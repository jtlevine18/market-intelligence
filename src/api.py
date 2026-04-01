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
from fastapi.responses import FileResponse, HTMLResponse

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
                "mandi_fee_rs": round(mandi_fee, 0),
                "net_price_rs": round(net_now, 0),
                "distance_km": round(dist, 1),
                "confidence": 0.85,
                "price_source": "current",
            })

            fc = forecast_by_mandi.get(m.mandi_id, {}).get(farmer.primary_commodity, {})
            p7 = fc.get("price_7d", 0)
            if p7 > 0:
                loss_pct = POST_HARVEST_LOSS.get(farmer.primary_commodity, {}).get("storage_per_month", 2.5)
                storage_loss = p7 * (loss_pct / 100) * (7 / 30)
                net_7d = p7 - transport - p7 * MANDI_FEE_PCT / 100 - storage_loss
                options.append({
                    "mandi_id": m.mandi_id,
                    "mandi_name": m.name,
                    "sell_timing": "7d",
                    "market_price_rs": p7,
                    "transport_cost_rs": round(transport, 0),
                    "storage_loss_rs": round(storage_loss, 0),
                    "mandi_fee_rs": round(p7 * MANDI_FEE_PCT / 100, 0),
                    "net_price_rs": round(net_7d, 0),
                    "distance_km": round(dist, 1),
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
        "metrics": {
            "rmse": 87.4,
            "mae": 62.1,
            "r_squared": 0.89,
            "train_samples": 4200,
            "features": 15,
        },
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
            "metrics": model_metrics.get("metrics", {}),
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
</style>
</head>
<body>
  <h1>Market Intelligence Agent <span class="status">Running</span></h1>
  <p class="subtitle">AI-powered market timing for Tamil Nadu smallholder farmers</p>

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
            return None
        file_path = dist_path / path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(dist_path / "index.html"))
