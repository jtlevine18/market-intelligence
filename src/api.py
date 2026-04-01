"""
Market Intelligence Agent -- FastAPI Application

AI-powered market timing and routing for Tamil Nadu smallholder farmers.

Serves synthetic demo data for the dashboard when the pipeline hasn't run.
When the real pipeline has been run, serves pipeline results instead.

Endpoints:
- GET  /health                  -- Health check
- GET  /api/mandis              -- Mandi list with current reporting status
- GET  /api/market-prices       -- Reconciled prices by commodity x mandi
- GET  /api/price-forecast      -- 7/14/30d price predictions with confidence
- GET  /api/sell-recommendations -- Optimized sell options for sample farmers
- GET  /api/price-conflicts     -- Where Agmarknet and eNAM disagreed + resolution
- GET  /api/raw-inputs          -- Raw Agmarknet + eNAM data before processing
- GET  /api/extracted-data      -- Normalized data after extraction
- GET  /api/reconciled-data     -- Reconciled data with conflict log
- GET  /api/model-info          -- XGBoost metrics, feature importances
- GET  /api/pipeline/runs       -- Run history
- GET  /api/pipeline/stats      -- Aggregate stats
- POST /api/pipeline/trigger    -- Manual pipeline run
"""

import logging
import random
import threading
from datetime import datetime, date, timedelta
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from config import (
    COMMODITIES,
    COMMODITY_MAP,
    MANDIS,
    MANDI_MAP,
    PIPELINE_STEPS,
    SEASONAL_INDICES,
    BASE_PRICES_RS,
    POST_HARVEST_LOSS,
    SAMPLE_FARMERS,
    TRANSPORT_COST_RS_PER_QUINTAL_PER_KM,
    MIN_TRANSPORT_COST_RS,
    MANDI_FEE_PCT,
)
from src.geo import haversine_km
from src.store import store
from src.scheduler import scheduler

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Market Intelligence Agent",
    description="AI-powered market timing and routing for Tamil Nadu smallholder farmers",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

SEED = 42


# ── Demo data generation (deterministic, seed=42) ────────────────────────



def _demo_credit_readiness(farmer, best_option: dict, all_options: list, potential_gain: float) -> dict:
    """Generate demo credit readiness for a farmer based on sell optimization."""
    if not best_option or best_option.get("net_price_rs", 0) <= 0:
        return {"readiness": "not_yet", "advice_en": "No market data available.", "strengths": [], "risks": []}

    expected = best_option["net_price_rs"] * farmer.quantity_quintals
    worst_net = min((o.get("net_price_rs", 0) for o in all_options), default=0) if all_options else 0
    min_rev = worst_net * farmer.quantity_quintals
    max_advisable = expected * 0.40
    strengths = []
    risks = []

    if farmer.has_storage:
        strengths.append("Storage available — you can wait for better prices if needed")
    else:
        risks.append("No storage — you must sell quickly, limiting price flexibility")
    if expected > 25_000 * 2:
        strengths.append(f"Expected revenue (Rs {expected:,.0f}) is well above typical input costs")
    if potential_gain > 0:
        strengths.append(f"Agent found Rs {potential_gain:,.0f} more value by optimizing where and when you sell")

    if len(risks) == 0 and expected > 25_000 * 2:
        readiness = "strong"
        advice = (f"Your {farmer.quantity_quintals:.0f} quintals should earn ~Rs {expected:,.0f}. "
                  f"An input loan up to Rs {max_advisable:,.0f} looks manageable.")
    elif expected > 25_000 * 1.5:
        readiness = "moderate"
        advice = (f"Expected revenue: ~Rs {expected:,.0f}. A smaller loan could work, "
                  f"but keep it conservative (up to Rs {max_advisable:,.0f}).")
    else:
        readiness = "not_yet"
        advice = (f"Revenue is uncertain (~Rs {expected:,.0f}). Consider waiting until after harvest, "
                  f"or start with a very small amount.")

    return {
        "readiness": readiness,
        "expected_revenue_rs": round(expected, 0),
        "min_revenue_rs": round(min_rev, 0),
        "max_advisable_input_loan_rs": round(max_advisable, 0),
        "revenue_confidence": best_option.get("confidence", 0.7),
        "loan_to_revenue_pct": round(max_advisable / expected * 100, 1) if expected else 0,
        "strengths": strengths,
        "risks": risks,
        "advice_en": advice,
        "advice_ta": "",
    }


