"""Amazon Chronos-Bolt forecaster for drug demand time series.

Chronos-Bolt is a 9M-parameter T5-based time-series foundation model
pre-trained on 100B+ observations.  It runs zero-shot on CPU — no local
training data is needed, which means it can produce calibrated demand
forecasts for new health facilities from day one.

This module wraps ChronosPipeline and provides batch prediction plus an
ensemble helper that combines Chronos with XGBoost predictions.
"""

from __future__ import annotations

import logging
from typing import Any

import torch

logger = logging.getLogger(__name__)


class ChronosBoltForecaster:
    """Zero-shot time-series forecaster using Amazon Chronos-Bolt-Tiny."""

    MODEL_ID = "amazon/chronos-bolt-tiny"
    PARAMS = "9M"
    PRETRAINING = "100B+ observations"

    def __init__(self) -> None:
        self._pipeline: Any | None = None
        self._available: bool = False
        self._loaded: bool = False

    # -- Lazy loading --------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load model on first use.  Silently marks unavailable on failure."""
        if self._loaded:
            return
        self._loaded = True
        try:
            from chronos import ChronosBoltPipeline

            self._pipeline = ChronosBoltPipeline.from_pretrained(
                self.MODEL_ID,
                device_map="cpu",
                dtype=torch.float32,
            )
            self._available = True
            logger.info("Chronos-Bolt-Tiny loaded successfully")
        except Exception:
            logger.warning("Chronos-Bolt unavailable — falling back to XGBoost only", exc_info=True)
            self._available = False

    # -- Public API ----------------------------------------------------------

    @property
    def is_available(self) -> bool:
        self._ensure_loaded()
        return self._available

    @property
    def model_info(self) -> dict:
        return {
            "name": "Amazon Chronos-Bolt-Tiny",
            "model_id": self.MODEL_ID,
            "parameters": self.PARAMS,
            "pretraining_data": self.PRETRAINING,
            "type": "T5 transformer (time-series foundation model)",
            "inference": "zero-shot (no local training needed)",
            "status": "loaded" if self._available else "unavailable",
        }

    def predict_batch(
        self,
        series_dict: dict[str, list[float]],
        prediction_length: int = 1,
    ) -> dict[str, dict[str, float]]:
        """Batch-predict next-step demand for multiple (facility, drug) series.

        Args:
            series_dict: ``{"FAC-IKJ|amoxicillin_250mg": [v1, v2, ...], ...}``
            prediction_length: forecast horizon (default 1 month ahead)

        Returns:
            ``{key: {"median": float, "lower_10": float, "upper_90": float}}``
        """
        self._ensure_loaded()
        if not self._available or not series_dict:
            return {}

        keys = list(series_dict.keys())
        contexts = [torch.tensor(series_dict[k], dtype=torch.float32) for k in keys]

        try:
            quantiles, mean = self._pipeline.predict_quantiles(
                contexts,
                prediction_length=prediction_length,
                quantile_levels=[0.1, 0.5, 0.9],
            )

            # quantiles shape: [batch, prediction_length, n_quantiles]
            results: dict[str, dict[str, float]] = {}
            for i, key in enumerate(keys):
                results[key] = {
                    "median": max(0.0, float(quantiles[i, 0, 1])),   # 50th percentile
                    "lower_10": max(0.0, float(quantiles[i, 0, 0])), # 10th percentile
                    "upper_90": max(0.0, float(quantiles[i, 0, 2])), # 90th percentile
                }
            return results

        except Exception:
            logger.warning("Chronos batch prediction failed", exc_info=True)
            return {}


def build_series_from_training_data(
    training_df: "pd.DataFrame",
) -> dict[str, list[float]]:
    """Extract per-(facility, drug) consumption time series from training data.

    Groups by (facility_id, drug_id), sorts by month, and returns a dict
    mapping ``"facility_id|drug_id"`` to a list of monthly consumption values.
    """
    import pandas as pd  # noqa: F811

    series: dict[str, list[float]] = {}
    for (fac, drug), grp in training_df.groupby(["facility_id", "drug_id"]):
        vals = grp.sort_values("month")["consumption_rate_per_1000"].tolist()
        if len(vals) >= 2:  # need at least 2 points for a meaningful series
            series[f"{fac}|{drug}"] = vals
    return series


def ensemble_predictions(
    xgb_pred: float,
    xgb_lower: float,
    xgb_upper: float,
    chronos_pred: float,
    chronos_lower: float,
    chronos_upper: float,
    xgb_weight: float = 0.65,
) -> dict[str, float]:
    """Weighted ensemble of XGBoost and Chronos-Bolt predictions.

    Point forecast uses weighted average.  Prediction intervals take the
    wider bounds (min of lowers, max of uppers) for conservative coverage.
    """
    chronos_weight = 1.0 - xgb_weight
    return {
        "ensemble_prediction": round(
            xgb_weight * xgb_pred + chronos_weight * chronos_pred, 2
        ),
        "ensemble_lower": round(min(xgb_lower, chronos_lower), 2),
        "ensemble_upper": round(max(xgb_upper, chronos_upper), 2),
        "xgb_prediction": round(xgb_pred, 2),
        "chronos_prediction": round(chronos_pred, 2),
        "xgb_weight": xgb_weight,
        "chronos_weight": chronos_weight,
    }
