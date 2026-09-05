# forecaster/test_timdr_forecast_resonance.py
"""
test_timdr_forecast_resonance.py — testy DODANE razem z
`resonance_confidence_multiplier` (kalibrowalny mnożnik wkładu 'rezonansu'
do niepewności prognozy - patrz forecaster/resonance_calibration.py i
docstring na górze forecaster/timdr_forecast.py).

Nie re-testuje całej matematyki `_forecast_param` (to już pokrywa
forecaster/test_j_compress.py::test_timdr_forecast_param_does_not_crash) -
tylko sprawdza, że mnożnik faktycznie coś zmienia (i tylko wtedy, gdy
rezonans jest aktywny).
"""
import pandas as pd
import pytest

from .timdr_forecast import TIMDRForecast


def _make_df(n=30):
    # prosty trend + lekki szum co 5 probek, zeby std (j_compress) bylo > 0
    return pd.DataFrame({
        "temp": [10.0 + 0.1 * i + (0.3 if i % 5 == 0 else 0.0) for i in range(n)],
    })


class TestResonanceConfidenceMultiplierWiring:
    def test_default_multiplier_is_one(self):
        tf = TIMDRForecast(figure_window_days=1)
        assert tf.resonance_confidence_multiplier == 1.0

    def test_higher_multiplier_widens_uncertainty_band_when_resonance_active(self):
        df = _make_df()
        timdr_results = {"rezonans": [("2026-01-01T00:00:00", ["temp", "pressure", "wind_speed"])]}

        baseline = TIMDRForecast(figure_window_days=1, resonance_confidence_multiplier=1.0)
        calibrated = TIMDRForecast(figure_window_days=1, resonance_confidence_multiplier=3.0)

        res_baseline = baseline._forecast_param(df, "temp", steps=3, timdr_results=timdr_results)
        res_calibrated = calibrated._forecast_param(df, "temp", steps=3, timdr_results=timdr_results)

        band_baseline = res_baseline["upper"][0] - res_baseline["lower"][0]
        band_calibrated = res_calibrated["upper"][0] - res_calibrated["lower"][0]
        assert band_calibrated > band_baseline
        assert "mnożnik kalibracji=3.00" in res_calibrated["timdr_adjustment"]

    def test_multiplier_has_no_effect_when_resonance_not_active(self):
        df = _make_df()
        baseline = TIMDRForecast(figure_window_days=1, resonance_confidence_multiplier=1.0)
        calibrated = TIMDRForecast(figure_window_days=1, resonance_confidence_multiplier=3.0)

        res_baseline = baseline._forecast_param(df, "temp", steps=3, timdr_results={})
        res_calibrated = calibrated._forecast_param(df, "temp", steps=3, timdr_results={})

        assert res_baseline["upper"] == res_calibrated["upper"]
        assert res_baseline["lower"] == res_calibrated["lower"]

    def test_from_calibrated_falls_back_to_default_multiplier_when_csv_missing(self):
        tf, result = TIMDRForecast.from_calibrated("/nonexistent/path/does_not_exist.csv")
        assert result["status"] == "insufficient_data"
        assert tf.resonance_confidence_multiplier == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