def _generate_demo_data() -> dict:
    """Deterministic synthetic data that tells a coherent story.

    Story:
    - It's late March 2026 (post-rabi harvest for rice, peak turmeric arrivals)
    - Rice prices are recovering from Jan-Feb trough, trending up toward lean season
    - Turmeric at Erode is near seasonal low due to heavy arrivals
    - Agmarknet and eNAM show 5-10% price divergence on several mandis
    - Banana prices are stable with slight festival-driven uptick
    - Sell recommendations show real tradeoffs (nearer mandi vs farther + higher price)
    """
    rng = random.Random(SEED)
    now = datetime(2026, 3, 31, 10, 0, 0)
    today = date(2026, 3, 31)
    month = today.month

    # ── Mandis ──
    mandis = []
    for m in MANDIS:
        mandis.append({
            "mandi_id": m.mandi_id,
            "name": m.name,
            "district": m.district,
            "state": m.state,
            "latitude": m.latitude,
            "longitude": m.longitude,
            "market_type": m.market_type,
            "enam_integrated": m.enam_integrated,
            "reporting_quality": m.reporting_quality,
            "commodities_traded": m.commodities_traded,
            "avg_daily_arrivals_tonnes": m.avg_daily_arrivals_tonnes,
        })

    # ── Reconciled market prices ──
    market_prices = []
    reconciled_by_mandi: dict[str, dict] = {}

    for m in MANDIS:
        reconciled_by_mandi[m.mandi_id] = {}
        for commodity in COMMODITIES:
            cid = commodity["id"]
            if cid not in m.commodities_traded:
                continue

            base = BASE_PRICES_RS.get(cid, 2000)
            seasonal = SEASONAL_INDICES.get(cid, {}).get(month, 1.0)

            mandi_factor = 1.0 + rng.uniform(-0.04, 0.06)
            if m.market_type == "terminal":
                mandi_factor += 0.02
            elif m.reporting_quality == "poor":
                mandi_factor -= 0.02

            price = round(base * seasonal * mandi_factor, 0)

            conf_map = {"good": rng.uniform(0.85, 0.95), "moderate": rng.uniform(0.70, 0.85), "poor": rng.uniform(0.55, 0.70)}
            confidence = conf_map.get(m.reporting_quality, 0.7)

            # Generate Agmarknet/eNAM split for display
            agm_price = round(price * rng.uniform(0.97, 1.03))
            enam_price_val = round(price * rng.uniform(0.95, 1.05)) if m.enam_integrated else None

            # Trend based on seasonal direction
            next_month_seasonal = SEASONAL_INDICES.get(cid, {}).get(month % 12 + 1, 1.0)
            if next_month_seasonal > seasonal * 1.02:
                trend = "up"
            elif next_month_seasonal < seasonal * 0.98:
                trend = "down"
            else:
                trend = "flat"

            market_prices.append({
                "mandi_id": m.mandi_id,
                "mandi_name": m.name,
                "commodity_id": cid,
                "commodity_name": commodity["name"],
                "category": commodity["category"],
                "price_rs": price,
                "agmarknet_price_rs": agm_price,
                "enam_price_rs": enam_price_val,
                "reconciled_price_rs": price,
                "confidence": round(confidence, 2),
                "price_trend": trend,
                "date": today.isoformat(),
                "source_used": "weighted_average" if m.enam_integrated else "agmarknet_only",
                "reasoning": (
                    f"Agmarknet and eNAM agree within 5% at {m.name}."
                    if confidence > 0.85 else
                    f"Minor conflict at {m.name} resolved by weighted average."
                ),
            })

            reconciled_by_mandi[m.mandi_id][cid] = {
                "price_rs": price,
                "confidence": round(confidence, 2),
            }

    # ── Price conflicts ──
    price_conflicts = []
    for m in MANDIS:
        if not m.enam_integrated:
            continue
        for commodity in COMMODITIES:
            cid = commodity["id"]
            if cid not in m.commodities_traded:
                continue
            if rng.random() > 0.35:
                continue

            base = BASE_PRICES_RS.get(cid, 2000)
            seasonal = SEASONAL_INDICES.get(cid, {}).get(month, 1.0)
            agm_price = round(base * seasonal * (1 + rng.uniform(-0.03, 0.03)), 0)

            divergence = rng.uniform(0.04, 0.12)
            enam_price = round(agm_price * (1 + divergence * (1 if rng.random() > 0.4 else -1)), 0)

            delta_pct = round(abs(enam_price - agm_price) / agm_price * 100, 1)
            reconciled_price = round(agm_price * 0.6 + enam_price * 0.4, 0)

            # Generate rich investigation reasoning showing the 5 reconciliation tools
            neighbor_price = round(agm_price * rng.uniform(0.97, 1.03))
            seasonal_low = round(base * min(SEASONAL_INDICES.get(cid, {}).values()))
            seasonal_high = round(base * max(SEASONAL_INDICES.get(cid, {}).values()))
            arrivals = round(rng.uniform(30, 200), 1)

            investigation_steps = [
                {
                    "tool": "compare_sources",
                    "finding": f"Agmarknet reports Rs {agm_price:,.0f}, eNAM reports Rs {enam_price:,.0f} ({delta_pct}% divergence). Agmarknet updated {rng.randint(2,8)}h ago, eNAM {rng.randint(1,4)}h ago.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": f"Nearest mandi reports Rs {neighbor_price:,.0f} for {commodity['name']} — {'consistent with Agmarknet' if abs(neighbor_price - agm_price) < abs(neighbor_price - enam_price) else 'closer to eNAM price'}.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": f"Seasonal range for {commodity['name']} in {'March' if month == 3 else 'April'}: Rs {seasonal_low:,.0f}–{seasonal_high:,.0f}. Both prices are within plausible range.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": f"Arrivals at {m.name}: {arrivals} tonnes. {'High arrivals support lower price' if enam_price < agm_price else 'Moderate arrivals — no strong supply signal'}.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": f"Spread of Rs {abs(agm_price - enam_price):,.0f} {'exceeds' if delta_pct > 8 else 'is within'} transport cost to neighboring mandis (~Rs {round(rng.uniform(80, 200)):,.0f}/quintal). {'Suspicious — markets should equilibrate.' if delta_pct > 8 else 'Within normal range.'}",
                },
            ]

            # Decision logic based on investigation
            if abs(neighbor_price - agm_price) < abs(neighbor_price - enam_price):
                trust = "Agmarknet"
                reconciled_price = round(agm_price * 0.65 + enam_price * 0.35)
                resolution_detail = f"Neighbor prices align with Agmarknet. Weighted 65/35 toward Agmarknet = Rs {reconciled_price:,.0f}."
            else:
                trust = "eNAM"
                reconciled_price = round(agm_price * 0.4 + enam_price * 0.6)
                resolution_detail = f"Neighbor prices align with eNAM. Weighted 40/60 toward eNAM = Rs {reconciled_price:,.0f}."

            price_conflicts.append({
                "mandi_id": m.mandi_id,
                "mandi_name": m.name,
                "commodity_id": cid,
                "commodity_name": commodity["name"],
                "agmarknet_price": agm_price,
                "enam_price": enam_price,
                "delta_pct": delta_pct,
                "resolution": f"weighted_toward_{trust.lower()}",
                "reconciled_price": reconciled_price,
                "investigation_steps": investigation_steps,
                "reasoning": resolution_detail,
            })

    # ── Enrich conflicts with realistic investigation narratives ──
    # Each conflict tells a different story about WHY two government databases disagreed.
    # Keyed on (mandi_id, commodity_id) to match the deterministic RNG output above.
    _conflict_narratives = {
        # ── Story: Stale eNAM data ──
        # Salem turmeric — eNAM hasn't updated since last session, Agmarknet is fresher
        ("MND-SLM", "TUR-FIN"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet reports modal price from 31 Mar auction (Rs 10,315/q). eNAM shows last-traded price from 29 Mar (Rs 9,480/q). The 2-day lag explains Rs 835 gap — eNAM hasn't updated since Saturday's session.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Erode Turmeric Market (38km) reports Rs 10,480 on 31 Mar. Karur (55km) reports Rs 10,250. Both align with Agmarknet's Rs 10,315, not eNAM's stale Rs 9,480.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "March turmeric prices typically 8-12% below annual average as rabi harvest peaks. Rs 10,315 falls within expected seasonal band. Rs 9,480 would be 18% below — unusually low even for post-harvest glut.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Arrival volume 185 quintals vs 7-day average 210. Normal range — no supply shock that would justify eNAM's discount.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Salem-to-Erode transport cost Rs 95/q. Price gap of Rs 835 far exceeds transport cost — if eNAM's price were real, traders would already be buying at Salem and selling at Erode.",
                },
            ],
            "reasoning": "eNAM data is 2 days stale (last updated Saturday). Agmarknet's Monday auction price is corroborated by Erode and Karur. Trust Agmarknet.",
            "resolution": "trust_agmarknet",
            "confidence": 0.92,
        },
        # ── Story: Genuine regional price difference (aggregation method) ──
        # Tiruchirappalli rice — both sources are same-day but use different aggregation
        ("MND-TRC", "RICE-SAMBA"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Both sources report same-day data (31 Mar). Agmarknet modal price Rs 2,047/q. eNAM weighted-average price Rs 2,275/q. Different aggregation methods — modal vs weighted average of all transactions.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Thanjavur (45km) reports Rs 2,020. Kumbakonam (35km) reports Rs 2,080. Cluster average Rs 2,050 sits closer to Agmarknet but eNAM's weighted average captures some premium lots.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "Late-March Samba rice typically near seasonal low as rabi harvest arrives. Rs 2,047-2,275 range is within 5% of expected seasonal index (0.92). Both plausible.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Tiruchirappalli arrivals 420 quintals — 20% above 7-day average of 350. Harvest surge explains downward pressure on modal price while premium lots still trade higher.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Price gap (Rs 228) vs Thanjavur transport (Rs 113/q). Gap is 2x transport cost but Thanjavur at Rs 2,020 — arbitrage partially closed. Remaining gap reflects aggregation method, not a true market inefficiency.",
                },
            ],
            "reasoning": "Both sources report same-day but use different methods: Agmarknet's modal price reflects the most common transaction; eNAM's weighted average includes premium lots. Weighted 60/40 toward Agmarknet.",
            "resolution": "weighted_average",
            "confidence": 0.78,
        },
        # ── Story: Seasonal anomaly — eNAM price doesn't match seasonal pattern ──
        # Coimbatore onion — eNAM shows price that's premature for the season
        ("MND-CBE", "ONI-RED"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet reports Rs 1,534/q (31 Mar). eNAM reports Rs 1,473/q (31 Mar). Both same-day. Gap of Rs 61 (4.0%) — modest divergence but directionally interesting: eNAM is lower.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Dindigul (65km) reports Rs 1,520. Madurai Periyar (98km) reports Rs 1,550. Regional cluster Rs 1,520-1,550 strongly supports Agmarknet's range.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "March onion prices typically at seasonal low (index 0.85) before summer spike begins in April-May. Rs 1,534 matches seasonal pattern. Rs 1,473 suggests deeper-than-expected trough — possibly one distressed lot pulling down eNAM's average.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Arrivals 165 quintals vs 7-day avg 180. Slight decline but not enough to justify downward pressure. Rabi onion harvest is winding down normally.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Coimbatore-to-Dindigul transport Rs 163/q. eNAM discount of Rs 61 is well within transport cost — no arbitrage opportunity. Likely a small-lot distressed sale on eNAM.",
                },
            ],
            "reasoning": "Regional mandis and seasonal pattern both support Agmarknet's price. eNAM's lower figure likely reflects a distressed small-lot sale, not the prevailing market rate. Trust Agmarknet.",
            "resolution": "trust_agmarknet",
            "confidence": 0.88,
        },
        # ── Story: Volume spike / outlier transaction ──
        # Salem groundnut — eNAM higher due to a thin-volume premium lot
        ("MND-SLM", "GNUT-POD"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet Rs 5,964/q. eNAM Rs 6,288/q. eNAM is higher by Rs 324 (5.4%). Both same-day data.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Coimbatore (85km) Rs 5,857. Erode (45km) — no groundnut trading. Karur (50km) Rs 5,900. Cluster Rs 5,857-5,900 aligns with Agmarknet, not eNAM's premium.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "March groundnut typically at seasonal baseline (index 1.00) before crushing-season demand lifts April-May prices. Rs 5,964 consistent with seasonal expectation.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Arrivals 95 quintals — 35% BELOW 7-day average of 145. Low supply day. eNAM likely recorded a premium lot from a single large buyer bidding up a thin market.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Gap Rs 324. Karur transport Rs 125/q. Gap is 2.6x transport — if eNAM's price were prevailing, Karur traders would already be shipping groundnut to Salem. They aren't.",
                },
            ],
            "reasoning": "eNAM recorded a premium lot on a thin-volume day (arrivals 35% below average). Regional mandis and seasonal norms both support Agmarknet's price. Trust Agmarknet.",
            "resolution": "trust_agmarknet",
            "confidence": 0.90,
        },
        # ── Story: Reporting lag + weekend effect ──
        # Madurai cotton — eNAM captured Friday's closing, Agmarknet has Monday's opening
        ("MND-MDR", "COT-MCU"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet Rs 6,897/q (Monday 31 Mar opening). eNAM Rs 7,356/q (Friday 28 Mar close). Weekend gap — eNAM hasn't synced Monday's session yet. Rs 459 spread (6.7%).",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Coimbatore (210km) reports Rs 6,880 on 31 Mar. Karur (150km) reports Rs 6,920. Monday prices across the region are Rs 6,880-6,920, consistent with Agmarknet.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "Cotton at seasonal baseline (index 1.00) in March before summer mill procurement. Rs 6,897 tracks the index. eNAM's Rs 7,356 implies a 7% premium over seasonal norm — would require a demand shock that didn't happen.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Monday arrivals 245 quintals — slightly above 7-day average of 230. Normal post-weekend restock. No supply constraint to justify eNAM's premium.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Madurai-to-Coimbatore transport Rs 525/q (long haul). But Karur at Rs 6,920 with Rs 375/q transport — the Rs 459 spread exceeds Karur-to-Madurai cost of Rs 375. If eNAM were current, arbitrage would close the gap.",
                },
            ],
            "reasoning": "Classic weekend lag: eNAM shows Friday's closing price, Agmarknet reports Monday's opening. Regional mandis confirm Monday's lower level. Trust Agmarknet (fresher data).",
            "resolution": "trust_agmarknet",
            "confidence": 0.91,
        },
        # ── Story: Harvest surplus depressing modal price ──
        # Madurai maize — Agmarknet's modal price pushed down by harvest glut
        ("MND-MDR", "MZE-YEL"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet Rs 1,889/q. eNAM Rs 1,684/q. Unusual — eNAM is LOWER by Rs 205 (10.9%). Both report 31 Mar data.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Dindigul (65km) reports Rs 1,850. Tiruchirappalli (130km) reports Rs 1,870. Regional cluster Rs 1,850-1,870 supports Agmarknet's range.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "March maize near seasonal low (index 0.88) as rabi harvest arrives. Rs 1,889 is within expected band. Rs 1,684 would be 20% below annual average — implausibly low.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Arrivals 310 quintals — 45% above 7-day average of 215. Harvest surge. eNAM appears to have captured distressed early-morning lots sold at discount before the auction floor stabilized.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Gap Rs 205. Dindigul transport Rs 163/q. eNAM's low price would create immediate arbitrage from Dindigul — but Dindigul traders report normal flows. eNAM's price is an outlier, not the market.",
                },
            ],
            "reasoning": "eNAM captured early-morning distressed lots during harvest surge. Agmarknet's modal price reflects the stabilized auction floor, corroborated by Dindigul and Tiruchirappalli. Trust Agmarknet.",
            "resolution": "trust_agmarknet",
            "confidence": 0.87,
        },
        # ── Story: Festival demand spike in eNAM ──
        # Madurai banana — eNAM lower but Agmarknet captures festival premium lots
        ("MND-MDR", "BAN-ROB"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet Rs 1,666/q. eNAM Rs 1,496/q. eNAM is lower by Rs 170 (10.2%). Both same-day. Banana is perishable — price gaps close fast.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Dindigul (65km) reports Rs 1,620. Coimbatore (210km) reports Rs 1,707. Wide geographic spread: Rs 1,620-1,707. Madurai sits in the middle.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "March banana at seasonal low (index 0.95). Rs 1,666 is plausible. Rs 1,496 would be 12% below average — unusually cheap for a perishable with steady demand.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Arrivals 380 quintals — 15% above 7-day average of 330. Good supply but banana demand is steady. eNAM likely recorded a bulk wholesale lot at discount.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Gap Rs 170. Dindigul transport Rs 163/q. Margin nearly zero — no profitable arbitrage, which means the gap is a reporting artifact, not a real market opportunity.",
                },
            ],
            "reasoning": "eNAM recorded a bulk wholesale discount lot. Agmarknet's modal price better reflects retail-wholesale prevailing rate. Neighboring mandis split the difference. Weighted 65/35 toward Agmarknet.",
            "resolution": "weighted_toward_agmarknet",
            "confidence": 0.82,
        },
        # ── Story: Coimbatore groundnut — processor premium in Agmarknet ──
        ("MND-CBE", "GNUT-POD"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet Rs 5,857/q. eNAM Rs 5,468/q. Agmarknet is higher by Rs 389 (6.6%). Both same-day. Coimbatore is a major oil-mill hub — processors bid aggressively in the auction.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Salem (85km) Rs 5,964. Dindigul (90km) Rs 5,800. Cluster Rs 5,800-5,964 — Coimbatore's Agmarknet price sits squarely in this range.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "March groundnut at seasonal baseline (index 1.00). Rs 5,857 is consistent. Rs 5,468 would be 6% below baseline — possible but unusual with crushing season approaching.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Arrivals 210 quintals vs 7-day average 195. Slightly above normal. Oil mills actively procuring ahead of crushing season, supporting Agmarknet's higher auction price.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Gap Rs 389. Salem transport Rs 213/q. Gap is 1.8x transport — borderline. Some Salem traders are indeed shipping to Coimbatore to capture the processor premium, which should narrow the gap within days.",
                },
            ],
            "reasoning": "Coimbatore oil mills bid up Agmarknet's auction price ahead of crushing season. eNAM captures older or non-processor transactions. Regional prices support Agmarknet. Trust Agmarknet.",
            "resolution": "trust_agmarknet",
            "confidence": 0.86,
        },
        # ── Story: Coimbatore cotton — quality grade mismatch ──
        ("MND-CBE", "COT-MCU"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet Rs 6,880/q. eNAM Rs 6,300/q. Gap Rs 580 (8.4%). Both same-day. Significant — cotton prices don't usually vary this much within a single mandi.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Erode (65km) Rs 6,950. Karur (80km) Rs 6,920. Madurai Periyar (210km) Rs 6,897. All three neighbors cluster near Rs 6,900, strongly supporting Agmarknet.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "March cotton at seasonal baseline (index 1.00). Rs 6,880 matches perfectly. Rs 6,300 would be 7% below — would indicate off-grade or short-staple cotton.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Arrivals 195 quintals vs 7-day average 200. Normal volume. No supply disruption. The gap likely reflects a grade mismatch — eNAM may be reporting a short-staple MCU-5 lot while Agmarknet reports the standard MCU-7.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Gap Rs 580. Erode transport Rs 163/q. Gap is 3.6x transport cost — if same grade, traders would flood Coimbatore. They aren't, confirming this is a grade/quality difference, not a price discrepancy.",
                },
            ],
            "reasoning": "Likely a cotton grade mismatch: eNAM recorded a short-staple lot (MCU-5) while Agmarknet reports standard MCU-7. Three neighboring mandis confirm Rs 6,880-6,950 for standard grade. Trust Agmarknet for MCU-7 benchmark.",
            "resolution": "trust_agmarknet",
            "confidence": 0.85,
        },
        # ── Story: Coimbatore banana — cold chain disruption premium ──
        ("MND-CBE", "BAN-ROB"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet Rs 1,707/q. eNAM Rs 1,898/q. eNAM is HIGHER by Rs 191 (11.2%). Both same-day. Unusual for eNAM to report a premium.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Dindigul (65km) Rs 1,620. Madurai Periyar (98km) Rs 1,666. Regional cluster Rs 1,620-1,707. eNAM's Rs 1,898 is a clear outlier.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "March banana at index 0.95 (slight seasonal dip). Rs 1,707 is consistent. Rs 1,898 would imply index 1.06 — a premium typically seen only during October-November festival season.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Arrivals 145 quintals — 30% BELOW 7-day average of 210. Significant supply drop. A banana shipment from Theni was delayed due to truck breakdown on NH-44, creating temporary scarcity that spiked eNAM's price.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Gap Rs 191. Dindigul transport Rs 163/q. Margin of Rs 28/q — barely profitable. With banana's high perishability (3% transport loss), arbitrage isn't viable. The premium will self-correct when the delayed shipment arrives.",
                },
            ],
            "reasoning": "Temporary supply disruption (delayed Theni shipment) spiked eNAM's price on a thin-volume day. Agmarknet's auction price reflects normal supply. Premium will self-correct. Trust Agmarknet.",
            "resolution": "trust_agmarknet",
            "confidence": 0.84,
        },
        # ── Story: Kumbakonam black gram — procurement agent distortion ──
        ("MND-KBK", "URD-BLK"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet Rs 7,785/q. eNAM Rs 6,971/q. eNAM is lower by Rs 814 (10.5%). Both same-day. Large gap for a staple pulse.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Thanjavur (25km) Rs 7,650. Tiruchirappalli (55km) Rs 7,700. Ramanathapuram (120km) — no eNAM. Cluster Rs 7,650-7,700 supports Agmarknet range.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "March urad at seasonal high (index 1.05) as kharif stocks deplete before next harvest. Rs 7,785 is consistent with lean-season premium. Rs 6,971 would be below baseline — implausible in March.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Arrivals 85 quintals — 40% below 7-day average of 140. Very thin market day. A government procurement agent may have listed a below-market reserved-price lot on eNAM, pulling down the average.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Gap Rs 814. Thanjavur transport Rs 63/q. Gap is 13x transport cost — if eNAM's price were real, every trader in the delta would converge on Kumbakonam. This is clearly a reporting anomaly.",
                },
            ],
            "reasoning": "eNAM likely recorded a government procurement lot at reserved price on a thin-volume day. Thanjavur and Tiruchirappalli confirm market rate near Rs 7,700. Trust Agmarknet.",
            "resolution": "trust_agmarknet",
            "confidence": 0.89,
        },
        # ── Story: Vellore rice — different variety mix ──
        ("MND-VLR", "RICE-SAMBA"): {
            "investigation_steps": [
                {
                    "tool": "compare_sources",
                    "finding": "Agmarknet Rs 1,979/q. eNAM Rs 2,132/q. eNAM higher by Rs 153 (7.7%). Both same-day. Vellore trades both Samba and Ponni rice — variety mix may explain the gap.",
                },
                {
                    "tool": "check_neighboring_mandis",
                    "finding": "Villupuram (85km) Rs 2,000. Tiruchirappalli (180km) Rs 2,047. Cluster Rs 2,000-2,047 — closer to Agmarknet. Vellore is at the northern edge of the Samba belt, with more Ponni trading.",
                },
                {
                    "tool": "seasonal_norm_check",
                    "finding": "March Samba rice at seasonal index 0.92 (post-rabi trough). Rs 1,979 matches. Rs 2,132 would be index 0.97 — plausible only if some Ponni (which commands a 5-8% premium) is mixed into eNAM's average.",
                },
                {
                    "tool": "verify_arrival_volumes",
                    "finding": "Arrivals 120 quintals vs 7-day average of 135. Slightly below normal. Vellore's mixed-variety market means eNAM's weighted average naturally skews higher when Ponni lots dominate.",
                },
                {
                    "tool": "transport_arbitrage_check",
                    "finding": "Gap Rs 153. Villupuram transport Rs 213/q. Transport cost exceeds the price gap — no arbitrage possible. Gap is explainable by variety composition, not market inefficiency.",
                },
            ],
            "reasoning": "Vellore trades both Samba and Ponni rice. eNAM's weighted average includes premium Ponni lots, inflating the figure. Agmarknet's modal price better reflects pure Samba. Weighted 60/40 toward Agmarknet.",
            "resolution": "weighted_average",
            "confidence": 0.80,
        },
    }

    # Apply narrative overrides to conflicts (preserves all other fields)
    for conflict in price_conflicts:
        key = (conflict["mandi_id"], conflict["commodity_id"])
        if key in _conflict_narratives:
            narrative = _conflict_narratives[key]
            conflict["investigation_steps"] = narrative["investigation_steps"]
            conflict["reasoning"] = narrative["reasoning"]
            if "resolution" in narrative:
                conflict["resolution"] = narrative["resolution"]
            if "confidence" in narrative:
                # Update the reconciled price based on narrative confidence/resolution
                agm = conflict["agmarknet_price"]
                enam = conflict["enam_price"]
                res = narrative["resolution"]
                if res == "trust_agmarknet":
                    conflict["reconciled_price"] = round(agm * 0.92 + enam * 0.08)
                elif res == "weighted_average":
                    conflict["reconciled_price"] = round(agm * 0.60 + enam * 0.40)
                elif res == "weighted_toward_agmarknet":
                    conflict["reconciled_price"] = round(agm * 0.65 + enam * 0.35)

    # ── Price forecasts ──
    price_forecasts = []
    forecast_by_mandi: dict[str, dict] = {}

    for m in MANDIS:
        forecast_by_mandi[m.mandi_id] = {}
        for commodity in COMMODITIES:
            cid = commodity["id"]
            if cid not in m.commodities_traded:
                continue

            current = reconciled_by_mandi.get(m.mandi_id, {}).get(cid, {}).get("price_rs", 0)
            if current <= 0:
                continue

            s7 = SEASONAL_INDICES.get(cid, {}).get((today + timedelta(days=7)).month, 1.0)
            s14 = SEASONAL_INDICES.get(cid, {}).get((today + timedelta(days=14)).month, 1.0)
            s30 = SEASONAL_INDICES.get(cid, {}).get((today + timedelta(days=30)).month, 1.0)
            s_now = SEASONAL_INDICES.get(cid, {}).get(month, 1.0)

            p7 = round(current * s7 / max(0.5, s_now) * (1 + rng.gauss(0, 0.01)), 0)
            p14 = round(current * s14 / max(0.5, s_now) * (1 + rng.gauss(0, 0.015)), 0)
            p30 = round(current * s30 / max(0.5, s_now) * (1 + rng.gauss(0, 0.02)), 0)

            vol = rng.uniform(0.04, 0.10)
            ci7 = round(current * vol * 0.5, 0)
            ci14 = round(current * vol * 0.7, 0)
            ci30 = round(current * vol * 1.0, 0)

            pct_change = (p7 - current) / current if current else 0
            direction = "up" if pct_change > 0.02 else "down" if pct_change < -0.02 else "flat"

            price_forecasts.append({
                "mandi_id": m.mandi_id,
                "mandi_name": m.name,
                "commodity_id": cid,
                "commodity_name": commodity["name"],
                "current_price_rs": current,
                "price_7d": p7,
                "price_14d": p14,
                "price_30d": p30,
                "ci_lower_7d": p7 - ci7,
                "ci_upper_7d": p7 + ci7,
                "ci_lower_14d": p14 - ci14,
                "ci_upper_14d": p14 + ci14,
                "ci_lower_30d": p30 - ci30,
                "ci_upper_30d": p30 + ci30,
                "direction": direction,
                "confidence": round(rng.uniform(0.65, 0.88), 2),
                "seasonal_index": round(s_now, 2),
            })

            forecast_by_mandi[m.mandi_id][cid] = {
                "price_7d": p7,
                "price_14d": p14,
                "price_30d": p30,
            }

    # ── Sell recommendations ──
    sell_recommendations = []
    for farmer in SAMPLE_FARMERS:
        commodity = COMMODITY_MAP.get(farmer.primary_commodity, {})
        options = []

        for m in MANDIS:
            if farmer.primary_commodity not in m.commodities_traded:
                continue
            dist = haversine_km(farmer.latitude, farmer.longitude, m.latitude, m.longitude)
            if dist > 60:
                continue

            transport = max(MIN_TRANSPORT_COST_RS, dist * TRANSPORT_COST_RS_PER_QUINTAL_PER_KM)
            current_price = reconciled_by_mandi.get(m.mandi_id, {}).get(farmer.primary_commodity, {}).get("price_rs", 0)
            if current_price <= 0:
                continue

            mandi_fee = current_price * MANDI_FEE_PCT / 100
            net_now = current_price - transport - mandi_fee

            options.append({
                "mandi_id": m.mandi_id,
                "mandi_name": m.name,
                "sell_timing": "now",
                "market_price_rs": current_price,
                "transport_cost_rs": round(transport, 0),
                "storage_loss_rs": 0,
                "storage_cost_rs": 0,
                "mandi_fee_rs": round(mandi_fee, 0),
                "net_price_rs": round(net_now, 0),
                "distance_km": round(dist, 1),
                "drive_time_min": round(dist / 30 * 60),
                "confidence": 0.85,
                "price_source": "current",
            })

            fc = forecast_by_mandi.get(m.mandi_id, {}).get(farmer.primary_commodity, {})
            p7 = fc.get("price_7d", 0)
            if p7 > 0:
                loss_pct = POST_HARVEST_LOSS.get(farmer.primary_commodity, {}).get("storage_per_month", 2.5)
                storage_loss = p7 * (loss_pct / 100) * (7 / 30)
                net_7d = p7 - transport - p7 * MANDI_FEE_PCT / 100 - storage_loss
                storage_cost = 20.0 * (7 / 30)
                options.append({
                    "mandi_id": m.mandi_id,
                    "mandi_name": m.name,
                    "sell_timing": "7d",
                    "market_price_rs": p7,
                    "transport_cost_rs": round(transport, 0),
                    "storage_loss_rs": round(storage_loss, 0),
                    "storage_cost_rs": round(storage_cost, 0),
                    "mandi_fee_rs": round(p7 * MANDI_FEE_PCT / 100, 0),
                    "net_price_rs": round(net_7d, 0),
                    "distance_km": round(dist, 1),
                    "drive_time_min": round(dist / 30 * 60),
                    "confidence": 0.78,
                    "price_source": "forecasted",
                })

        options.sort(key=lambda o: o["net_price_rs"], reverse=True)
        best = options[0] if options else {}

        nearest_now = sorted(
            [o for o in options if o.get("sell_timing") == "now"],
            key=lambda o: o.get("distance_km", 999),
        )
        nearest_now_price = nearest_now[0]["net_price_rs"] if nearest_now else 0
        potential_gain = (best.get("net_price_rs", 0) - nearest_now_price) * farmer.quantity_quintals

        sell_recommendations.append({
            "commodity_id": farmer.primary_commodity,
            "commodity_name": commodity.get("name", ""),
            "quantity_quintals": farmer.quantity_quintals,
            "farmer_id": farmer.farmer_id,
            "farmer_name": farmer.name,
            "farmer_lat": farmer.latitude,
            "farmer_lon": farmer.longitude,
            "best_option": best,
            "all_options": options[:12],
            "potential_gain_rs": round(potential_gain, 0),
            "recommendation_text": (
                f"{farmer.name}: Best option is {best.get('mandi_name', 'N/A')} "
                f"({best.get('sell_timing', 'now')}). "
                f"Net Rs {best.get('net_price_rs', 0):,.0f}/quintal "
                f"after transport Rs {best.get('transport_cost_rs', 0):,.0f} and fees."
            ) if best else "No mandis in range.",
            "recommendation_tamil": (
                f"{farmer.name}: சிறந்த விருப்பம் {best.get('mandi_name', 'N/A')} "
                f"({best.get('sell_timing', 'இப்போது')}). "
                f"நிகர ₹{best.get('net_price_rs', 0):,.0f}/குவிண்டால் "
                f"போக்குவரத்து ₹{best.get('transport_cost_rs', 0):,.0f} கழித்த பிறகு."
            ) if best else "சந்தைகள் எதுவும் இல்லை.",
            "credit_readiness": _demo_credit_readiness(farmer, best, options, potential_gain),
        })

    # ── Raw inputs (summary) ──
    raw_inputs = {
        "agmarknet": {
            "mandis_queried": len(MANDIS),
            "records_fetched": rng.randint(800, 1200),
            "date_range": f"{(today - timedelta(days=30)).isoformat()} to {today.isoformat()}",
        },
        "enam": {
            "mandis_queried": sum(1 for m in MANDIS if m.enam_integrated),
            "records_fetched": rng.randint(200, 400),
            "date_range": f"{(today - timedelta(days=14)).isoformat()} to {today.isoformat()}",
        },
        "nasa_power": {
            "mandis_queried": len(MANDIS),
            "readings_fetched": rng.randint(900, 1350),
            "parameters": ["PRECTOTCORR", "T2M", "T2M_MAX", "T2M_MIN", "RH2M"],
        },
    }

    # ── Extracted data ──
    extracted_data = {}
    for m in MANDIS:
        extracted_data[m.mandi_id] = {
            "mandi_id": m.mandi_id,
            "normalized_count": rng.randint(30, 60),
            "stale_count": rng.randint(0, 5) if m.reporting_quality != "good" else 0,
            "anomaly_count": rng.randint(0, 2),
            "confidence": {"good": 0.92, "moderate": 0.78, "poor": 0.60}.get(m.reporting_quality, 0.7),
            "method": "rule_based",
        }

    # ── Reconciliation results ──
    reconciliation_results = {}
    for m in MANDIS:
        reconciliation_results[m.mandi_id] = reconciled_by_mandi.get(m.mandi_id, {})

    # ── Model metrics ──
    model_metrics = {
        "model_type": "xgboost",
        "rmse": 87.4,
        "mae": 62.1,
        "r2": 0.89,
        "directional_accuracy": 0.76,
        "train_samples": 4200,
        "features": [
            "current_reconciled_price", "price_trend_7d", "seasonal_index",
            "mandi_arrival_volume_7d_avg", "rainfall_7d", "days_since_harvest",
        ],
        "feature_importances": {
            "current_reconciled_price": 0.28,
            "seasonal_index": 0.18,
            "price_trend_7d": 0.14,
            "mandi_arrival_volume_7d_avg": 0.12,
            "rainfall_7d": 0.08,
            "days_since_harvest": 0.07,
            "price_volatility_30d": 0.05,
            "temperature_7d_avg": 0.04,
            "month_sin": 0.02,
            "month_cos": 0.02,
        },
    }

    # ── Recommendation reasoning ──
    recommendation_reasoning = [
        {
            "farmer_id": "FMR-LKSH",
            "farmer_name": "Lakshmi",
            "tool": "get_market_summary",
            "input": {"commodity_id": "RICE-SAMBA"},
            "result_summary": "Rice prices across 8 mandis: Rs 1,980-2,250. Thanjavur lowest (production hub).",
        },
        {
            "farmer_id": "FMR-LKSH",
            "farmer_name": "Lakshmi",
            "tool": "get_price_forecast",
            "input": {"commodity_id": "RICE-SAMBA", "mandi_id": "MND-KBK"},
            "result_summary": "Kumbakonam: +3.5% in 7d (seasonal uptick), +6% in 30d. Confidence: 0.82.",
        },
        {
            "farmer_id": "FMR-KUMR",
            "farmer_name": "Kumar",
            "tool": "get_storage_analysis",
            "input": {"commodity_id": "TUR-FIN", "current_price_rs": 10800},
            "result_summary": "Turmeric stores well: 1.5%/month loss. Hold 2 months = 3% loss vs 15-25% price gain.",
        },
        {
            "farmer_id": "FMR-MEEN",
            "farmer_name": "Meena",
            "tool": "get_weather_outlook",
            "input": {"latitude": 10.36, "longitude": 77.97},
            "result_summary": "Light rain day 3-4. Banana must sell within 5 days. Transport risky on day 3.",
        },
    ]

    # ── Pipeline runs ──
    pipeline_runs = []
    for i in range(12):
        run_date = now - timedelta(days=i * 2)
        duration = rng.uniform(15, 60)
        cost = rng.uniform(0.02, 0.08)
        status = "ok" if rng.random() > 0.1 else "partial"
        pipeline_runs.append({
            "run_id": f"run-{3000 + i}",
            "started_at": run_date.isoformat(),
            "ended_at": (run_date + timedelta(seconds=duration)).isoformat(),
            "status": status,
            "duration_s": round(duration, 1),
            "mandis_processed": len(MANDIS),
            "commodities_tracked": len(COMMODITIES),
            "price_conflicts_found": rng.randint(3, 12),
            "total_cost_usd": round(cost, 4),
            "steps": [
                {"step": s, "status": "ok", "duration_s": round(duration / 6, 1)}
                for s in PIPELINE_STEPS
            ],
        })

    # ── Stats ──
    stats = {
        "total_runs": len(pipeline_runs),
        "successful_runs": sum(1 for r in pipeline_runs if r["status"] == "ok"),
        "success_rate": round(
            sum(1 for r in pipeline_runs if r["status"] == "ok") / len(pipeline_runs), 2,
        ),
        "mandis_monitored": len(MANDIS),
        "commodities_tracked": len(COMMODITIES),
        "price_conflicts_found": len(price_conflicts),
        "total_cost_usd": round(sum(r["total_cost_usd"] for r in pipeline_runs), 2),
        "avg_cost_per_run_usd": round(
            sum(r["total_cost_usd"] for r in pipeline_runs) / len(pipeline_runs), 4,
        ),
        "last_run": pipeline_runs[0]["started_at"],
        "data_sources": ["Agmarknet (data.gov.in)", "eNAM", "NASA POWER"],
    }

    return {
        "mandis": mandis,
        "market_prices": market_prices,
        "price_forecasts": price_forecasts,
        "sell_recommendations": sell_recommendations,
        "price_conflicts": price_conflicts,
        "pipeline_runs": pipeline_runs,
        "stats": stats,
        "raw_inputs": raw_inputs,
        "extracted_data": extracted_data,
        "reconciliation_results": reconciliation_results,
        "model_metrics": model_metrics,
        "recommendation_reasoning": recommendation_reasoning,
    }


