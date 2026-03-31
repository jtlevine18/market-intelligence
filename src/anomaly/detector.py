"""
Isolation Forest anomaly detection for drug consumption patterns.

Learns normal consumption patterns from historical facility data and flags
anomalous readings that may indicate stock theft, data entry errors, or
unexpected demand spikes/drops.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models"

ANOMALY_FEATURES = [
    "consumption_rate_per_1000",
    "consumption_last_month",
    "consumption_trend",
    "population_served",
    "facility_type_encoded",
    "drug_category_encoded",
    "month",
    "is_rainy_season",
]

class ConsumptionAnomalyDetector:
    """Isolation Forest for detecting anomalous drug consumption patterns.

    Trained on historical consumption data. At inference, scores each reading
    on a 0-1 scale (0 = normal, 1 = highly anomalous) and flags outliers.
    """

    def __init__(self, contamination: float = 0.05):
        self._model: IsolationForest | None = None
        self._scaler: StandardScaler | None = None
        self._contamination = contamination
        self._metrics: dict[str, Any] = {}

    def is_trained(self) -> bool:
        return self._model is not None

    def train(self, df: pd.DataFrame) -> dict[str, Any]:
        """Train isolation forest on consumption data.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain columns from ANOMALY_FEATURES.

        Returns
        -------
        dict with training metrics: n_samples, n_anomalies, anomaly_rate, etc.
        """
        available = [c for c in ANOMALY_FEATURES if c in df.columns]
        X = df[available].copy().fillna(0)

        self._scaler = StandardScaler()
        X_scaled = self._scaler.fit_transform(X)

        self._model = IsolationForest(
            n_estimators=200,
            contamination=self._contamination,
            max_samples="auto",
            random_state=42,
            n_jobs=-1,
        )
        self._model.fit(X_scaled)

        scores = self._model.decision_function(X_scaled)
        predictions = self._model.predict(X_scaled)
        n_anomalies = int((predictions == -1).sum())

        self._metrics = {
            "n_samples": len(df),
            "n_anomalies": n_anomalies,
            "anomaly_rate": round(n_anomalies / max(1, len(df)), 4),
            "score_mean": round(float(scores.mean()), 4),
            "score_std": round(float(scores.std()), 4),
            "contamination": self._contamination,
            "features_used": available,
        }

        log.info(
            "Anomaly detector trained: %d samples, %d anomalies (%.1f%%)",
            len(df), n_anomalies, 100 * n_anomalies / max(1, len(df)),
        )
        return self._metrics

    def score(self, features: dict[str, Any]) -> dict[str, Any]:
        """Score a single consumption reading for anomalousness.

        Returns
        -------
        dict with anomaly_score (0-1), is_anomaly (bool), raw_score.
        """
        if not self.is_trained():
            raise RuntimeError("Model not trained. Call train() first.")

        X = pd.DataFrame([{c: features.get(c, 0) for c in ANOMALY_FEATURES}])
        X = X.fillna(0)
        X_scaled = self._scaler.transform(X)

        raw_score = float(self._model.decision_function(X_scaled)[0])
        is_anomaly = int(self._model.predict(X_scaled)[0]) == -1

        # Normalize: decision_function returns negative for anomalies
        anomaly_score = float(np.clip(0.5 - raw_score, 0, 1))

        return {
            "anomaly_score": round(anomaly_score, 4),
            "is_anomaly": is_anomaly,
            "raw_score": round(raw_score, 4),
        }

    def score_batch(self, df: pd.DataFrame) -> pd.DataFrame:
        """Score a batch of readings, returning df with anomaly columns added."""
        if not self.is_trained():
            raise RuntimeError("Model not trained")

        available = [c for c in ANOMALY_FEATURES if c in df.columns]
        X = df[available].copy().fillna(0)
        X_scaled = self._scaler.transform(X)

        scores = self._model.decision_function(X_scaled)
        predictions = self._model.predict(X_scaled)

        result = df.copy()
        result["anomaly_score"] = np.clip(0.5 - scores, 0, 1).round(4)
        result["is_anomaly"] = predictions == -1
        return result

    def save(self, path: str | Path | None = None) -> str:
        """Save trained model to disk."""
        if not self.is_trained():
            raise RuntimeError("No trained model to save")
        if path is None:
            DEFAULT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
            path = DEFAULT_MODEL_DIR / "anomaly_detector.joblib"
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self._model,
            "scaler": self._scaler,
            "metrics": self._metrics,
        }, path)
        log.info("Anomaly detector saved to %s", path)
        return str(path)

    def load(self, path: str | Path | None = None) -> None:
        """Load a trained model from disk."""
        if path is None:
            path = DEFAULT_MODEL_DIR / "anomaly_detector.joblib"
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model not found: {path}")
        payload = joblib.load(path)
        self._model = payload["model"]
        self._scaler = payload["scaler"]
        self._metrics = payload.get("metrics", {})
        log.info("Anomaly detector loaded from %s", path)

    @property
    def metrics(self) -> dict[str, Any]:
        return self._metrics
