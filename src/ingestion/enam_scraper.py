"""
eNAM price scraper -- fetches live trading prices from eNAM dashboards.

Secondary data source that often reports DIFFERENT prices than Agmarknet
for the same mandi/commodity/date. This conflict is the reconciliation
challenge the tool solves.

In production this would scrape eNAM's web dashboard via BeautifulSoup.
For demo mode it generates realistic conflicting prices.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from config import (
    BASE_PRICES_RS,
    COMMODITIES,
    MANDI_MAP,
    MANDIS,
    SEASONAL_INDICES,
    Mandi,
)
from src.ingestion.agmarknet import PriceRecord

log = logging.getLogger(__name__)


async def fetch_enam_prices(
    mandis: list[Mandi] | None = None,
    commodities: list[dict] | None = None,
    days_back: int = 14,
) -> dict[str, list[PriceRecord]]:
    """Fetch eNAM trading prices for mandis that are eNAM-integrated.

    In production, this would scrape the eNAM dashboard. For demo mode,
    it generates prices that deliberately diverge from Agmarknet by 3-12%
    (sometimes more for poorly-reporting mandis).

    Introduces realistic data quality issues:
    - Stale data (same price repeated for 3+ consecutive days)
    - Missing entries for some days
    - Occasional price spikes (data entry errors)

    Parameters
    ----------
    mandis : list[Mandi], optional
        Mandis to query. Only eNAM-integrated mandis will have data.
    commodities : list[dict], optional
        Commodities to query.
    days_back : int
        Days of data to fetch (eNAM typically has less history than Agmarknet).

    Returns
    -------
    dict[str, list[PriceRecord]]
        Price records grouped by mandi_id, source="enam".
    """
    if mandis is None:
        mandis = MANDIS
    if commodities is None:
        commodities = COMMODITIES

    # Only eNAM-integrated mandis have data
    enam_mandis = [m for m in mandis if m.enam_integrated]

    if not enam_mandis:
        return {}

    log.info("eNAM scraper: generating demo prices for %d integrated mandis", len(enam_mandis))
    return _generate_enam_prices(enam_mandis, commodities, days_back, seed=42)


def _generate_enam_prices(
    mandis: list[Mandi],
    commodities: list[dict],
    days_back: int,
    seed: int = 42,
) -> dict[str, list[PriceRecord]]:
    """Generate eNAM prices that intentionally conflict with Agmarknet.

    The divergence pattern varies by mandi reporting quality:
    - good: 3-6% divergence (rounding, timing differences)
    - moderate: 5-10% divergence (delayed reporting, aggregation differences)
    - poor: 8-15% divergence (stale data, data entry errors)
    """
    rng = random.Random(seed + 7)  # different seed from Agmarknet
    end_date = date.today()
    results: dict[str, list[PriceRecord]] = {m.mandi_id: [] for m in mandis}

    for mandi in mandis:
        # Divergence range based on reporting quality
        if mandi.reporting_quality == "good":
            divergence_range = (0.03, 0.06)
        elif mandi.reporting_quality == "moderate":
            divergence_range = (0.05, 0.10)
        else:
            divergence_range = (0.08, 0.15)

        for commodity in commodities:
            if commodity["id"] not in mandi.commodities_traded:
                continue

            base_price = BASE_PRICES_RS.get(commodity["id"], 2000)

            # eNAM tends to report slightly higher (last traded price vs modal)
            enam_bias = rng.uniform(0.01, 0.04)

            # Stale data simulation: pick some days where price stays the same
            stale_price = None
            stale_counter = 0
            stale_trigger = rng.randint(4, 8)  # how many days before staleness

            for day_offset in range(days_back):
                current_date = end_date - timedelta(days=day_offset)

                # Skip weekends
                if current_date.weekday() >= 6:
                    continue

                # Missing entries: eNAM has gaps (~15% of days missing)
                if rng.random() < 0.15:
                    continue

                month = current_date.month
                seasonal = SEASONAL_INDICES.get(commodity["id"], {}).get(month, 1.0)

                # Base eNAM price diverges from Agmarknet
                divergence = rng.uniform(*divergence_range)
                divergence_sign = 1 if rng.random() > 0.4 else -1
                divergence_factor = 1.0 + (divergence * divergence_sign) + enam_bias

                daily_noise = rng.gauss(0, 0.012)
                trend = 1.0 + (days_back - day_offset) * 0.0002

                # Stale data simulation
                stale_counter += 1
                if stale_counter >= stale_trigger and stale_price is not None:
                    # Copy previous price for 3-5 days (stale reporting)
                    if stale_counter < stale_trigger + rng.randint(3, 5):
                        modal_price = stale_price
                        quality_flag = "stale"
                    else:
                        stale_counter = 0
                        stale_trigger = rng.randint(5, 10)
                        modal_price = base_price * seasonal * divergence_factor * trend * (1 + daily_noise)
                        modal_price = round(modal_price, 0)
                        stale_price = modal_price
                        quality_flag = "good"
                else:
                    modal_price = base_price * seasonal * divergence_factor * trend * (1 + daily_noise)
                    modal_price = round(modal_price, 0)
                    stale_price = modal_price
                    quality_flag = "good"

                # Occasional spike (data entry error, ~2% of entries)
                if rng.random() < 0.02:
                    modal_price = round(modal_price * rng.uniform(1.3, 1.8), 0)
                    quality_flag = "anomalous"

                # eNAM reports last traded price, not min/max in same way
                spread_pct = rng.uniform(0.03, 0.08)
                min_price = round(modal_price * (1 - spread_pct), 0)
                max_price = round(modal_price * (1 + spread_pct * 0.6), 0)

                # eNAM arrivals tend to be lower (only electronic trading portion)
                arrivals = mandi.avg_daily_arrivals_tonnes * rng.uniform(0.1, 0.4)

                results[mandi.mandi_id].append(PriceRecord(
                    mandi_id=mandi.mandi_id,
                    commodity_id=commodity["id"],
                    date=current_date.strftime("%Y-%m-%d"),
                    min_price_rs=min_price,
                    max_price_rs=max_price,
                    modal_price_rs=modal_price,
                    arrivals_tonnes=round(arrivals, 1),
                    source="enam",
                    freshness_hours=12.0 + day_offset * 24,  # eNAM is slightly more current
                    quality_flag=quality_flag,
                ))

    total = sum(len(v) for v in results.values())
    log.info("eNAM demo: generated %d price records across %d mandis", total, len(mandis))
    return results
