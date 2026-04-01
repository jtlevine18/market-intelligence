"""
NASA POWER daily data fetcher for Tamil Nadu mandi locations.

Fetches PRECTOTCORR, T2M, T2M_MAX, T2M_MIN, RH2M from the NASA POWER
daily point API for each mandi's lat/lon. Handles rate limiting,
retries, and parallel mandi fetching via httpx.

NASA POWER data has a 2-3 day processing lag. The API returns -999
for missing values, which we filter out.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx

from config import NASA_POWER_PARAMS, NASA_POWER_URL, Mandi

log = logging.getLogger(__name__)

NASA_MISSING = -999.0

_MAX_CONCURRENT = 4
_INTER_REQUEST_DELAY = 0.6
_TIMEOUT = httpx.Timeout(45.0)
_MAX_RETRIES = 3


@dataclass
class DailyReading:
    mandi_id: str
    date: str
    precip_mm: float | None
    temp_mean_c: float | None
    temp_max_c: float | None
    temp_min_c: float | None
    humidity_pct: float | None
    source: str = "nasa_power"
    data_quality: float = 1.0


def _safe_val(val: Any) -> float | None:
    """Return None for NASA's -999 missing sentinel or actual None."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if f == NASA_MISSING else round(f, 2)
    except (ValueError, TypeError):
        return None


def _default_date_range(days_back: int = 90) -> tuple[date, date]:
    """Return (start, end) defaulting to last 90 days.

    Ends 2 days ago to account for NASA POWER processing lag.
    """
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days_back - 1)
    return start, end


async def fetch_mandi_nasa_power(
    mandi: Mandi,
    start_date: date | None = None,
    end_date: date | None = None,
    client: httpx.AsyncClient | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> list[DailyReading]:
    """Fetch NASA POWER daily data for a single mandi.

    Parameters
    ----------
    mandi : Mandi
        Mandi definition with lat/lon.
    start_date, end_date : date, optional
        Date range. Defaults to last 90 days (ending 2 days ago).
    client : httpx.AsyncClient, optional
        Shared client for connection pooling across mandis.
    semaphore : asyncio.Semaphore, optional
        Concurrency limiter shared across parallel fetches.

    Returns
    -------
    list[DailyReading]
        One reading per day with NASA POWER fields populated.
    """
    if start_date is None or end_date is None:
        start_date, end_date = _default_date_range()

    sem = semaphore or asyncio.Semaphore(_MAX_CONCURRENT)
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=_TIMEOUT)

    try:
        async with sem:
            await asyncio.sleep(_INTER_REQUEST_DELAY)
            return await _fetch_with_retry(mandi, start_date, end_date, client)
    finally:
        if owns_client:
            await client.aclose()


async def _fetch_with_retry(
    mandi: Mandi,
    start_date: date,
    end_date: date,
    client: httpx.AsyncClient,
) -> list[DailyReading]:
    """Fetch with exponential backoff on 429 / transient errors."""
    params = {
        "parameters": ",".join(NASA_POWER_PARAMS),
        "community": "AG",
        "longitude": mandi.longitude,
        "latitude": mandi.latitude,
        "start": start_date.strftime("%Y%m%d"),
        "end": end_date.strftime("%Y%m%d"),
        "format": "JSON",
    }

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.get(NASA_POWER_URL, params=params)

            if resp.status_code == 429:
                wait = 10 * (attempt + 1)
                log.warning(
                    "NASA POWER 429 for mandi %s (attempt %d/%d), backing off %ds",
                    mandi.mandi_id, attempt + 1, _MAX_RETRIES, wait,
                )
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            data = resp.json()
            return _parse_response(mandi.mandi_id, data)

        except httpx.TimeoutException as exc:
            last_exc = exc
            wait = 5.0 * (attempt + 1)
            log.warning(
                "NASA POWER timeout for mandi %s (attempt %d/%d), retrying in %.0fs",
                mandi.mandi_id, attempt + 1, _MAX_RETRIES, wait,
            )
            await asyncio.sleep(wait)

        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code >= 500:
                wait = 5.0 * (attempt + 1)
                log.warning(
                    "NASA POWER %d for mandi %s (attempt %d/%d), retrying in %.0fs",
                    exc.response.status_code, mandi.mandi_id,
                    attempt + 1, _MAX_RETRIES, wait,
                )
                await asyncio.sleep(wait)
            else:
                log.error(
                    "NASA POWER %d for mandi %s: %s",
                    exc.response.status_code, mandi.mandi_id,
                    exc.response.text[:200],
                )
                return []

        except Exception as exc:
            last_exc = exc
            log.warning(
                "NASA POWER unexpected error for mandi %s (attempt %d/%d): %s",
                mandi.mandi_id, attempt + 1, _MAX_RETRIES, exc,
            )
            await asyncio.sleep(3.0)

    log.error(
        "NASA POWER failed for mandi %s after %d attempts: %s",
        mandi.mandi_id, _MAX_RETRIES, last_exc,
    )
    return []


