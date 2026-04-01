"""
Agmarknet API client -- fetches daily wholesale prices from data.gov.in.

Primary data source for Tamil Nadu mandi prices. Returns structured
price records normalized to per-quintal basis.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from config import (
    AGMARKNET_API_URL,
    BASE_PRICES_RS,
    COMMODITY_MAP,
    COMMODITIES,
    MANDI_MAP,
    MANDIS,
    SEASONAL_INDICES,
    Mandi,
)

log = logging.getLogger(__name__)

_RATE_LIMIT = asyncio.Semaphore(10)  # max 10 requests/sec to data.gov.in
_TIMEOUT = httpx.Timeout(30.0)


@dataclass
class PriceRecord:
    """Single price observation from a data source."""
    mandi_id: str
    commodity_id: str
    date: str  # YYYY-MM-DD
    min_price_rs: float
    max_price_rs: float
    modal_price_rs: float
    arrivals_tonnes: float
    source: str  # "agmarknet" or "enam"
    freshness_hours: float
    quality_flag: str  # "good", "stale", "anomalous", "missing"


async def fetch_mandi_prices(
    mandis: list[Mandi] | None = None,
    commodities: list[dict] | None = None,
    days_back: int = 30,
    api_key: str | None = None,
) -> dict[str, list[PriceRecord]]:
    """Fetch daily wholesale prices from the Agmarknet API.

    Parameters
    ----------
    mandis : list[Mandi], optional
        Mandis to query. Defaults to all Tamil Nadu mandis.
    commodities : list[dict], optional
        Commodities to query. Defaults to all 10 Tamil Nadu crops.
    days_back : int
        Number of days of historical data.
    api_key : str, optional
        data.gov.in API key. Falls back to env var, then demo mode.

    Returns
    -------
    dict[str, list[PriceRecord]]
        Price records grouped by mandi_id.
    """
    if mandis is None:
        mandis = MANDIS
    if commodities is None:
        commodities = COMMODITIES

    # data.gov.in provides a default public API key for testing
    _DEFAULT_KEY = "579b464db66ec23bdd000001cdd3946e44ce4aad7209ff7b23ac571b"
    api_key = api_key or os.environ.get("DATA_GOV_IN_API_KEY", _DEFAULT_KEY)

    if api_key and os.environ.get("MARKET_INTEL_USE_REAL_API", "").lower() in ("1", "true", "yes"):
        return await _fetch_real_prices(mandis, commodities, days_back, api_key)

    log.info("Real API disabled (set MARKET_INTEL_USE_REAL_API=1 to enable) -- generating demo prices")
    return _generate_demo_prices(mandis, commodities, days_back, seed=42)


async def _fetch_real_prices(
    mandis: list[Mandi],
    commodities: list[dict],
    days_back: int,
    api_key: str,
) -> dict[str, list[PriceRecord]]:
    """Fetch from real Agmarknet API on data.gov.in."""
    end_date = date.today()
    start_date = end_date - timedelta(days=days_back)

    results: dict[str, list[PriceRecord]] = {m.mandi_id: [] for m in mandis}

    # Collect unique districts from our mandi list for targeted queries
    districts = sorted(set(m.district for m in mandis))

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        for commodity in commodities:
            names_to_try = [commodity["agmarknet_name"]] + commodity.get("agmarknet_aliases", [])

            for commodity_name in names_to_try:
                async with _RATE_LIMIT:
                    try:
                        # Note: data.gov.in Agmarknet API returns current prices only.
                        # Date filters (from_date/to_date) are not supported on this resource.
                        params = {
                            "api-key": api_key,
                            "format": "json",
                            "filters[state]": "Tamil Nadu",
                            "filters[commodity]": commodity_name,
                            "limit": 500,
                        }
                        resp = await client.get(AGMARKNET_API_URL, params=params)
                        resp.raise_for_status()
                        data = resp.json()

                        for rec in data.get("records", []):
                            mandi_match = _match_mandi_by_district(rec.get("district", ""), rec.get("market", ""), mandis)
                            if mandi_match is None:
                                continue

                            price_date = _parse_date(rec.get("arrival_date", ""))
                            if price_date is None:
                                continue

                            results[mandi_match.mandi_id].append(PriceRecord(
                                mandi_id=mandi_match.mandi_id,
                                commodity_id=commodity["id"],
                                date=price_date,
                                min_price_rs=float(rec.get("min_price", 0)),
                                max_price_rs=float(rec.get("max_price", 0)),
                                modal_price_rs=float(rec.get("modal_price", 0)),
                                arrivals_tonnes=float(rec.get("arrivals_tonnes", 0)),
                                source="agmarknet",
                                freshness_hours=24.0,
                                quality_flag="good",
                            ))
                    except Exception as exc:
                        log.warning("Agmarknet API error for %s (%s): %s", commodity["id"], commodity_name, exc)
                        await asyncio.sleep(0.5)

    total = sum(len(v) for v in results.values())
    log.info("Agmarknet: fetched %d real price records across %d mandis", total, len(mandis))
    return results


def _match_mandi_by_district(district: str, market_name: str, mandis: list[Mandi]) -> Mandi | None:
    """Match an API record to our mandi list, primarily by district.

    The API's 'district' field matches our mandi districts exactly.
    Multiple API markets in one district all map to the same mandi.
    """
    district_lower = district.lower().strip()
    for m in mandis:
        if m.district.lower() == district_lower:
            return m
    # Fallback to market name matching
    return _match_mandi(market_name, mandis)


def _match_mandi(market_name: str, mandis: list[Mandi]) -> Mandi | None:
    """Fuzzy-match an Agmarknet market name to our mandi list.

    API returns names like "Singanallur(Uzhavar Sandhai) APMC" or "Tindivanam APMC".
    We match against mandi name and district, stripping common suffixes.
    """
    market_lower = market_name.lower().strip()
    # Strip common suffixes
    for suffix in [" apmc", "(uzhavar sandhai)", "(uzhavar sandhai )", " market"]:
        market_lower = market_lower.replace(suffix, "").strip()

    for m in mandis:
        mname = m.name.lower()
        mdistrict = m.district.lower()
        # Direct match
        if mname in market_lower or market_lower in mname:
            return m
        # District match (e.g., "Thanjavur" matches "Thanjavur")
        if mdistrict in market_lower or market_lower in mdistrict:
            return m
        # First word match (e.g., "Madurai" in "Madurai Periyar")
        first_word = mname.split()[0] if mname else ""
        if first_word and first_word in market_lower:
            return m
    return None


def _parse_date(date_str: str) -> str | None:
    """Parse date from Agmarknet format (DD/MM/YYYY or DD-MM-YYYY)."""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _generate_demo_prices(
    mandis: list[Mandi],
    commodities: list[dict],
    days_back: int,
    seed: int = 42,
) -> dict[str, list[PriceRecord]]:
    """Generate deterministic, realistic demo price data.

    Creates coherent price series with:
    - Seasonal patterns from SEASONAL_INDICES
    - Mandi-level variation (production-area mandis cheaper)
    - Realistic spreads between min/max/modal
    - Arrival volumes correlated with season
    """
    rng = random.Random(seed)
    end_date = date.today()
    results: dict[str, list[PriceRecord]] = {m.mandi_id: [] for m in mandis}

    for mandi in mandis:
        for commodity in commodities:
            if commodity["id"] not in mandi.commodities_traded:
                continue

            base_price = BASE_PRICES_RS.get(commodity["id"], 2000)

            # Mandi-level adjustment: production hubs are 3-8% cheaper
            mandi_factor = 1.0
            if mandi.market_type == "terminal":
                mandi_factor = 1.02 + rng.uniform(0, 0.03)
            elif mandi.market_type == "wholesale":
                mandi_factor = 1.00 + rng.uniform(0, 0.05)
            elif mandi.reporting_quality == "poor":
                mandi_factor = 0.97 + rng.uniform(-0.02, 0.03)
            else:
                mandi_factor = 0.98 + rng.uniform(-0.02, 0.04)

            # Generate daily prices
            for day_offset in range(days_back):
                current_date = end_date - timedelta(days=day_offset)

                # Skip weekends (mandis often closed)
                if current_date.weekday() >= 6:  # Sunday
                    continue

                month = current_date.month
                seasonal = SEASONAL_INDICES.get(commodity["id"], {}).get(month, 1.0)

                # Daily noise
                daily_noise = rng.gauss(0, 0.015)

                # Trend component (slight upward drift)
                trend = 1.0 + (days_back - day_offset) * 0.0002

                modal_price = base_price * seasonal * mandi_factor * trend * (1 + daily_noise)
                modal_price = round(modal_price, 0)

                spread_pct = rng.uniform(0.05, 0.12)
                min_price = round(modal_price * (1 - spread_pct), 0)
                max_price = round(modal_price * (1 + spread_pct * 0.8), 0)

                # Arrivals correlated with harvest season
                base_arrivals = mandi.avg_daily_arrivals_tonnes * 0.3
                harvest_months = []
                for hw in commodity.get("harvest_windows", []):
                    harvest_months.extend(hw.get("months", []))
                if month in harvest_months:
                    arrivals = base_arrivals * rng.uniform(1.5, 3.0)
                else:
                    arrivals = base_arrivals * rng.uniform(0.3, 0.8)

                results[mandi.mandi_id].append(PriceRecord(
                    mandi_id=mandi.mandi_id,
                    commodity_id=commodity["id"],
                    date=current_date.strftime("%Y-%m-%d"),
                    min_price_rs=min_price,
                    max_price_rs=max_price,
                    modal_price_rs=modal_price,
                    arrivals_tonnes=round(arrivals, 1),
                    source="agmarknet",
                    freshness_hours=24.0 + day_offset * 24,
                    quality_flag="good",
                ))

    total = sum(len(v) for v in results.values())
    log.info("Agmarknet demo: generated %d price records across %d mandis", total, len(mandis))
    return results
