# forecaster/test_bias_correction.py
import os
import tempfile

import pandas as pd
import pytest

from forecaster.bias_correction import compute_lead_bias, apply_bias_correction

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


class TestMinSamplesGating:
    def test_no_bias_below_threshold(self):
        # 3 sparowane obserwacje na lead_days=2, próg domyślny 5 -> brak wpisu
        rows = []
        for i in range(3):
            rows.append({"station": "X", "target_date": f"2026-01-{10+i:02d}",
                         "issue_date": f"2026-01-{8+i:02d}", "pull_seq": 1, "lead_days": 2,
                         "min_temp_c": None, "avg_temp_c": 10.0, "max_temp_c": None,
                         "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
                         "source": "prognoza"})
            rows.append({"station": "X", "target_date": f"2026-01-{10+i:02d}",
                         "issue_date": None, "pull_seq": None, "lead_days": None,
                         "min_temp_c": None, "avg_temp_c": None, "max_temp_c": 12.0,
                         "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
                         "source": "IMGW_real_15:00"})
        path = _write_csv(rows)
        table = compute_lead_bias(path, min_samples=5)
        assert table == {}
        os.remove(path)

    def test_bias_appears_once_threshold_reached(self):
        rows = []
        for i in range(5):
            rows.append({"station": "X", "target_date": f"2026-01-{10+i:02d}",
                         "issue_date": f"2026-01-{8+i:02d}", "pull_seq": 1, "lead_days": 2,
                         "min_temp_c": None, "avg_temp_c": 10.0, "max_temp_c": None,
                         "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
                         "source": "prognoza"})
            rows.append({"station": "X", "target_date": f"2026-01-{10+i:02d}",
                         "issue_date": None, "pull_seq": None, "lead_days": None,
                         "min_temp_c": None, "avg_temp_c": None, "max_temp_c": 12.0,
                         "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
                         "source": "IMGW_real_15:00"})
        path = _write_csv(rows)
        table = compute_lead_bias(path, min_samples=5)
        assert 2 in table
        assert table[2]["n"] == 5
        assert abs(table[2]["bias"] - 2.0) < 1e-9  # real(12) - forecast(10) = +2 caly czas
        assert abs(table[2]["mae"] - 2.0) < 1e-9
        os.remove(path)


class TestApplyCorrection:
    def test_no_entry_returns_unchanged(self):
        assert apply_bias_correction(15.0, 7, {}) == 15.0

    def test_entry_shifts_value(self):
        table = {3: {"bias": -1.5, "mae": 1.5, "n": 10}}
        assert apply_bias_correction(20.0, 3, table) == 18.5


class TestRobustness:
    def test_missing_file_returns_empty(self):
        table = compute_lead_bias("/nonexistent/path/does_not_exist.csv")
        assert table == {}

    def test_no_real_rows_returns_empty(self):
        rows = [{"station": "X", "target_date": "2026-01-10", "issue_date": "2026-01-08",
                  "pull_seq": 1, "lead_days": 2, "min_temp_c": None, "avg_temp_c": 10.0,
                  "max_temp_c": None, "precip_mm": None, "pressure_hpa": None,
                  "wind_kmh": None, "source": "prognoza"}]
        path = _write_csv(rows)
        assert compute_lead_bias(path) == {}
        os.remove(path)

    def test_accuweather_not_used_as_ground_truth(self):
        # AccuWeather_real NIE powinno wplywac na bias wlasnego silnika
        rows = []
        for i in range(6):
            rows.append({"station": "X", "target_date": f"2026-01-{10+i:02d}",
                         "issue_date": f"2026-01-{8+i:02d}", "pull_seq": 1, "lead_days": 1,
                         "min_temp_c": None, "avg_temp_c": 10.0, "max_temp_c": None,
                         "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
                         "source": "prognoza"})
            rows.append({"station": "X", "target_date": f"2026-01-{10+i:02d}",
                         "issue_date": None, "pull_seq": None, "lead_days": None,
                         "min_temp_c": None, "avg_temp_c": None, "max_temp_c": 99.0,
                         "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
                         "source": "AccuWeather_real_18:00"})
        path = _write_csv(rows)
        # brak IMGW_real/web_szukaj -> brak sparowanych obserwacji w ogole
        assert compute_lead_bias(path, min_samples=5) == {}
        os.remove(path)

    def test_station_filter(self):
        rows = []
        for i in range(6):
            rows.append({"station": "A", "target_date": f"2026-01-{10+i:02d}",
                         "issue_date": f"2026-01-{8+i:02d}", "pull_seq": 1, "lead_days": 0,
                         "min_temp_c": None, "avg_temp_c": 10.0, "max_temp_c": None,
                         "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
                         "source": "prognoza"})
            rows.append({"station": "A", "target_date": f"2026-01-{10+i:02d}",
                         "issue_date": None, "pull_seq": None, "lead_days": None,
                         "min_temp_c": None, "avg_temp_c": None, "max_temp_c": 11.0,
                         "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
                         "source": "IMGW_real_15:00"})
            # stacja B: inny (duzy) bias - nie powinien wplywac na wynik dla A
            rows.append({"station": "B", "target_date": f"2026-01-{10+i:02d}",
                         "issue_date": f"2026-01-{8+i:02d}", "pull_seq": 1, "lead_days": 0,
                         "min_temp_c": None, "avg_temp_c": 10.0, "max_temp_c": None,
                         "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
                         "source": "prognoza"})
            rows.append({"station": "B", "target_date": f"2026-01-{10+i:02d}",
                         "issue_date": None, "pull_seq": None, "lead_days": None,
                         "min_temp_c": None, "avg_temp_c": None, "max_temp_c": 30.0,
                         "precip_mm": None, "pressure_hpa": None, "wind_kmh": None,
                         "source": "IMGW_real_15:00"})
        path = _write_csv(rows)
        table_a = compute_lead_bias(path, station="A", min_samples=5)
        assert abs(table_a[0]["bias"] - 1.0) < 1e-9
        table_b = compute_lead_bias(path, station="B", min_samples=5)
        assert abs(table_b[0]["bias"] - 20.0) < 1e-9
        os.remove(path)