_demo_cache: dict | None = None
_demo_lock = threading.Lock()


def _get_demo() -> dict:
    global _demo_cache
    if _demo_cache is None:
        with _demo_lock:
            if _demo_cache is None:
                _demo_cache = _generate_demo_data()
    return _demo_cache


def _get(key: str, default=None):
    if default is None:
        default = []
    if store.has_real_data:
        val = getattr(store, key, None)
        if val:
            return val
    return _get_demo().get(key, default)


def _source() -> str:
    return "pipeline" if store.has_real_data else "demo"


# ── API Endpoints ────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "market-intelligence-agent",
        "version": "1.0.0",
        "pipeline_data": store.has_real_data,
    }


@app.get("/api/mandis")
def get_mandis():
    mandis = _get("mandis")
    return {"mandis": mandis, "total": len(mandis), "source": _source()}


@app.get("/api/market-prices")
def get_market_prices(
    mandi_id: str | None = Query(default=None),
    commodity_id: str | None = Query(default=None),
):
    prices = _get("market_prices")
    if mandi_id:
        prices = [p for p in prices if p.get("mandi_id") == mandi_id]
    if commodity_id:
        prices = [p for p in prices if p.get("commodity_id") == commodity_id]
    return {"market_prices": prices, "total": len(prices), "source": _source()}


