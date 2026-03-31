"""
XGBoost demand forecasting model for health supply chain.

Trains on reconciled facility data, climate signals, and disease surveillance
to predict drug consumption rates. Falls back to the deterministic
climate-driven model in demand.py when untrained.
"""

from __future__ import annotations

import logging
import os
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.preprocessing import LabelEncoder

from config import (
    FACILITIES,
    FACILITY_MAP,
    ESSENTIAL_MEDICINES,
    DRUG_MAP,
    LEAD_TIMES,
    HealthFacility,
)
from src.ingestion.lmis_simulator import (
    simulate_facility_stock,
    _get_season,
)

log = logging.getLogger(__name__)

# Default model save location
DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models"

# Feature columns used for training (order matters for prediction)
FEATURE_COLS = [
    "disease_cases_malaria",
    "disease_cases_diarrhoea",
    "disease_cases_respiratory",
    "consumption_last_month",
    "consumption_trend",
    "avg_temp_30d",
    "avg_precip_30d",
    "avg_humidity_30d",
    "population_served",
    "facility_type_encoded",
    "drug_category_encoded",
    "month",
    "is_rainy_season",
    # Expanded features (supply chain + facility context)
    "consumption_lag_2m",
    "cross_facility_demand_ratio",
    "reporting_quality_encoded",
    "drug_criticality",
    "days_of_stock_current",
    "stock_velocity",
    "lead_time_days",
]

# Facility type encoding
FACILITY_TYPE_ENC = {"hospital": 0, "health_center": 1, "health_post": 2}

# Drug category encoding
CATEGORY_ENC = {
    "Antibiotics": 0,
    "Antimalarials": 1,
    "Analgesics": 2,
    "Cardiovascular": 3,
    "Diabetes": 4,
    "Diagnostics": 5,
    "Diarrhoeal": 6,
    "Maternal Health": 7,
    "Nutrition": 8,
}

# Disease-drug category mapping
DISEASE_CATEGORY_MAP = {
    "Antimalarials": "malaria",
    "Diagnostics": "malaria",
    "Diarrhoeal": "diarrhoea",
    "Antibiotics": "respiratory",
}

# Reporting quality encoding
REPORTING_QUALITY_ENC = {"good": 0, "moderate": 1, "poor": 2}

LEAD_TIME_MAP = LEAD_TIMES


def _generate_climate_for_month(
    fac: HealthFacility, month: int, seed: int,
) -> dict[str, float]:
    """Generate plausible climate data for a facility-month."""
    rng = random.Random(seed + hash(fac.facility_id) + month)

    # Base temps by latitude (West Africa)
    if fac.latitude > 10:
        # Northern Nigeria — hotter, more seasonal
        base_temp = {1: 22, 2: 25, 3: 29, 4: 32, 5: 31, 6: 28,
                     7: 26, 8: 25, 9: 27, 10: 28, 11: 25, 12: 22}
        base_precip = {1: 0, 2: 0, 3: 3, 4: 10, 5: 50, 6: 100,
                       7: 200, 8: 250, 9: 140, 10: 15, 11: 0, 12: 0}
    elif fac.latitude > 6:
        # Coastal West Africa
        base_temp = {1: 27, 2: 28, 3: 29, 4: 28, 5: 27, 6: 26,
                     7: 25, 8: 25, 9: 26, 10: 27, 11: 27, 12: 27}
        base_precip = {1: 25, 2: 40, 3: 80, 4: 150, 5: 200, 6: 300,
                       7: 250, 8: 150, 9: 200, 10: 140, 11: 55, 12: 20}
    else:
        # Ghana
        base_temp = {1: 27, 2: 28, 3: 28, 4: 28, 5: 27, 6: 26,
                     7: 25, 8: 24, 9: 25, 10: 26, 11: 27, 12: 27}
        base_precip = {1: 15, 2: 35, 3: 80, 4: 100, 5: 150, 6: 180,
                       7: 50, 8: 15, 9: 40, 10: 70, 11: 35, 12: 20}

    avg_temp = base_temp.get(month, 27) + rng.uniform(-1.5, 1.5)
    monthly_precip = base_precip.get(month, 50) * rng.uniform(0.7, 1.3)
    avg_precip = monthly_precip / 30  # daily average
    avg_humidity = 60 + avg_precip * 1.5 + rng.uniform(-5, 5)
    avg_humidity = min(95, max(40, avg_humidity))

    return {
        "avg_temp_30d": round(avg_temp, 1),
        "avg_precip_30d": round(avg_precip, 2),
        "avg_humidity_30d": round(avg_humidity, 1),
    }