def _parse_response(mandi_id: str, data: dict) -> list[DailyReading]:
    """Parse NASA POWER JSON response into DailyReading objects."""
    try:
        props = data["properties"]["parameter"]
    except (KeyError, TypeError):
        log.error("NASA POWER unexpected response structure for mandi %s", mandi_id)
        return []

    prec_data = props.get("PRECTOTCORR", {})
    t2m_data = props.get("T2M", {})
    t2m_max_data = props.get("T2M_MAX", {})
    t2m_min_data = props.get("T2M_MIN", {})
    rh2m_data = props.get("RH2M", {})

    all_days = sorted(t2m_data.keys())
    readings: list[DailyReading] = []

    for day_str in all_days:
        try:
            formatted_date = f"{day_str[:4]}-{day_str[4:6]}-{day_str[6:8]}"
        except (IndexError, TypeError):
            continue

        precip = _safe_val(prec_data.get(day_str))
        temp_mean = _safe_val(t2m_data.get(day_str))
        temp_max = _safe_val(t2m_max_data.get(day_str))
        temp_min = _safe_val(t2m_min_data.get(day_str))
        humidity = _safe_val(rh2m_data.get(day_str))

        fields = [precip, temp_mean, temp_max, temp_min, humidity]
        present = sum(1 for f in fields if f is not None)
        quality = present / len(fields)

        readings.append(
            DailyReading(
                mandi_id=mandi_id,
                date=formatted_date,
                precip_mm=precip,
                temp_mean_c=temp_mean,
                temp_max_c=temp_max,
                temp_min_c=temp_min,
                humidity_pct=humidity,
                source="nasa_power",
                data_quality=quality,
            )
        )

    log.info(
        "NASA POWER: mandi %s -- %d days fetched, %.0f%% avg completeness",
        mandi_id, len(readings),
        (sum(r.data_quality for r in readings) / len(readings) * 100)
        if readings else 0,
    )
    return readings


async def fetch_all_mandis_nasa_power(
    mandis: list[Mandi],
    start_date: date | None = None,
    end_date: date | None = None,
    days_back: int = 90,
) -> dict[str, list[DailyReading]]:
    """Fetch NASA POWER data for all mandis in parallel.

    Returns a dict mapping mandi_id -> list of DailyReading.
    """
    if start_date is None or end_date is None:
        start_date, end_date = _default_date_range(days_back)

    sem = asyncio.Semaphore(_MAX_CONCURRENT)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        tasks = [
            fetch_mandi_nasa_power(
                m, start_date, end_date,
                client=client, semaphore=sem,
            )
            for m in mandis
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    output: dict[str, list[DailyReading]] = {}
    for m, result in zip(mandis, results):
        if isinstance(result, Exception):
            log.error("NASA POWER failed for mandi %s: %s", m.mandi_id, result)
            output[m.mandi_id] = []
        else:
            output[m.mandi_id] = result

    total_readings = sum(len(v) for v in output.values())
    mandis_with_data = sum(1 for v in output.values() if v)
    log.info(
        "NASA POWER batch complete: %d/%d mandis with data, %d total readings",
        mandis_with_data, len(mandis), total_readings,
    )
    return output