@app.get("/api/price-forecast")
def get_price_forecast(
    mandi_id: str | None = Query(default=None),
    commodity_id: str | None = Query(default=None),
):
    forecasts = _get("price_forecasts")
    if mandi_id:
        forecasts = [f for f in forecasts if f.get("mandi_id") == mandi_id]
    if commodity_id:
        forecasts = [f for f in forecasts if f.get("commodity_id") == commodity_id]
    return {"price_forecasts": forecasts, "total": len(forecasts), "source": _source()}


@app.get("/api/sell-recommendations")
def get_sell_recommendations(farmer_id: str | None = Query(default=None)):
    recs = _get("sell_recommendations")
    if farmer_id:
        recs = [r for r in recs if r.get("farmer_id") == farmer_id]
    return {"sell_recommendations": recs, "total": len(recs), "source": _source()}


@app.get("/api/price-conflicts")
def get_price_conflicts(
    mandi_id: str | None = Query(default=None),
    commodity_id: str | None = Query(default=None),
):
    conflicts = _get("price_conflicts")
    if mandi_id:
        conflicts = [c for c in conflicts if c.get("mandi_id") == mandi_id]
    if commodity_id:
        conflicts = [c for c in conflicts if c.get("commodity_id") == commodity_id]
    return {"price_conflicts": conflicts, "total": len(conflicts), "source": _source()}


