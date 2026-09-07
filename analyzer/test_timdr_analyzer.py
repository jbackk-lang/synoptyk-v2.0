# analyzer/test_timdr_analyzer.py
"""
test_timdr_analyzer.py — testy DODANE razem z parametrem `resonance_k`
(kalibrowalny próg K sygnału 'rezonans' - patrz
forecaster/resonance_calibration.py).

Repo wcześniej NIE miało żadnych testów dla TIMDRAnalyzer.analyze() (patrz
komentarz w analyzer/weather_trigger.py: "TIMDRAnalyzer(...) [...] ale nie
ma własnych testów (brak test_timdr_analyzer.py w repo)"). Ten plik NIE
próbuje tego nadrobić w całości - to osobna, większa robota - tylko
pokrywa NOWY parametr `resonance_k`, żeby regres na nim był widoczny.

Żeby testy były deterministyczne i NIE zależały od prawdziwej zawartości
weather_cache.db (współdzielonej, żywej bazy tego repo - jej stan zależy
od tego, co ostatnio pobrało GUI), wstrzykujemy `_FakeThresholds` w miejsce
`analyzer.thresholds` PO konstrukcji (ten sam wzorzec co wstrzykiwany
`engine` w analyzer/test_weather_trigger.py) - is_anomaly/is_defect/
is_trend_reversal są tu w pełni kontrolowane, więc wynik 'rezonans' zależy
WYŁĄCZNIE od logiki liczenia w analyze() (i od resonance_k), nie od
przypadkowego stanu bazy.
"""
import pandas as pd
import pytest

from .timdr_analyzer import DEFAULT_RESONANCE_K, TIMDRAnalyzer


class _FakeThresholds:
    """Stub - is_anomaly() zwraca True dokładnie dla (param, dt) podanych
    w `anomaly_dts_by_param`; is_defect/is_trend_reversal zawsze False
    (nie są tu przedmiotem testu)."""

    def __init__(self, anomaly_dts_by_param: dict):
        self.anomaly_dts_by_param = anomaly_dts_by_param
        self.fallback_df = None  # analyze() ustawia to bezwarunkowo na wejściu

    def is_anomaly(self, value, dt, param):
        return dt in self.anomaly_dts_by_param.get(param, set())

    def is_defect(self, current, previous, dt, param):
        return False

    def is_trend_reversal(self, series, dt, param):
        return False


def _make_df():
    """5 wierszy godzinowych; wszystkie kolumny wymagane przez
    TIMDRAnalyzer.analyze()/WindAnalyzer (w tym 'wind_dir' - bez niego
    WindAnalyzer.sudden_direction_change() rzuca KeyError, patrz
    analyzer/wind_analyzer.py). Wartości liczbowe są tu nieistotne dla
    testu (anomalie kontroluje _FakeThresholds po dacie, nie po wartości)
    - trzymane blisko stałych, żeby defekt/skręt (poza kontrolą stuba)
    nie wpadły przypadkiem."""
    dates = pd.date_range("2026-01-01", periods=5, freq="h")
    df = pd.DataFrame({
        "datetime": dates,
        "temp": [10.0, 10.0, 10.0, 10.0, 40.0],
        "pressure": [1013.0, 1013.0, 1013.0, 1013.0, 800.0],
        "humidity": [60.0, 60.0, 60.0, 60.0, 60.0],
        "wind_speed": [5.0, 5.0, 5.0, 5.0, 50.0],
        "wind_dir": [180.0, 180.0, 180.0, 180.0, 180.0],
        "precip": [0.0, 0.0, 0.0, 0.0, 0.0],
    })
    return df, dates


class TestResonanceKParameter:
    def test_default_resonance_k_is_three(self):
        assert DEFAULT_RESONANCE_K == 3
        analyzer = TIMDRAnalyzer(station="calibration_test_station")
        assert analyzer.resonance_k == 3

    def test_constructor_accepts_custom_resonance_k(self):
        analyzer = TIMDRAnalyzer(station="calibration_test_station", resonance_k=5)
        assert analyzer.resonance_k == 5

    def test_resonance_fires_at_default_k_when_three_params_anomalous(self):
        df, dates = _make_df()
        last_dt = pd.to_datetime(dates[-1])
        anomaly_dts_by_param = {p: {last_dt} for p in ("temp", "pressure", "wind_speed")}

        analyzer = TIMDRAnalyzer(station="calibration_test_station")
        analyzer.thresholds = _FakeThresholds(anomaly_dts_by_param)

        results = analyzer.analyze(df)
        assert len(results["rezonans"]) == 1
        fired_dt, fired_params = results["rezonans"][0]
        assert fired_dt == last_dt
        assert set(fired_params) == {"temp", "pressure", "wind_speed"}

    def test_resonance_does_not_fire_below_calibrated_k(self):
        # te same 3 anomalne kanaly co wyzej, ale skalibrowany prog K=4 ->
        # 3 < 4, rezonans NIE powinien sie odpalic (dokladnie ten
        # mechanizm, ktorego uzywa TIMDRAnalyzer.from_calibrated(), gdy
        # kalibracja na realnych danych zaleca podwyzszenie progu)
        df, dates = _make_df()
        last_dt = pd.to_datetime(dates[-1])
        anomaly_dts_by_param = {p: {last_dt} for p in ("temp", "pressure", "wind_speed")}

        analyzer = TIMDRAnalyzer(station="calibration_test_station", resonance_k=4)
        analyzer.thresholds = _FakeThresholds(anomaly_dts_by_param)

        results = analyzer.analyze(df)
        assert results["rezonans"] == []

    def test_from_calibrated_falls_back_to_default_k_when_csv_missing(self):
        analyzer, result = TIMDRAnalyzer.from_calibrated(
            "/nonexistent/path/does_not_exist.csv", station="calibration_test_station",
        )
        assert result["status"] == "insufficient_data"
        assert analyzer.resonance_k == DEFAULT_RESONANCE_K


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
