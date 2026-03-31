"""
Residual correction model (MOS-style) for health demand forecasting.

Trains a secondary XGBoost on the primary model's prediction errors,
learning systematic biases by facility, drug category, and consumption
pattern. The model-correcting-model pattern mirrors Weather AI 2's
MOS (Model Output Statistics) approach.

Pipeline: Primary XGBoost → Residual XGBoost → Corrected Forecast
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

log = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models"

# Features focused on patterns the primary model misses:
# facility-level biases, consumption momentum, supply chain context
RESIDUAL_FEATURES = [
    "primary_prediction",
    "consumption_last_month",
    "consumption_trend",
    "facility_type_encoded",
    "drug_category_encoded",
    "population_served",
    "month",
    "is_rainy_season",
    "consumption_lag_2m",
    "cross_facility_demand_ratio",
    "drug_criticality",
]


class ResidualCorrectionModel:
    """XGBoost-based residual correction (MOS pattern).

    Learns systematic errors in the primary demand model and applies
    corrections. The correction model is intentionally shallower
    (max_depth=4, more regularization) to avoid overfitting to noise.
    """

    def __init__(self):
        self._model: xgb.XGBRegressor | None = None
        self._metrics: dict[str, Any] = {}
        self._feature_importances: dict[str, float] = {}
        self._features_used: list[str] = []

    def is_trained(self) -> bool:
        return self._model is not None

    def build_residual_data(
        self,
        primary_model,
        training_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Build training data for residual correction.

        Runs primary model predictions on training data, computes residuals,
        and derives additional features the primary model doesn't use.

        Parameters
        ----------
        primary_model : XGBoostDemandModel
            The trained primary demand model.
        training_df : pd.DataFrame
            The same DataFrame used to train the primary model (must include
            FEATURE_COLS + consumption_rate_per_1000).
        """
        from src.forecasting.model import FEATURE_COLS, CATEGORY_ENC
        from config import DRUG_MAP

        actuals = training_df["consumption_rate_per_1000"].fillna(0)

        predictions = primary_model.predict_batch(training_df)
        residuals = actuals.values - predictions

        residual_df = training_df.copy()
        residual_df["primary_prediction"] = predictions
        residual_df["residual"] = residuals

        # Derived features the primary model doesn't have

        # Lagged consumption (2-month lag approximation)
        if "consumption_lag_2m" not in residual_df.columns:
            residual_df["consumption_lag_2m"] = (
                residual_df["consumption_last_month"] * 0.95
            )

        # Cross-facility demand ratio: this row vs category average
        if "cross_facility_demand_ratio" not in residual_df.columns:
            cat_mean = residual_df.groupby("drug_category_encoded")[
                "consumption_rate_per_1000"
            ].transform("mean")
            residual_df["cross_facility_demand_ratio"] = (
                residual_df["consumption_rate_per_1000"] / cat_mean.clip(lower=1)
            ).round(3)

        # Drug criticality (binary)
        if "drug_criticality" not in residual_df.columns:
            if "_drug_id" in residual_df.columns:
                residual_df["drug_criticality"] = residual_df["_drug_id"].map(
                    lambda d: 1 if DRUG_MAP.get(d, {}).get("critical", False) else 0
                )
            else:
                residual_df["drug_criticality"] = 0

        return residual_df

    def train(self, residual_df: pd.DataFrame) -> dict[str, Any]:
        """Train the residual correction model.

        Returns
        -------
        dict with metrics including before/after RMSE and improvement %.
        """
        self._features_used = [f for f in RESIDUAL_FEATURES if f in residual_df.columns]
        X = residual_df[self._features_used].fillna(0)
        y = residual_df["residual"].fillna(0)

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42,
        )

        # Shallower, more regularized than primary — avoids overfitting to noise
        self._model = xgb.XGBRegressor(
            n_estimators=150,
            max_depth=4,
            learning_rate=0.05,
            objective="reg:squarederror",
            random_state=42,
            n_jobs=-1,
            reg_alpha=0.1,
            reg_lambda=1.0,
        )
        self._model.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )

        y_pred = self._model.predict(X_test)

        # Compare: uncorrected residuals (baseline = 0) vs corrected
        rmse_before = float(np.sqrt(mean_squared_error(y_test, np.zeros_like(y_test))))
        rmse_after = float(np.sqrt(mean_squared_error(y_test, y_pred)))
        mae_before = float(mean_absolute_error(y_test, np.zeros_like(y_test)))
        mae_after = float(mean_absolute_error(y_test, y_pred))
        r2 = float(r2_score(y_test, y_pred))

        importances = self._model.feature_importances_
        self._feature_importances = {
            col: round(float(imp), 4)
            for col, imp in zip(self._features_used, importances)
        }

        self._metrics = {
            "rmse_residual_before": round(rmse_before, 3),
            "rmse_residual_after": round(rmse_after, 3),
            "rmse_improvement_pct": round(
                100 * (1 - rmse_after / max(rmse_before, 0.001)), 1,
            ),
            "mae_residual_before": round(mae_before, 3),
            "mae_residual_after": round(mae_after, 3),
            "r2_residual": round(r2, 4),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "features_used": self._features_used,
            "feature_importances": self._feature_importances,
        }

        log.info(
            "Residual model trained: RMSE %.3f -> %.3f (%.1f%% improvement), R2=%.4f",
            rmse_before, rmse_after, self._metrics["rmse_improvement_pct"], r2,
        )
        return self._metrics

    def correct(
        self, primary_prediction: float, features: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply residual correction to a primary model prediction.

        Parameters
        ----------
        primary_prediction : float
            The primary model's consumption_rate_per_1000 prediction.
        features : dict
            Feature dict (same keys as RESIDUAL_FEATURES minus primary_prediction).

        Returns
        -------
        dict with primary_prediction, correction, corrected_prediction, correction_pct.
        """
        if not self.is_trained():
            raise RuntimeError("Residual model not trained")

        feature_vec = {"primary_prediction": primary_prediction, **features}
        X = pd.DataFrame(
            [{c: feature_vec.get(c, 0) for c in self._features_used}],
        ).fillna(0)

        correction = float(self._model.predict(X)[0])
        corrected = primary_prediction + correction

        return {
            "primary_prediction": round(primary_prediction, 2),
            "correction": round(correction, 2),
            "corrected_prediction": round(max(0, corrected), 2),
            "correction_pct": round(
                100 * correction / max(abs(primary_prediction), 0.01), 1,
            ),
        }

    def save(self, path: str | Path | None = None) -> str:
        """Save trained model to disk."""
        if not self.is_trained():
            raise RuntimeError("No trained model to save")
        if path is None:
            DEFAULT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
            path = DEFAULT_MODEL_DIR / "residual_correction.joblib"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self._model,
            "metrics": self._metrics,
            "feature_importances": self._feature_importances,
            "features_used": self._features_used,
        }, path)
        log.info("Residual model saved to %s", path)
        return str(path)

    def load(self, path: str | Path | None = None) -> None:
        """Load a trained model from disk."""
        if path is None:
            path = DEFAULT_MODEL_DIR / "residual_correction.joblib"
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model not found: {path}")
        payload = joblib.load(path)
        self._model = payload["model"]
        self._metrics = payload.get("metrics", {})
        self._feature_importances = payload.get("feature_importances", {})
        self._features_used = payload.get("features_used", RESIDUAL_FEATURES)
        log.info("Residual model loaded from %s", path)

    @property
    def metrics(self) -> dict[str, Any]:
        return self._metrics