@app.get("/api/raw-inputs")
def get_raw_inputs():
    return {"raw_inputs": _get("raw_inputs", default={}), "source": _source()}


@app.get("/api/extracted-data")
def get_extracted_data(mandi_id: str | None = Query(default=None)):
    data = _get("extracted_data", default={})
    if mandi_id and isinstance(data, dict):
        fac_data = data.get(mandi_id)
        data = {mandi_id: fac_data} if fac_data else {}
    return {"extracted_data": data, "total_mandis": len(data) if isinstance(data, dict) else 0, "source": _source()}


@app.get("/api/reconciled-data")
def get_reconciled_data(mandi_id: str | None = Query(default=None)):
    data = _get("reconciliation_results", default={})
    if mandi_id and isinstance(data, dict):
        fac_data = data.get(mandi_id)
        data = {mandi_id: fac_data} if fac_data else {}
    return {"reconciled_data": data, "total_mandis": len(data) if isinstance(data, dict) else 0, "source": _source()}


@app.get("/api/model-info")
def get_model_info():
    model_metrics = _get("model_metrics", default={})
    ml_stack = {
        "primary_model": {
            "type": "XGBoost Regressor (200 estimators, 3 horizons: 7d/14d/30d)",
            "features": 15,
            "metrics": {k: model_metrics.get(k) for k in ("rmse", "mae", "r2", "directional_accuracy") if model_metrics.get(k) is not None},
        },
        "rag": {
            "type": "Hybrid FAISS + BM25 with sentence-transformers (all-MiniLM-L6-v2)",
            "purpose": "Agricultural marketing knowledge retrieval for recommendations",
            "chunks": 28,
        },
        "agents": {
            "extraction": "Claude tool-use agent (5 tools) with regex fallback",
            "reconciliation": "Claude cross-validation agent (5 tools) with rule-based fallback",
            "recommendation": "Claude broker agent (5 tools) with template fallback",
        },
    }
    return {"model_metrics": model_metrics, "ml_stack": ml_stack, "source": _source()}


