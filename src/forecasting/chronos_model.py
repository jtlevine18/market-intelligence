"""
Amazon Chronos-2 foundation model for probabilistic price forecasting,
with XGBoost MOS (Model Output Statistics) bias-correction layer.

Architecture mirrors Weather AI 2: NeuralGCM -> XGBoost MOS
Here: Chronos-2 -> XGBoost residual correction

Chronos-2 provides:
  - Zero-shot time-series forecasting from price history
  - Native probabilistic output (21 quantiles)
  - Horizon-dependent uncertainty (CI widens naturally)

XGBoost MOS provides:
  - Local mandi/commodity bias correction
  - Learns systematic residuals between Chronos-2 and actuals
  - Uses same 15 contextual features as standalone model

Fallback chain: Chronos-2 + MOS -> XGBoost standalone -> seasonal baseline
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── Chronos availability check ──────────────────────────────────────────

CHRONOS_AVAILABLE = False
CHRONOS2_AVAILABLE = False
_chronos_import_error: Optional[str] = None

try:
    import torch
    from chronos import ChronosPipeline  # V1: chronos-t5-* models

    CHRONOS_AVAILABLE = True

    # Try Chronos2Pipeline for Bolt models (V2)
    try:
        from chronos.chronos2 import Chronos2Pipeline
        CHRONOS2_AVAILABLE = True
    except ImportError:
        pass
except ImportError as e:
    _chronos_import_error = str(e)
    log.info("chronos-forecasting not available: %s -- Chronos path disabled", e)


# ── Constants ───────────────────────────────────────────────────────────

# Model selection priority:
# 1. chronos-bolt-base (Bolt V2, ~250x faster on CPU) -- requires Chronos2Pipeline
# 2. chronos-t5-small (V1, 20M params, solid CPU perf) -- always works with ChronosPipeline
BOLT_MODEL_ID = "amazon/chronos-bolt-tiny"
V1_MODEL_ID = "amazon/chronos-t5-tiny"

QUANTILE_LOW = 0.1   # 10th percentile for CI lower
QUANTILE_MID = 0.5   # median for point forecast
QUANTILE_HIGH = 0.9  # 90th percentile for CI upper


@dataclass
class ChronosForecastResult:
    """Raw Chronos-2 forecast for a single series."""
    horizon_days: int
    median: float
    q10: float  # 10th percentile (CI lower)
    q90: float  # 90th percentile (CI upper)
    all_quantiles: Optional[np.ndarray] = None


class ChronosForecaster:
    """Loads Chronos foundation model and generates probabilistic forecasts.

    Tries Bolt (V2, ~250x faster on CPU) first, falls back to T5-small (V1).
    Designed for CPU inference on HF Spaces free tier.
    """

    def __init__(self, device: str = "cpu"):
        self._pipeline = None
        self._model_id: Optional[str] = None
        self._device = device
        self._loaded = False
        self._load_error: Optional[str] = None
        self._load_time_s: float = 0.0
        self._model_variant: str = ""  # "bolt" or "t5"

    def load(self, timeout_s: float = 300) -> bool:
        """Load the Chronos pipeline. Tries Bolt V2, falls back to T5-small V1.

        Args:
            timeout_s: Max seconds to wait for model download/load (default 5 min).
                       If exceeded, returns False so the pipeline falls back to XGBoost.
        """
        if not CHRONOS_AVAILABLE:
            self._load_error = f"chronos-forecasting not installed: {_chronos_import_error}"
            log.warning("Chronos load skipped: %s", self._load_error)
            return False

        import concurrent.futures

        def _try_load_bolt():
            return Chronos2Pipeline.from_pretrained(
                BOLT_MODEL_ID, device_map=self._device, dtype=torch.float32,
            )

        def _try_load_t5():
            return ChronosPipeline.from_pretrained(
                V1_MODEL_ID, device_map=self._device, dtype=torch.float32,
            )

        # Attempt 1: Chronos-Bolt (V2) via Chronos2Pipeline
        if CHRONOS2_AVAILABLE:
            try:
                t0 = time.time()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_try_load_bolt)
                    self._pipeline = future.result(timeout=timeout_s)
                self._load_time_s = time.time() - t0
                self._loaded = True
                self._model_id = BOLT_MODEL_ID
                self._model_variant = "bolt"
                log.info(
                    "Chronos Bolt loaded: model=%s, device=%s, load_time=%.1fs",
                    self._model_id, self._device, self._load_time_s,
                )
                return True
            except concurrent.futures.TimeoutError:
                log.warning("Chronos Bolt load timed out after %.0fs -- trying T5-small", timeout_s)
            except Exception as e:
                log.info("Chronos Bolt load failed (%s) -- trying T5-small", e)

        # Attempt 2: Chronos T5-small (V1) via ChronosPipeline
        try:
            t0 = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_try_load_t5)
                self._pipeline = future.result(timeout=timeout_s)
            self._load_time_s = time.time() - t0
            self._loaded = True
            self._model_id = V1_MODEL_ID
            self._model_variant = "t5"
            log.info(
                "Chronos T5-small loaded: model=%s, device=%s, load_time=%.1fs",
                self._model_id, self._device, self._load_time_s,
            )
            return True
        except concurrent.futures.TimeoutError:
            self._load_error = f"All Chronos variants timed out after {timeout_s}s"
            log.warning("Chronos load timed out -- falling back to XGBoost")
            return False
        except Exception as e:
            self._load_error = str(e)
            log.warning("Chronos load failed (all variants): %s", e)
            return False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def predict(
        self,
        price_history: np.ndarray,
        prediction_length: int = 30,
    ) -> list[ChronosForecastResult]:
        """Generate probabilistic forecast from price history.

        Args:
            price_history: 1D array of historical prices (daily, chronological).
                          Minimum ~30 points recommended for good forecasts.
            prediction_length: Number of days to forecast (max horizon).

        Returns:
            List of ChronosForecastResult, one per forecast step.
        """
        if not self._loaded or self._pipeline is None:
            raise RuntimeError("Chronos-2 model not loaded. Call load() first.")

        # Chronos expects a torch tensor
        context = torch.tensor(price_history, dtype=torch.float32).unsqueeze(0)

        # Generate quantile forecasts
        # Chronos-2 .predict() returns (batch, num_samples, prediction_length)
        # With quantile_levels, it returns quantiles directly
        quantile_forecasts = self._pipeline.predict(
            context,
            prediction_length=prediction_length,
            limit_prediction_length=False,
        )
        # quantile_forecasts shape: (batch=1, num_samples, prediction_length)
        # Compute quantiles from samples
        samples = quantile_forecasts.numpy()[0]  # (num_samples, prediction_length)
        q10 = np.quantile(samples, QUANTILE_LOW, axis=0)
        q50 = np.quantile(samples, QUANTILE_MID, axis=0)
        q90 = np.quantile(samples, QUANTILE_HIGH, axis=0)

        results = []
        for step in range(prediction_length):
            results.append(ChronosForecastResult(
                horizon_days=step + 1,
                median=float(q50[step]),
                q10=float(q10[step]),
                q90=float(q90[step]),
            ))

        return results

    def predict_at_horizons(
        self,
        price_history: np.ndarray,
        horizons: list[int] = None,
    ) -> dict[int, ChronosForecastResult]:
        """Predict at specific day horizons (7, 14, 30).

        Returns dict mapping horizon_days -> ChronosForecastResult.
        """
        if horizons is None:
            horizons = [7, 14, 30]

        max_horizon = max(horizons)
        all_steps = self.predict(price_history, prediction_length=max_horizon)

        results = {}
        for h in horizons:
            if h <= len(all_steps):
                results[h] = all_steps[h - 1]  # 0-indexed
        return results
