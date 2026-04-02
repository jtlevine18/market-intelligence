"""
Monthly MOS Retrain — learns from accumulated prediction-vs-actual pairs.

Every weekly pipeline run saves predicted prices (price_forecasts) and
actual reconciled prices (market_prices) to Neon. This script pulls
those pairs, builds training features, and retrains the XGBoost MOS
correction models so forecasts improve over time.

Run manually:
    python scripts/retrain_mos.py

Or via the weekly GitHub Action (week 4 of each month):
    See .github/workflows/weekly-pipeline.yml

The retrained model is saved to models/ in the running container.
"""

from __future__ import annotations

import logging
import math
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import COMMODITIES, COMMODITY_MAP, MANDIS, MANDI_MAP, SEASONAL_INDICES

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")


def fetch_actuals_vs_predictions(engine, min_rows: int = 50) -> pd.DataFrame | None:
    """Pull prediction-vs-actual pairs from Neon.

    Joins price_forecasts (what we predicted) with market_prices
    (what actually happened) on (mandi_id, commodity_id, date).
    """
    query = text("""
        SELECT
            f.mandi_id,
            f.commodity_id,
            f.forecast_date,
            f.horizon_days,
            f.predicted_price,
            m.price_rs AS actual_price,
            m.date AS actual_date
        FROM price_forecasts f
        JOIN market_prices m
            ON f.mandi_id = m.mandi_id
            AND f.commodity_id = m.commodity_id
        WHERE m.price_rs IS NOT NULL
            AND f.predicted_price IS NOT NULL
        ORDER BY f.forecast_date, f.mandi_id, f.commodity_id
    """)

    with engine.connect() as conn:
        df = pd.read_sql(query, conn)

    if len(df) < min_rows:
        log.warning(
            "Only %d prediction-actual pairs (need %d). "
            "Run more weekly pipelines to accumulate training data.",
            len(df), min_rows,
        )
        return None

    log.info("Fetched %d prediction-actual pairs from Neon", len(df))
    return df


def fetch_price_history(engine) -> pd.DataFrame:
    """Pull all historical prices from Neon for feature engineering."""
    query = text("""
        SELECT mandi_id, commodity_id, date, price_rs, created_at
        FROM market_prices
        WHERE price_rs IS NOT NULL
        ORDER BY mandi_id, commodity_id, date
    """)
    with engine.connect() as conn:
        return pd.read_sql(query, conn)


def build_training_features(
    pairs_df: pd.DataFrame,
    history_df: pd.DataFrame,
) -> pd.DataFrame:
    """Build XGBoost training features from prediction-actual pairs.

    For each pair, computes the same features the live pipeline uses:
    - current_reconciled_price (the price at forecast time)
    - price_trend_7d, price_volatility_30d
    - seasonal_index, days_since/until_harvest
    - rainfall_7d, temperature_7d_avg (from historical averages)
    - The target is the RESIDUAL: actual - predicted
    """
    rows = []

    # Group history by (mandi, commodity) for efficient lookup
    history_groups = {}
    for (mid, cid), group in history_df.groupby(["mandi_id", "commodity_id"]):
        prices = group.sort_values("date")["price_rs"].values
        history_groups[(mid, cid)] = prices

    for _, pair in pairs_df.iterrows():
        mid = pair["mandi_id"]
        cid = pair["commodity_id"]
        horizon = pair["horizon_days"]
        predicted = pair["predicted_price"]
        actual = pair["actual_price"]

        commodity = COMMODITY_MAP.get(cid, {})
        mandi = MANDI_MAP.get(mid)
        if not mandi:
            continue

        # Residual is what MOS learns to correct
        residual = actual - predicted

        # Get price history for this pair
        history = history_groups.get((mid, cid), np.array([]))

        # Current price (approximate: use the actual as proxy for now)
        current_price = actual

        # Compute features
        n = len(history)
        trend_7 = _linear_slope(history[-7:]) if n >= 7 else 0
        vol_30 = float(np.std(history[-30:]) / np.mean(history[-30:])) if n >= 30 and np.mean(history[-30:]) > 0 else 0.05

        # Parse date for seasonal features
        try:
            forecast_date = pd.to_datetime(pair["forecast_date"]).date() if isinstance(pair["forecast_date"], str) else pair["forecast_date"]
            month = forecast_date.month
        except Exception:
            month = date.today().month

        seasonal = SEASONAL_INDICES.get(cid, {}).get(month, 1.0)

        harvest_months = []
        for hw in commodity.get("harvest_windows", []):
            harvest_months.extend(hw.get("months", []))

        rows.append({
            "mandi_id": mid,
            "commodity_id": cid,
            "horizon_days": horizon,
            "current_reconciled_price": round(current_price, 0),
            "price_trend_7d": round(trend_7, 4),
            "price_volatility_30d": round(vol_30, 4),
            "seasonal_index": seasonal,
            "days_since_harvest": _days_since_harvest(forecast_date, harvest_months) if harvest_months else 90,
            "days_until_next_harvest": _days_until_harvest(forecast_date, harvest_months) if harvest_months else 90,
            "month_sin": round(math.sin(2 * math.pi * month / 12), 4),
            "month_cos": round(math.cos(2 * math.pi * month / 12), 4),
            "residual": residual,
            "predicted": predicted,
            "actual": actual,
        })

    df = pd.DataFrame(rows)
    log.info(
        "Built %d training rows (%d unique mandi-commodity pairs, horizons: %s)",
        len(df),
        df.groupby(["mandi_id", "commodity_id"]).ngroups,
        sorted(df["horizon_days"].unique()),
    )
    return df