@app.get("/api/pipeline/runs")
def get_pipeline_runs():
    runs = _get("pipeline_runs")
    return {"runs": runs, "total": len(runs)}


@app.get("/api/pipeline/stats")
def get_pipeline_stats():
    return _get("stats", default={})


@app.post("/api/pipeline/trigger")
def trigger_pipeline():
    return scheduler.trigger()


@app.get("/api/pipeline/status")
def pipeline_status():
    return scheduler.progress


@app.get("/api/db/health")
def db_health():
    from src.db import health_check
    return health_check()


# ── Status page ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def status_page():
    stats = _get("stats", default={})
    conflicts = _get("price_conflicts")
    mandis = _get("mandis")

    n_mandis = stats.get("mandis_monitored", len(mandis))
    n_commodities = stats.get("commodities_tracked", len(COMMODITIES))
    success_rate = stats.get("success_rate", 0)
    n_conflicts = stats.get("price_conflicts_found", len(conflicts))

    conflict_rows = ""
    for c in conflicts[:6]:
        conflict_rows += f"""
        <tr>
            <td>{c.get('mandi_name', '')}</td>
            <td>{c.get('commodity_name', '')}</td>
            <td>Rs {c.get('agmarknet_price', 0):,.0f}</td>
            <td>Rs {c.get('enam_price', 0):,.0f}</td>
            <td>{c.get('delta_pct', 0)}%</td>
            <td>Rs {c.get('reconciled_price', 0):,.0f}</td>
        </tr>"""

    if not conflict_rows:
        conflict_rows = '<tr><td colspan="6" style="color:#888;text-align:center;padding:16px;">No price conflicts detected</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Market Intelligence Agent -- API Status</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; background: #faf8f5; color: #1a1a1a; padding: 32px; max-width: 780px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; font-weight: 700; margin-bottom: 4px; }}
  .subtitle {{ color: #888; font-size: 0.85rem; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: #fff; border: 1px solid #e0dcd5; border-radius: 8px; padding: 14px; }}
  .card .label {{ font-size: 0.7rem; color: #888; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; margin-bottom: 4px; }}
  .card .value {{ font-size: 1.3rem; font-weight: 700; }}
  .status {{ display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; background: #2a9d8f22; color: #2a9d8f; }}
  .section {{ font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #2a9d8f; border-bottom: 2px solid #2a9d8f; padding-bottom: 6px; margin: 20px 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; }}
  th {{ text-align: left; font-size: 0.7rem; color: #888; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; padding: 6px 8px; border-bottom: 1px solid #e0dcd5; }}
  td {{ padding: 8px; border-bottom: 1px solid #f0ede8; }}
  .link {{ color: #2a9d8f; text-decoration: none; font-weight: 600; }}
  .link:hover {{ text-decoration: underline; }}
  .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #e0dcd5; font-size: 0.75rem; color: #aaa; }}
  .pipeline-tracker {{ background: #fff; border: 1px solid #e0dcd5; border-radius: 8px; padding: 16px; margin-bottom: 24px; }}
  .pipeline-tracker h3 {{ font-size: 0.8rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; color: #0d7377; margin-bottom: 12px; }}
  .step-row {{ display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 0.82rem; }}
  .step-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .step-dot.done {{ background: #2a9d8f; }}
  .step-dot.active {{ background: #d4a019; animation: pulse 1.2s infinite; }}
  .step-dot.pending {{ background: #e0dcd5; }}
  .step-dot.failed {{ background: #e63946; }}
  .step-name {{ font-weight: 600; min-width: 110px; }}
  .step-time {{ color: #888; font-size: 0.75rem; }}
  .step-status {{ color: #888; font-size: 0.75rem; }}
  .trigger-btn {{ background: #0d7377; color: #fff; border: none; padding: 8px 18px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; cursor: pointer; margin-top: 10px; }}
  .trigger-btn:hover {{ background: #0a5c5f; }}
  .trigger-btn:disabled {{ background: #ccc; cursor: not-allowed; }}
  @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
</style>
</head>
<body>
  <h1>Market Intelligence Agent <span class="status">Running</span></h1>
  <p class="subtitle">AI-powered market timing for Tamil Nadu smallholder farmers</p>

  <div class="pipeline-tracker" id="tracker">
    <h3>Pipeline</h3>
    <div id="steps-container">Loading...</div>
    <button class="trigger-btn" id="trigger-btn" onclick="triggerPipeline()">Run Pipeline</button>
  </div>

  <script>
  const STEPS = ['ingest', 'extract', 'reconcile', 'forecast', 'optimize', 'recommend'];
  const LABELS = {{
    ingest: 'Price Collection', extract: 'Price Extraction', reconcile: 'Conflict Reconciliation',
    forecast: 'Price Forecasting', optimize: 'Sell Optimization', recommend: 'Farmer Recommendation'
  }};

  function renderSteps(data) {{
    const completed = (data.completed_steps || []).map(s => s.step);
    const current = data.current_step;
    const running = data.running;
    let html = '';

    for (const step of STEPS) {{
      const done = completed.includes(step);
      const active = current === step;
      const cls = done ? 'done' : active ? 'active' : 'pending';
      const info = (data.completed_steps || []).find(s => s.step === step);
      const time = info ? info.duration_s + 's' : active ? 'running...' : '';
      const statusText = done ? info?.status || 'ok' : active ? 'running' : '';
      html += '<div class="step-row">'
        + '<div class="step-dot ' + cls + '"></div>'
        + '<span class="step-name">' + (LABELS[step] || step) + '</span>'
        + '<span class="step-time">' + time + '</span>'
        + '<span class="step-status">' + statusText + '</span>'
        + '</div>';
    }}

    if (!running && data.last_status) {{
      html += '<div style="margin-top:8px;font-size:0.75rem;color:#888;">Last run: '
        + (data.last_run_at || 'never') + ' — ' + (data.last_status || '') + '</div>';
    }}

    document.getElementById('steps-container').innerHTML = html;
    document.getElementById('trigger-btn').disabled = running;
    document.getElementById('trigger-btn').textContent = running ? 'Running...' : 'Run Pipeline';
  }}

  async function fetchStatus() {{
    try {{
      const r = await fetch('/api/pipeline/status');
      const data = await r.json();
      renderSteps(data);
      if (data.running) setTimeout(fetchStatus, 3000);
      else setTimeout(fetchStatus, 15000);
    }} catch(e) {{ setTimeout(fetchStatus, 5000); }}
  }}

  async function triggerPipeline() {{
    document.getElementById('trigger-btn').disabled = true;
    await fetch('/api/pipeline/trigger', {{ method: 'POST' }});
    setTimeout(fetchStatus, 1000);
  }}

  fetchStatus();
  </script>

  <div class="grid">
    <div class="card"><div class="label">Mandis</div><div class="value">{n_mandis}</div></div>
    <div class="card"><div class="label">Commodities</div><div class="value">{n_commodities}</div></div>
    <div class="card"><div class="label">Price Conflicts</div><div class="value">{n_conflicts}</div></div>
    <div class="card"><div class="label">Reliability</div><div class="value">{round(success_rate * 100)}%</div></div>
  </div>

  <div class="section">Price Conflicts (Agmarknet vs eNAM)</div>
  <table>
    <thead><tr><th>Mandi</th><th>Commodity</th><th>Agmarknet</th><th>eNAM</th><th>Delta</th><th>Reconciled</th></tr></thead>
    <tbody>{conflict_rows}</tbody>
  </table>

  <div class="section">API Endpoints</div>
  <table>
    <thead><tr><th>Endpoint</th><th>Description</th></tr></thead>
    <tbody>
      <tr><td><code>/health</code></td><td>Service health check</td></tr>
      <tr><td><code>/api/mandis</code></td><td>All {n_mandis} Tamil Nadu mandis</td></tr>
      <tr><td><code>/api/market-prices</code></td><td>Reconciled prices by commodity x mandi</td></tr>
      <tr><td><code>/api/price-forecast</code></td><td>7/14/30d price predictions</td></tr>
      <tr><td><code>/api/sell-recommendations</code></td><td>Optimal sell options for sample farmers</td></tr>
      <tr><td><code>/api/price-conflicts</code></td><td>Agmarknet vs eNAM disagreements</td></tr>
      <tr><td><code>/api/raw-inputs</code></td><td>Raw data from all sources</td></tr>
      <tr><td><code>/api/extracted-data</code></td><td>Normalized price data</td></tr>
      <tr><td><code>/api/reconciled-data</code></td><td>Reconciled data with conflict resolution</td></tr>
      <tr><td><code>/api/model-info</code></td><td>XGBoost model metrics</td></tr>
      <tr><td><code>/api/pipeline/runs</code></td><td>Pipeline run history</td></tr>
      <tr><td><code>/api/pipeline/stats</code></td><td>Aggregate statistics</td></tr>
    </tbody>
  </table>

  <div class="footer">Post-harvest market intelligence for Tamil Nadu | Agmarknet + eNAM + NASA POWER</div>
</body>
</html>"""


# ── Static file serving ──────────────────────────────────────────────────

dist_path = Path(__file__).parent.parent / "frontend" / "dist"
if dist_path.exists():
    app.mount("/assets", StaticFiles(directory=str(dist_path / "assets")), name="static")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        if path.startswith("api/") or path == "health":
            return JSONResponse({"detail": "Not found"}, status_code=404)
        file_path = dist_path / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(dist_path / "index.html"))
