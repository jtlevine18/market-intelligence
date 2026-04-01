"""
XGBoost price forecasting model for Tamil Nadu agricultural commodities.

Predicts prices at 7, 14, and 30-day horizons using ~15 features derived
from historical prices, seasonal patterns, weather, and market volumes.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from config import (
    BASE_PRICES_RS,
    COMMODITIES,
    COMMODITY_MAP,
    MANDIS,
    MANDI_MAP,
    SEASONAL_INDICES,
    Mandi,
)

log = logging.getLogger(__name__)

# Encoding maps for categorical features
MARKET_TYPE_ENC = {"regulated": 0, "wholesale": 1, "terminal": 2}
CATEGORY_ENC = {"cereal": 0, "oilseed": 1, "spice": 2, "cash_crop": 3, "fruit": 4, "vegetable": 5}


@dataclass
class PriceForecast:
    """Price forecast for a single commodity at a single mandi."""
    commodity_id: str
    mandi_id: str
    current_price: float
    price_7d: float
    price_14d: float
    price_30d: float
    ci_lower_7d: float
    ci_upper_7d: float
    ci_lower_14d: float
    ci_upper_14d: float
    ci_lower_30d: float
    ci_upper_30d: float
    direction: str  # "up", "flat", "down"
    confidence: float
    feature_importances: dict = field(default_factory=dict)


class XGBoostPriceModel:
    """XGBoost-based price forecasting model.

    Trains on historical mandi price data with ~15 features.
    Predicts at 7, 14, and 30-day horizons with quantile regression
    for prediction intervals.
    """

    FEATURES = [
        "current_reconciled_price",
        "price_trend_7d",
        "price_trend_14d",
        "price_trend_30d",
        "price_volatility_30d",
        "seasonal_index",
        "days_since_harvest",
        "days_until_next_harvest",
        "mandi_arrival_volume_7d_avg",
        "rainfall_7d",
        "temperature_7d_avg",
        "month_sin",
        "month_cos",
        "commodity_category_encoded",
        "mandi_market_type_encoded",
    ]

    def __init__(self):
        self._model_7d = None
        self._model_14d = None
        self._model_30d = None
        self._trained = False
        self.metrics: dict = {}
        self.feature_importances: dict = {}

    def is_trained(self) -> bool:
        return self._trained

    def train(self, training_data: pd.DataFrame):
        """Train XGBoost models for 7/14/30 day horizons."""
        try:
            import xgboost as xgb
        except ImportError:
            log.warning("xgboost not available -- using seasonal baseline only")
            return

        feature_cols = [c for c in self.FEATURES if c in training_data.columns]
        if not feature_cols:
            log.warning("No valid feature columns found in training data")
            return

        X = training_data[feature_cols].fillna(0)

        params = {
            "objective": "reg:squarederror",
            "max_depth": 6,
            "learning_rate": 0.05,
            "n_estimators": 200,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "random_state": 42,
        }

        for horizon, col in [("7d", "target_7d"), ("14d", "target_14d"), ("30d", "target_30d")]:
            if col not in training_data.columns:
                continue

            y = training_data[col].fillna(training_data["current_reconciled_price"])
            model = xgb.XGBRegressor(**params)
            model.fit(X, y)

            if horizon == "7d":
                self._model_7d = model
            elif horizon == "14d":
                self._model_14d = model
            else:
                self._model_30d = model

        if self._model_7d is not None:
            importances = dict(zip(feature_cols, self._model_7d.feature_importances_))
            self.feature_importances = {
                k: round(float(v), 4)
                for k, v in sorted(importances.items(), key=lambda x: -x[1])
            }

        # Compute metrics on training data
        if self._model_7d is not None and "target_7d" in training_data.columns:
            preds = self._model_7d.predict(X)
            actuals = training_data["target_7d"].fillna(training_data["current_reconciled_price"])
            residuals = actuals - preds
            self.metrics = {
                "rmse": round(float(np.sqrt(np.mean(residuals ** 2))), 1),
                "mae": round(float(np.mean(np.abs(residuals))), 1),
                "r2": round(float(1 - np.sum(residuals ** 2) / np.sum((actuals - actuals.mean()) ** 2)), 3),
                "train_samples": len(training_data),
                "features": len(feature_cols),
            }

        self._trained = True
        log.info("XGBoost price model trained: %s", self.metrics)

    def predict(self, features: pd.DataFrame) -> list[PriceForecast]:
        """Generate price forecasts for given features."""
        if not self._trained:
            return self._seasonal_baseline(features)

        feature_cols = [c for c in self.FEATURES if c in features.columns]
        X = features[feature_cols].fillna(0)

        forecasts = []
        for i, row in features.iterrows():
            current_price = row.get("current_reconciled_price", 0)
            commodity_id = row.get("commodity_id", "")
            mandi_id = row.get("mandi_id", "")

            # Predict median
            p7 = float(self._model_7d.predict(X.iloc[[i]])[0]) if self._model_7d else current_price
            p14 = float(self._model_14d.predict(X.iloc[[i]])[0]) if self._model_14d else current_price
            p30 = float(self._model_30d.predict(X.iloc[[i]])[0]) if self._model_30d else current_price

            # Confidence intervals (heuristic: wider for longer horizons)
            vol = row.get("price_volatility_30d", 0.05)
            ci_7 = current_price * vol * 0.5
            ci_14 = current_price * vol * 0.7
            ci_30 = current_price * vol * 1.0

            # Direction
            pct_change = (p7 - current_price) / current_price if current_price else 0
            direction = "up" if pct_change > 0.02 else "down" if pct_change < -0.02 else "flat"

            forecasts.append(PriceForecast(
                commodity_id=commodity_id,
                mandi_id=mandi_id,
                current_price=round(current_price, 0),
                price_7d=round(p7, 0),
                price_14d=round(p14, 0),
                price_30d=round(p30, 0),
                ci_lower_7d=round(p7 - ci_7, 0),
                ci_upper_7d=round(p7 + ci_7, 0),
                ci_lower_14d=round(p14 - ci_14, 0),
                ci_upper_14d=round(p14 + ci_14, 0),
                ci_lower_30d=round(p30 - ci_30, 0),
                ci_upper_30d=round(p30 + ci_30, 0),
                direction=direction,
                confidence=round(max(0.10, 0.85 - vol * 0.5), 2),
                feature_importances=self.feature_importances,
            ))

        return forecasts

    def _seasonal_baseline(self, features: pd.DataFrame) -> list[PriceForecast]:
        """Seasonal baseline model: current price * seasonal adjustment."""
        forecasts = []
        today = date.today()

        for i, row in features.iterrows():
            current_price = row.get("current_reconciled_price", 0)
            commodity_id = row.get("commodity_id", "")
            mandi_id = row.get("mandi_id", "")

            # Seasonal adjustments for future months
            seasonal_now = SEASONAL_INDICES.get(commodity_id, {}).get(today.month, 1.0)
            m7 = (today + timedelta(days=7)).month
            m14 = (today + timedelta(days=14)).month
            m30 = (today + timedelta(days=30)).month

            s7 = SEASONAL_INDICES.get(commodity_id, {}).get(m7, 1.0) / max(0.5, seasonal_now)
            s14 = SEASONAL_INDICES.get(commodity_id, {}).get(m14, 1.0) / max(0.5, seasonal_now)
            s30 = SEASONAL_INDICES.get(commodity_id, {}).get(m30, 1.0) / max(0.5, seasonal_now)

            p7 = current_price * s7
            p14 = current_price * s14
            p30 = current_price * s30

            vol = row.get("price_volatility_30d", 0.08)
            ci_7 = current_price * vol * 0.5
            ci_14 = current_price * vol * 0.7
            ci_30 = current_price * vol * 1.0

            pct_change = (p7 - current_price) / current_price if current_price else 0
            direction = "up" if pct_change > 0.02 else "down" if pct_change < -0.02 else "flat"

            forecasts.append(PriceForecast(
                commodity_id=commodity_id,
                mandi_id=mandi_id,
                current_price=round(current_price, 0),
                price_7d=round(p7, 0),
                price_14d=round(p14, 0),
                price_30d=round(p30, 0),
                ci_lower_7d=round(p7 - ci_7, 0),
                ci_upper_7d=round(p7 + ci_7, 0),
                ci_lower_14d=round(p14 - ci_14, 0),
                ci_upper_14d=round(p14 + ci_14, 0),
                ci_lower_30d=round(p30 - ci_30, 0),
                ci_upper_30d=round(p30 + ci_30, 0),
                direction=direction,
                confidence=round(0.65, 2),
                feature_importances={"seasonal_index": 1.0},
            ))

        return forecasts

    def save(self, path: str = "models/price_model.joblib"):
        """Save trained models to disk."""
        import joblib
        joblib.dump({
            "model_7d": self._model_7d,
            "model_14d": self._model_14d,
            "model_30d": self._model_30d,
            "metrics": self.metrics,
            "feature_importances": self.feature_importances,
        }, path)

    def load(self, path: str = "models/price_model.joblib"):
        """Load pre-trained models from disk."""
        import joblib
        data = joblib.load(path)
        self._model_7d = data["model_7d"]
        self._model_14d = data["model_14d"]
        self._model_30d = data["model_30d"]
        self.metrics = data.get("metrics", {})
        self.feature_importances = data.get("feature_importances", {})
        self._trained = True


def generate_training_data(months_back: int = 12, seed: int = 42) -> pd.DataFrame:
    """Generate realistic synthetic historical price data for model training.

    Creates daily price observations across all mandis and commodities with:
    - Proper seasonal patterns from SEASONAL_INDICES
    - Year-over-year trends
    - Mandi-level variation
    - Correlated weather features
    """
    rng = random.Random(seed)
    np_rng = np.random.RandomState(seed)
    rows = []

    end_date = date.today()
    start_date = end_date - timedelta(days=months_back * 30)

    for mandi in MANDIS:
        for commodity in COMMODITIES:
            if commodity["id"] not in mandi.commodities_traded:
                continue

            base = BASE_PRICES_RS.get(commodity["id"], 2000)
            category_enc = CATEGORY_ENC.get(commodity["category"], 0)
            market_type_enc = MARKET_TYPE_ENC.get(mandi.market_type, 0)

            prices_history = []
            current = base * (0.95 + rng.random() * 0.1)

            current_date = start_date
            while current_date <= end_date:
                if current_date.weekday() >= 6:
                    current_date += timedelta(days=1)
                    continue

                month = current_date.month
                seasonal = SEASONAL_INDICES.get(commodity["id"], {}).get(month, 1.0)

                # Random walk with mean reversion
                shock = np_rng.normal(0, base * 0.01)
                mean_revert = (base * seasonal - current) * 0.03
                current = current + shock + mean_revert
                current = max(base * 0.5, min(base * 1.8, current))

                prices_history.append(current)

                # Weather features (correlated with season)
                rainfall = max(0, np_rng.normal(
                    8 if month in [6, 7, 8, 9, 10, 11] else 2, 3
                ))
                temperature = np_rng.normal(
                    30 if month in [4, 5, 6] else 26, 2
                )

                # Arrival volume
                harvest_months = []
                for hw in commodity.get("harvest_windows", []):
                    harvest_months.extend(hw.get("months", []))
                if month in harvest_months:
                    arrivals = mandi.avg_daily_arrivals_tonnes * rng.uniform(1.2, 2.5)
                else:
                    arrivals = mandi.avg_daily_arrivals_tonnes * rng.uniform(0.3, 0.7)

                # Compute features
                n = len(prices_history)
                trend_7 = _linear_slope(prices_history[-7:]) if n >= 7 else 0
                trend_14 = _linear_slope(prices_history[-14:]) if n >= 14 else 0
                trend_30 = _linear_slope(prices_history[-30:]) if n >= 30 else 0

                window_30 = prices_history[-30:] if n >= 30 else prices_history
                mean_30 = np.mean(window_30)
                std_30 = np.std(window_30)
                vol_30 = std_30 / mean_30 if mean_30 > 0 else 0.05

                # Days since/until harvest
                days_since = _days_since_harvest(current_date, harvest_months)
                days_until = _days_until_harvest(current_date, harvest_months)

                # Targets (future prices)
                # We'll fill these in a post-processing step
                row = {
                    "date": current_date.isoformat(),
                    "mandi_id": mandi.mandi_id,
                    "commodity_id": commodity["id"],
                    "current_reconciled_price": round(current, 0),
                    "price_trend_7d": round(trend_7, 2),
                    "price_trend_14d": round(trend_14, 2),
                    "price_trend_30d": round(trend_30, 2),
                    "price_volatility_30d": round(vol_30, 4),
                    "seasonal_index": seasonal,
                    "days_since_harvest": days_since,
                    "days_until_next_harvest": days_until,
                    "mandi_arrival_volume_7d_avg": round(arrivals, 1),
                    "rainfall_7d": round(rainfall, 1),
                    "temperature_7d_avg": round(temperature, 1),
                    "month_sin": round(math.sin(2 * math.pi * month / 12), 4),
                    "month_cos": round(math.cos(2 * math.pi * month / 12), 4),
                    "commodity_category_encoded": category_enc,
                    "mandi_market_type_encoded": market_type_enc,
                }
                rows.append(row)
                current_date += timedelta(days=1)

    df = pd.DataFrame(rows)

    # Fill targets: for each row, target_7d = price 7 days later for same mandi/commodity
    for group_key, group_df in df.groupby(["mandi_id", "commodity_id"]):
        sorted_idx = group_df.sort_values("date").index
        prices = df.loc[sorted_idx, "current_reconciled_price"].values

        target_7d = np.full(len(prices), np.nan)
        target_14d = np.full(len(prices), np.nan)
        target_30d = np.full(len(prices), np.nan)

        for i in range(len(prices)):
            if i + 5 < len(prices):  # ~7 trading days
                target_7d[i] = prices[i + 5]
            if i + 10 < len(prices):
                target_14d[i] = prices[i + 10]
            if i + 22 < len(prices):
                target_30d[i] = prices[i + 22]

        df.loc[sorted_idx, "target_7d"] = target_7d
        df.loc[sorted_idx, "target_14d"] = target_14d
        df.loc[sorted_idx, "target_30d"] = target_30d

    # Drop rows without targets
    df = df.dropna(subset=["target_7d"])

    log.info("Training data generated: %d rows, %d features", len(df), len(df.columns))
    return df


def _linear_slope(prices: list[float]) -> float:
    """Compute slope of linear fit to price series."""
    if len(prices) < 2:
        return 0.0
    x = np.arange(len(prices))
    y = np.array(prices)
    if np.std(y) == 0:
        return 0.0
    slope = np.polyfit(x, y, 1)[0]
    return float(slope)


def _days_since_harvest(current: date, harvest_months: list[int]) -> int:
    """Days since the most recent harvest month ended."""
    if not harvest_months:
        return 180

    best = 365
    for m in harvest_months:
        # End of harvest month
        year = current.year
        harvest_end = date(year, m, 28)
        if harvest_end > current:
            harvest_end = date(year - 1, m, 28)
        delta = (current - harvest_end).days
        if 0 < delta < best:
            best = delta

    return min(best, 365)


def _days_until_harvest(current: date, harvest_months: list[int]) -> int:
    """Days until the next harvest month starts."""
    if not harvest_months:
        return 180

    best = 365
    for m in harvest_months:
        year = current.year
        harvest_start = date(year, m, 1)
        if harvest_start <= current:
            harvest_start = date(year + 1, m, 1)
        delta = (harvest_start - current).days
        if 0 < delta < best:
            best = delta

    return min(best, 365)
