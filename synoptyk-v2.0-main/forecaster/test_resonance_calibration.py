# forecaster/test_resonance_calibration.py
"""
test_resonance_calibration.py — testy resonance_calibration.py.

Konwencja jak w test_bias_correction.py: budujemy tymczasowy CSV w formacie
krakow_forecast_snapshots.csv (te same kolumny/source-prefiksy) i sprawdzamy
zachowanie na skrajnych, ręcznie policzonych przypadkach - nie na losowych
danych, żeby test był deterministyczny i sprawdzalny "na kartce".

Dwa główne scenariusze (jak w zadaniu/audycie):
  1. TestCalibratedCase - dni oflagowane jako rezonansowe (proxy z
     _flag_resonance_days) MAJĄ faktycznie wyższy błąd prognozy -> kalibracja
     się włącza, confidence_multiplier > 1.0.
  2. TestInsufficientData - za mało sparowanych dni w którejś z grup (albo
     CSV nie istnieje) -> "brak mocy testu", confidence_multiplier wraca do
     1.0 (bez zmiany zachowania), status="insufficient_data" - ten sam
     wzorzec uczciwości co bias_correction.compute_lead_bias.
"""
import os
import tempfile

import pandas as pd
import pytest

from forecaster.resonance_calibration import (
    DEFAULT_CONFIDENCE_MULTIPLIER,
    calibrate_resonance,
    get_resonance_confidence_multiplier,
)

COLUMNS = [
    "station", "target_date", "issue_date", "pull_seq", "lead_days",
    "min_temp_c", "avg_temp_c", "max_temp_c", "precip_mm", "pressure_hpa",
    "wind_kmh", "source",
]


def _write_csv(rows: list[dict]) -> str:
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    df = pd.DataFrame(rows, columns=COLUMNS)
    df.to_csv(path, index=False)
    return path


def _forecast_row(day_id: str, avg_temp_c: float, lead_days: int = 2) -> dict:
    return {
        "station": "X", "target_date": day_id, "issue_date": f"{day_id}-issue",
        "pull_seq": 1, "lead_days": lead_days,
        "min_temp_c": None, "avg_temp_c": avg_temp_c, "max_temp_c": None,
        "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
        "source": "prognoza",
    }


def _real_row(day_id: str, max_temp_c: float, pressure_hpa: float,
              precip_mm: float, wind_kmh: float) -> dict:
    return {
        "station": "X", "target_date": day_id, "issue_date": None,
        "pull_seq": None, "lead_days": None,
        "min_temp_c": None, "avg_temp_c": None, "max_temp_c": max_temp_c,
        "precip_mm": precip_mm, "pressure_hpa": pressure_hpa, "wind_kmh": wind_kmh,
        "source": "OpenMeteo_real_dailymax",
    }


def _build_scenario_csv(n_normal: int = 40, n_flagged: int = 8) -> str:
    """
    n_normal dni "spokojnych" (temp~21 real vs 20 prognoza, pressure~1013,
    precip~0, wind~10 - blisko siebie, mały błąd) + n_flagged dni ze
    SKOKIEM na WSZYSTKICH czterech kanałach jednocześnie (temp/pressure/
    precip/wind) I dużym błędem prognozy (real bardzo daleko od forecast) -
    dokładnie sytuacja, w której prawdziwy rezonans (>=3 anomalne kanały)
    powinien korelować z gorszą prognozą.

    Wartości szczytowe (temp=80, pressure=700, wind=300, precip=500) są
    dobrane tak, żeby margines nad/pod mean±2*std (liczonym na całym
    48-elementowym oknie, z ddof=1 jak pandas .std()) wynosił dla każdego
    kanału > 3 jednostki - z dużym zapasem na błędy zaokrągleń.
    """
    rows = []
    day = 0
    for i in range(max(n_normal, n_flagged)):
        if i < n_flagged:
            day_id = f"D{day:03d}"
            rows.append(_forecast_row(day_id, avg_temp_c=40.0))
            rows.append(_real_row(day_id, max_temp_c=80.0, pressure_hpa=700.0,
                                   precip_mm=500.0, wind_kmh=300.0))
            day += 1
        if i < n_normal:
            day_id = f"D{day:03d}"
            rows.append(_forecast_row(day_id, avg_temp_c=20.0))
            rows.append(_real_row(day_id, max_temp_c=21.0, pressure_hpa=1013.0,
                                   precip_mm=0.0, wind_kmh=10.0))
            day += 1
    return _write_csv(rows)