def _generate_disease_cases(
    fac: HealthFacility, month: int, seed: int,
) -> dict[str, int]:
    """Generate plausible disease case counts per 1000 population."""
    rng = random.Random(seed + hash(fac.facility_id) + month * 7)
    season = _get_season(date(2026, month, 15), fac.latitude)

    pop_factor = fac.population_served / 1000

    if season == "rainy":
        malaria = int(rng.uniform(15, 30) * pop_factor)
        diarrhoea = int(rng.uniform(8, 18) * pop_factor)
        respiratory = int(rng.uniform(12, 22) * pop_factor)
    else:
        malaria = int(rng.uniform(3, 8) * pop_factor)
        diarrhoea = int(rng.uniform(3, 6) * pop_factor)
        respiratory = int(rng.uniform(8, 15) * pop_factor)

    return {
        "disease_cases_malaria": malaria,
        "disease_cases_diarrhoea": diarrhoea,
        "disease_cases_respiratory": respiratory,
    }


class XGBoostDemandModel:
    """XGBoost-based demand forecasting for drug consumption.

    Predicts consumption_rate_per_1000 for each facility x drug x month.
    """

    def __init__(self):
        self._model: xgb.XGBRegressor | None = None
        self._model_lower: xgb.XGBRegressor | None = None  # 10th percentile
        self._model_upper: xgb.XGBRegressor | None = None  # 90th percentile
        self._feature_importances: dict[str, float] = {}
        self._metrics: dict[str, float] = {}

    @property
    def metrics(self) -> dict[str, float]:
        return self._metrics

    @property
    def feature_importances(self) -> dict[str, float]:
        return self._feature_importances

    def is_trained(self) -> bool:
        return self._model is not None

    def build_training_data(
        self,
        reconciled_data: dict[str, dict] | None = None,
        climate_data: dict[str, list[dict]] | None = None,
        facilities: list[HealthFacility] | None = None,
        drugs: list[dict] | None = None,
        months_back: int = 6,
        seed: int = 42,
    ) -> pd.DataFrame:
        """Build training DataFrame by generating 6 months of simulated history.

        Each row: one facility x drug x month with features + target.
        Target: consumption_rate_per_1000 (monthly consumption / population * 1000).
        """
        if facilities is None:
            facilities = FACILITIES
        if drugs is None:
            drugs = ESSENTIAL_MEDICINES

        rows: list[dict] = []

        for month_offset in range(months_back):
            month_num = ((datetime.now().month - 1 - month_offset) % 12) + 1
            sim_seed = seed + month_offset * 100

            for fac in facilities:
                # Generate stock data for this month
                end_dt = date(2026, month_num, 28)
                try:
                    stock_readings = simulate_facility_stock(
                        fac, days_back=30, end_date=end_dt, seed=sim_seed,
                    )
                except Exception:
                    continue

                # Climate data for this month
                climate = _generate_climate_for_month(fac, month_num, sim_seed)

                # Disease data
                disease = _generate_disease_cases(fac, month_num, sim_seed)

                # Season
                season = _get_season(end_dt, fac.latitude)

                # Aggregate stock readings per drug
                drug_consumption: dict[str, float] = {}
                for r in stock_readings:
                    if r.reported and r.consumption_today is not None:
                        did = r.drug_id
                        drug_consumption[did] = drug_consumption.get(did, 0) + r.consumption_today

                # Previous month consumption (for trend feature)
                prev_month = ((month_num - 2) % 12) + 1
                prev_climate = _generate_climate_for_month(fac, prev_month, sim_seed - 100)

                for drug in drugs:
                    did = drug["drug_id"]
                    monthly_consumption = drug_consumption.get(did, 0)
                    pop_factor = fac.population_served / 1000

                    # Target: consumption rate per 1000 pop
                    if pop_factor > 0:
                        target = monthly_consumption / pop_factor
                    else:
                        continue

                    # Consumption trend: ratio vs baseline
                    baseline = drug["consumption_per_1000_month"]
                    if baseline > 0:
                        consumption_trend = target / baseline
                    else:
                        consumption_trend = 1.0

                    # Previous month consumption (estimated from baseline + season)
                    prev_season = _get_season(
                        date(2026, prev_month, 15), fac.latitude,
                    )
                    prev_mult = drug["seasonal_multiplier"].get(prev_season, 1.0)
                    consumption_last_month = baseline * prev_mult

                    # 2-month lag consumption
                    prev2_month = ((month_num - 3) % 12) + 1
                    prev2_season = _get_season(
                        date(2026, prev2_month, 15), fac.latitude,
                    )
                    prev2_mult = drug["seasonal_multiplier"].get(prev2_season, 1.0)
                    consumption_lag_2m = baseline * prev2_mult

                    # Stock velocity: daily consumption rate
                    stock_velocity = monthly_consumption / 30 if monthly_consumption > 0 else 0

                    # Days of stock: estimate from latest readings
                    latest = [r for r in stock_readings if r.drug_id == did and r.reported]
                    if latest and stock_velocity > 0:
                        last_stock = latest[-1].stock_level
                        days_of_stock = last_stock / stock_velocity if last_stock else 0
                    else:
                        days_of_stock = 30  # default 1 month

                    row = {
                        **disease,
                        "consumption_last_month": round(consumption_last_month, 1),
                        "consumption_trend": round(consumption_trend, 3),
                        **climate,
                        "population_served": fac.population_served,
                        "facility_type_encoded": FACILITY_TYPE_ENC.get(
                            fac.facility_type, 1,
                        ),
                        "drug_category_encoded": CATEGORY_ENC.get(
                            drug["category"], 0,
                        ),
                        "month": month_num,
                        "is_rainy_season": 1 if season == "rainy" else 0,
                        # Expanded features
                        "consumption_lag_2m": round(consumption_lag_2m, 1),
                        "cross_facility_demand_ratio": 1.0,  # computed post-hoc
                        "reporting_quality_encoded": REPORTING_QUALITY_ENC.get(
                            fac.reporting_quality, 1,
                        ),
                        "drug_criticality": 1 if drug.get("critical", False) else 0,
                        "days_of_stock_current": round(min(days_of_stock, 180), 1),
                        "stock_velocity": round(stock_velocity, 2),
                        "lead_time_days": LEAD_TIME_MAP.get("regional_depot", 14),
                        # Target
                        "consumption_rate_per_1000": round(target, 2),
                        # Metadata (not features)
                        "_facility_id": fac.facility_id,
                        "_drug_id": did,
                        "_month_offset": month_offset,
                    }
                    rows.append(row)

        df = pd.DataFrame(rows)

        # Compute cross-facility demand ratio post-hoc
        if not df.empty and "consumption_rate_per_1000" in df.columns:
            cat_mean = df.groupby("drug_category_encoded")[
                "consumption_rate_per_1000"
            ].transform("mean")
            df["cross_facility_demand_ratio"] = (
                df["consumption_rate_per_1000"] / cat_mean.clip(lower=1)
            ).round(3)

        log.info(
            "Built training data: %d rows (%d facilities x %d drugs x %d months), %d features",
            len(df), len(facilities), len(drugs), months_back, len(FEATURE_COLS),
        )
        return df

    def train(self, df: pd.DataFrame) -> dict[str, Any]:
        """Train XGBoost model on the training DataFrame.

        Returns metrics dict with RMSE, MAE, R2, and feature importances.
        """
        if df.empty:
            raise ValueError("Training DataFrame is empty")

        X = df[FEATURE_COLS].copy()
        y = df["consumption_rate_per_1000"].copy()

        # Handle any NaN
        X = X.fillna(0)
        y = y.fillna(0)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42,
        )

        # Main model (mean prediction)
        self._model = xgb.XGBRegressor(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            objective="reg:squarederror",
            random_state=42,
            n_jobs=-1,
        )
        self._model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        # Quantile models for prediction intervals
        self._model_lower = xgb.XGBRegressor(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            objective="reg:quantileerror",
            quantile_alpha=0.1,
            random_state=42,
            n_jobs=-1,
        )
        self._model_lower.fit(X_train, y_train, verbose=False)

        self._model_upper = xgb.XGBRegressor(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            objective="reg:quantileerror",
            quantile_alpha=0.9,
            random_state=42,
            n_jobs=-1,
        )
        self._model_upper.fit(X_train, y_train, verbose=False)

        # Evaluate
        y_pred = self._model.predict(X_test)
        rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
        mae = float(mean_absolute_error(y_test, y_pred))
        r2 = float(r2_score(y_test, y_pred))

        # Feature importances
        importances = self._model.feature_importances_
        self._feature_importances = {
            col: round(float(imp), 4)
            for col, imp in zip(FEATURE_COLS, importances)
        }

        self._metrics = {
            "rmse": round(rmse, 3),
            "mae": round(mae, 3),
            "r2": round(r2, 4),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "feature_importances": self._feature_importances,
        }

        log.info(
            "XGBoost trained: RMSE=%.3f, MAE=%.3f, R2=%.4f (%d train, %d test)",
            rmse, mae, r2, len(X_train), len(X_test),
        )

        return self._metrics

    def predict(self, features: dict[str, Any]) -> dict[str, Any]:
        """Predict consumption rate for a single feature vector.

        Parameters
        ----------
        features : dict
            Must contain all keys from FEATURE_COLS.

        Returns
        -------
        dict with predicted_consumption_per_1000, prediction_interval_lower,
        prediction_interval_upper, feature_importances.
        """
        if not self.is_trained():
            raise RuntimeError("Model not trained. Call train() first.")

        X = pd.DataFrame([{col: features.get(col, 0) for col in FEATURE_COLS}])
        X = X.fillna(0)

        pred = float(self._model.predict(X)[0])
        pred_lower = float(self._model_lower.predict(X)[0])
        pred_upper = float(self._model_upper.predict(X)[0])

        # Ensure lower <= pred <= upper
        pred_lower = min(pred_lower, pred)
        pred_upper = max(pred_upper, pred)

        return {
            "predicted_consumption_per_1000": round(max(0, pred), 2),
            "prediction_interval_lower": round(max(0, pred_lower), 2),
            "prediction_interval_upper": round(max(0, pred_upper), 2),
            "feature_importances": self._feature_importances,
        }

    def predict_batch(self, df: pd.DataFrame) -> np.ndarray:
        """Predict consumption rates for a batch of rows (vectorized).

        Returns array of predicted_consumption_per_1000 values.
        """
        if not self.is_trained():
            raise RuntimeError("Model not trained. Call train() first.")
        X = df[FEATURE_COLS].fillna(0)
        return self._model.predict(X)

    def save(self, path: str | Path | None = None) -> str:
        """Save trained model to disk."""
        if not self.is_trained():
            raise RuntimeError("No trained model to save")

        if path is None:
            DEFAULT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
            path = DEFAULT_MODEL_DIR / "demand_xgb.joblib"

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "model": self._model,
            "model_lower": self._model_lower,
            "model_upper": self._model_upper,
            "feature_importances": self._feature_importances,
            "metrics": self._metrics,
            "feature_cols": FEATURE_COLS,
        }
        joblib.dump(payload, path)
        log.info("Model saved to %s", path)
        return str(path)

    def load(self, path: str | Path | None = None) -> None:
        """Load a trained model from disk."""
        if path is None:
            path = DEFAULT_MODEL_DIR / "demand_xgb.joblib"

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        payload = joblib.load(path)
        self._model = payload["model"]
        self._model_lower = payload.get("model_lower")
        self._model_upper = payload.get("model_upper")
        self._feature_importances = payload.get("feature_importances", {})
        self._metrics = payload.get("metrics", {})
        log.info("Model loaded from %s", path)