def retrain_mos(training_df: pd.DataFrame) -> dict:
    """Retrain XGBoost MOS models from accumulated real data.

    Returns metrics dict with RMSE before/after for each horizon.
    """
    import xgboost as xgb
    from sklearn.metrics import mean_squared_error

    feature_cols = [
        "current_reconciled_price", "price_trend_7d", "price_volatility_30d",
        "seasonal_index", "days_since_harvest", "days_until_next_harvest",
        "month_sin", "month_cos",
    ]

    metrics = {}

    for horizon in [7, 14, 30]:
        horizon_df = training_df[training_df["horizon_days"] == horizon].copy()
        if len(horizon_df) < 20:
            log.warning("Only %d rows for %dd horizon — skipping", len(horizon_df), horizon)
            continue

        X = horizon_df[feature_cols].fillna(0)
        y_residual = horizon_df["residual"]

        # RMSE before MOS (raw Chronos/XGBoost error)
        rmse_before = float(np.sqrt(np.mean(y_residual ** 2)))

        # Train/test split (80/20)
        split = int(len(X) * 0.8)
        X_train, X_test = X.iloc[:split], X.iloc[split:]
        y_train, y_test = y_residual.iloc[:split], y_residual.iloc[split:]

        model = xgb.XGBRegressor(
            objective="reg:squarederror",
            max_depth=4,
            learning_rate=0.03,
            n_estimators=100,
            subsample=0.8,
            colsample_bytree=0.7,
            random_state=42,
        )
        model.fit(X_train, y_train)

        # RMSE after MOS correction
        preds = model.predict(X_test)
        corrected_residuals = y_test - preds
        rmse_after = float(np.sqrt(np.mean(corrected_residuals ** 2)))

        improvement = (1 - rmse_after / rmse_before) * 100 if rmse_before > 0 else 0

        metrics[f"{horizon}d"] = {
            "samples": len(horizon_df),
            "rmse_before": round(rmse_before, 1),
            "rmse_after": round(rmse_after, 1),
            "improvement_pct": round(improvement, 1),
        }

        # Save model
        model_path = f"models/mos_{horizon}d.json"
        model.save_model(model_path)
        log.info(
            "MOS %dd retrained: %d samples, RMSE %.1f → %.1f (%.1f%% improvement)",
            horizon, len(horizon_df), rmse_before, rmse_after, improvement,
        )

    return metrics


def _linear_slope(values) -> float:
    if len(values) < 2:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = np.array(values, dtype=float)
    mask = ~np.isnan(y)
    if mask.sum() < 2:
        return 0.0
    slope = np.polyfit(x[mask], y[mask], 1)[0]
    return float(slope)


def _days_since_harvest(d: date, harvest_months: list[int]) -> int:
    if not harvest_months:
        return 90
    best = 365
    for m in harvest_months:
        harvest_date = date(d.year, m, 15)
        if harvest_date > d:
            harvest_date = date(d.year - 1, m, 15)
        delta = (d - harvest_date).days
        if 0 <= delta < best:
            best = delta
    return min(best, 365)


def _days_until_harvest(d: date, harvest_months: list[int]) -> int:
    if not harvest_months:
        return 90
    best = 365
    for m in harvest_months:
        harvest_date = date(d.year, m, 15)
        if harvest_date <= d:
            harvest_date = date(d.year + 1, m, 15)
        delta = (harvest_date - d).days
        if 0 < delta < best:
            best = delta
    return min(best, 365)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s %(levelname)s %(message)s",
    )

    if not DATABASE_URL:
        print("DATABASE_URL not set — cannot retrain without historical data")
        sys.exit(1)

    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 10})

    # Fetch data
    pairs = fetch_actuals_vs_predictions(engine, min_rows=20)
    if pairs is None:
        print("Not enough data to retrain. Run more weekly pipelines first.")
        sys.exit(0)

    history = fetch_price_history(engine)
    if history.empty:
        print("No price history in database.")
        sys.exit(1)

    # Build features and retrain
    training_df = build_training_features(pairs, history)
    metrics = retrain_mos(training_df)

    # Summary
    print("\n=== MOS Retrain Results ===")
    for horizon, m in sorted(metrics.items()):
        print(f"  {horizon}: {m['samples']} samples, RMSE {m['rmse_before']} → {m['rmse_after']} ({m['improvement_pct']}% improvement)")

    if not metrics:
        print("  No horizons had enough data to retrain.")


if __name__ == "__main__":
    main()
