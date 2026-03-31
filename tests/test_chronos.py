"""Tests for Amazon Chronos-Bolt forecaster and ensemble logic."""

import pytest
import pandas as pd

from src.forecasting.chronos_model import (
    ChronosBoltForecaster,
    build_series_from_training_data,
    ensemble_predictions,
)


# -- Unit tests for ensemble_predictions ------------------------------------


def test_ensemble_weighted_average():
    result = ensemble_predictions(
        xgb_pred=100, xgb_lower=80, xgb_upper=120,
        chronos_pred=90, chronos_lower=70, chronos_upper=110,
    )
    # 0.65 * 100 + 0.35 * 90 = 96.5
    assert result["ensemble_prediction"] == 96.5
    assert result["ensemble_lower"] == 70  # min(80, 70)
    assert result["ensemble_upper"] == 120  # max(120, 110)
    assert result["xgb_weight"] == 0.65
    assert result["chronos_weight"] == 0.35


def test_ensemble_custom_weights():
    result = ensemble_predictions(
        xgb_pred=100, xgb_lower=80, xgb_upper=120,
        chronos_pred=50, chronos_lower=30, chronos_upper=70,
        xgb_weight=0.5,
    )
    assert result["ensemble_prediction"] == 75.0
    assert result["xgb_weight"] == 0.5
    assert result["chronos_weight"] == 0.5


def test_ensemble_preserves_individual_predictions():
    result = ensemble_predictions(
        xgb_pred=100, xgb_lower=80, xgb_upper=120,
        chronos_pred=90, chronos_lower=70, chronos_upper=110,
    )
    assert result["xgb_prediction"] == 100
    assert result["chronos_prediction"] == 90


def test_ensemble_wider_intervals():
    """Ensemble should take the wider bounds for conservative coverage."""
    result = ensemble_predictions(
        xgb_pred=100, xgb_lower=90, xgb_upper=110,
        chronos_pred=100, chronos_lower=60, chronos_upper=140,
    )
    assert result["ensemble_lower"] == 60
    assert result["ensemble_upper"] == 140


# -- Tests for build_series_from_training_data ------------------------------


def test_build_series_basic():
    df = pd.DataFrame({
        "facility_id": ["F1", "F1", "F1", "F2", "F2", "F2"],
        "drug_id": ["D1", "D1", "D1", "D1", "D1", "D1"],
        "month": [1, 2, 3, 1, 2, 3],
        "consumption_rate_per_1000": [10.0, 12.0, 11.0, 20.0, 22.0, 21.0],
    })
    series = build_series_from_training_data(df)
    assert "F1|D1" in series
    assert "F2|D1" in series
    assert series["F1|D1"] == [10.0, 12.0, 11.0]


def test_build_series_skips_single_point():
    """Need at least 2 points for a meaningful series."""
    df = pd.DataFrame({
        "facility_id": ["F1"],
        "drug_id": ["D1"],
        "month": [1],
        "consumption_rate_per_1000": [10.0],
    })
    series = build_series_from_training_data(df)
    assert len(series) == 0


def test_build_series_sorts_by_month():
    df = pd.DataFrame({
        "facility_id": ["F1", "F1", "F1"],
        "drug_id": ["D1", "D1", "D1"],
        "month": [3, 1, 2],
        "consumption_rate_per_1000": [30.0, 10.0, 20.0],
    })
    series = build_series_from_training_data(df)
    assert series["F1|D1"] == [10.0, 20.0, 30.0]


# -- Tests for ChronosBoltForecaster ----------------------------------------


def test_forecaster_model_info():
    f = ChronosBoltForecaster()
    info = f.model_info
    assert info["name"] == "Amazon Chronos-Bolt-Tiny"
    assert info["parameters"] == "9M"
    assert "zero-shot" in info["inference"]


def test_forecaster_empty_input():
    f = ChronosBoltForecaster()
    result = f.predict_batch({})
    assert result == {}


@pytest.mark.slow
def test_forecaster_predict_batch():
    """Integration test: actually loads the model and predicts."""
    f = ChronosBoltForecaster()
    if not f.is_available:
        pytest.skip("Chronos model not available (download required)")

    series = {
        "F1|D1": [10.0, 12.0, 11.0, 13.0, 12.5, 14.0],
        "F2|D1": [20.0, 22.0, 21.0, 23.0, 22.5, 24.0],
    }
    results = f.predict_batch(series)
    assert len(results) == 2
    for key in ("F1|D1", "F2|D1"):
        assert "median" in results[key]
        assert "lower_10" in results[key]
        assert "upper_90" in results[key]
        assert results[key]["median"] >= 0
        assert results[key]["lower_10"] <= results[key]["median"]
        assert results[key]["upper_90"] >= results[key]["median"]