class TestCalibratedCase:
    def test_calibration_detects_resonance_effect(self):
        path = _build_scenario_csv(n_normal=40, n_flagged=8)
        try:
            result = calibrate_resonance(path, min_samples_per_group=8)
            assert result["status"] == "calibrated"
            assert result["n_resonance_days"] == 8
            assert result["n_normal_days"] == 40
            # blad prognozy: normalne |21-20|=1.0, rezonansowe |80-40|=40.0
            assert result["mae_normal"] == pytest.approx(1.0, abs=1e-6)
            assert result["mae_resonance"] == pytest.approx(40.0, abs=1e-6)
            # duza roznica bledow -> mnoznik podbity do sufitu (3.0)
            assert result["confidence_multiplier"] == pytest.approx(3.0)
            # ratio >> 2.0 -> rekomendacja zlagodzenia progu K (bylo wiecej
            # sygnalu niz lapie obecny K=3)
            assert result["recommended_k"] == 2
        finally:
            os.remove(path)

    def test_get_resonance_confidence_multiplier_matches_calibrate_resonance(self):
        path = _build_scenario_csv(n_normal=40, n_flagged=8)
        try:
            full = calibrate_resonance(path, min_samples_per_group=8)
            multiplier = get_resonance_confidence_multiplier(path, min_samples_per_group=8)
            assert multiplier == full["confidence_multiplier"]
        finally:
            os.remove(path)


class TestInsufficientData:
    def test_too_few_resonance_days_falls_back_to_default(self):
        # tylko 3 dni "rezonansowe" (proxy) wsrod 20 normalnych - ponizej
        # progu min_samples_per_group=8 dla grupy rezonansowej
        path = _build_scenario_csv(n_normal=20, n_flagged=3)
        try:
            result = calibrate_resonance(path, min_samples_per_group=8)
            assert result["status"] == "insufficient_data"
            assert result["confidence_multiplier"] == DEFAULT_CONFIDENCE_MULTIPLIER
            assert result["n_resonance_days"] < 8
            assert "reason" in result
        finally:
            os.remove(path)

    def test_missing_file_returns_safe_default_without_raising(self):
        result = calibrate_resonance("/nonexistent/path/does_not_exist.csv")
        assert result["status"] == "insufficient_data"
        assert result["confidence_multiplier"] == DEFAULT_CONFIDENCE_MULTIPLIER

    def test_no_paired_data_returns_safe_default(self):
        rows = [_forecast_row("D000", avg_temp_c=10.0)]  # brak wiersza 'real'
        path = _write_csv(rows)
        try:
            result = calibrate_resonance(path)
            assert result["status"] == "insufficient_data"
            assert result["confidence_multiplier"] == DEFAULT_CONFIDENCE_MULTIPLIER
        finally:
            os.remove(path)

    def test_wrapper_never_raises_and_returns_default_on_missing_file(self):
        multiplier = get_resonance_confidence_multiplier("/nonexistent/path.csv")
        assert multiplier == DEFAULT_CONFIDENCE_MULTIPLIER


class TestConfidenceMultiplierFloor:
    def test_multiplier_never_drops_below_one_even_if_resonance_days_look_better(self):
        # scenariusz odwrotny: dni "rezonansowe" (proxy) maja MNIEJSZY blad
        # prognozy niz normalne - rezonans z definicji ma tylko poszerzac
        # niepewnosc, nigdy jej nie zwezac ponizej bazowego poziomu.
        rows = []
        day = 0
        for i in range(8):
            day_id = f"R{day:03d}"
            rows.append(_forecast_row(day_id, avg_temp_c=80.0))
            rows.append(_real_row(day_id, max_temp_c=80.0, pressure_hpa=700.0,
                                   precip_mm=500.0, wind_kmh=300.0))  # blad=0
            day += 1
        for i in range(40):
            day_id = f"R{day:03d}"
            rows.append(_forecast_row(day_id, avg_temp_c=10.0))
            rows.append(_real_row(day_id, max_temp_c=21.0, pressure_hpa=1013.0,
                                   precip_mm=0.0, wind_kmh=10.0))  # blad=11
            day += 1
        path = _write_csv(rows)
        try:
            result = calibrate_resonance(path, min_samples_per_group=8)
            assert result["status"] == "calibrated"
            assert result["mae_resonance"] < result["mae_normal"]
            assert result["confidence_multiplier"] == pytest.approx(1.0)
        finally:
            os.remove(path)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
