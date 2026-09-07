"""Testy dla gui_app.py::_backfill_real_observations - automatycznego
uzupełniania rzeczywistych obserwacji (patrz gui_app.py, docstring tej
funkcji, za pełne uzasadnienie: ręczne wpisy IMGW_real_*/web_szukaj_*
w krakow_forecast_snapshots.csv ustały 2026-08-22, ta funkcja ma je
zastąpić automatyzacją opartą o Open-Meteo Archive API).

Sieć jest tu ZAWSZE mockowana (monkeypatch na gui_app._fetch_historical) -
te testy nie robią żadnych żywych wywołań HTTP, więc działają identycznie
offline i online.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
import pytest

import gui_app


def _fake_hourly_df(start: date, end: date, temp_by_day: dict | None = None):
    """Buduje DataFrame o takim samym kształcie, jaki zwraca
    gui_app._fetch_historical: indeks godzinowy 'time', kolumny
    temp/precip/pressure/wind/wind_dir/humidity."""
    temp_by_day = temp_by_day or {}
    rows = []
    d = start
    while d <= end:
        base_temp = temp_by_day.get(d, 20.0)
        for hour in range(24):
            rows.append({
                "time": pd.Timestamp(d) + pd.Timedelta(hours=hour),
                "temp": base_temp + (hour - 12) * 0.1,  # max w poludnie-ish, wciaz > base
                "precip": 0.1 if hour == 15 else 0.0,
                "pressure": 1013.0,
                "wind": 10.0 + hour * 0.01,
                "wind_dir": 180.0,
                "humidity": 70.0,
            })
        d += timedelta(days=1)
    df = pd.DataFrame(rows).set_index("time")
    return df


def test_backfill_adds_rows_for_missing_past_days(tmp_path, monkeypatch):
    csv_path = str(tmp_path / "snapshots.csv")
    today = date.today()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    fake_hist = _fake_hourly_df(
        two_days_ago, yesterday,
        temp_by_day={yesterday: 22.0, two_days_ago: 18.0},
    )
    monkeypatch.setattr(gui_app, "_fetch_historical", lambda lat, lon, days_back: fake_hist)

    gui_app._backfill_real_observations(csv_path, "TestStation", 50.0, 20.0, lookback_days=3)

    df = pd.read_csv(csv_path, dtype={"source": str})
    real_rows = df[df["source"] == gui_app._REAL_BACKFILL_SOURCE]
    assert set(real_rows["target_date"]) == {str(yesterday), str(two_days_ago)}
    row_y = real_rows[real_rows["target_date"] == str(yesterday)].iloc[0]
    assert row_y["max_temp_c"] == pytest.approx(22.0 + 11 * 0.1, abs=1e-6)
    assert row_y["station"] == "TestStation"


def test_backfill_skips_dates_already_covered(tmp_path, monkeypatch):
    csv_path = str(tmp_path / "snapshots.csv")
    today = date.today()
    yesterday = today - timedelta(days=1)

    # CSV juz ma reczny wpis "IMGW_real" dla wczoraj - nie powinien byc dublowany
    existing = pd.DataFrame([{
        "station": "TestStation", "target_date": str(yesterday), "issue_date": "",
        "pull_seq": "", "lead_days": "", "min_temp_c": "", "avg_temp_c": "",
        "max_temp_c": 19.5, "precip_mm": "", "pressure_hpa": "", "wind_kmh": "",
        "source": "IMGW_real_15:00", "v4_point_c": "", "v4_lower_c": "", "v4_upper_c": "",
    }], columns=gui_app._CSV_FIELDNAMES)
    existing.to_csv(csv_path, index=False)

    fake_hist = _fake_hourly_df(yesterday, yesterday, temp_by_day={yesterday: 99.0})
    monkeypatch.setattr(gui_app, "_fetch_historical", lambda lat, lon, days_back: fake_hist)

    gui_app._backfill_real_observations(csv_path, "TestStation", 50.0, 20.0, lookback_days=2)

    df = pd.read_csv(csv_path, dtype={"source": str})
    # wciaz tylko 1 wiersz dla wczoraj (stary, reczny) - nowy NIE zostal dopisany
    rows_for_yday = df[df["target_date"] == str(yesterday)]
    assert len(rows_for_yday) == 1
    assert rows_for_yday.iloc[0]["source"] == "IMGW_real_15:00"
    assert (df["source"] == gui_app._REAL_BACKFILL_SOURCE).sum() == 0


def test_backfill_is_idempotent(tmp_path, monkeypatch):
    csv_path = str(tmp_path / "snapshots.csv")
    yesterday = date.today() - timedelta(days=1)
    fake_hist = _fake_hourly_df(yesterday, yesterday, temp_by_day={yesterday: 15.0})
    monkeypatch.setattr(gui_app, "_fetch_historical", lambda lat, lon, days_back: fake_hist)

    gui_app._backfill_real_observations(csv_path, "TestStation", 50.0, 20.0, lookback_days=2)
    gui_app._backfill_real_observations(csv_path, "TestStation", 50.0, 20.0, lookback_days=2)

    df = pd.read_csv(csv_path, dtype={"source": str})
    real_rows = df[df["source"] == gui_app._REAL_BACKFILL_SOURCE]
    assert len(real_rows) == 1  # drugie wywolanie nie zdublowalo wiersza


def test_backfill_handles_fetch_failure_gracefully(tmp_path, monkeypatch):
    csv_path = str(tmp_path / "snapshots.csv")

    def _raise(*a, **k):
        raise RuntimeError("Open-Meteo niedostepne")
    monkeypatch.setattr(gui_app, "_fetch_historical", _raise)

    # nie powinno rzucic wyjatku
    gui_app._backfill_real_observations(csv_path, "TestStation", 50.0, 20.0, lookback_days=3)
    assert not os.path.exists(csv_path)  # nic nie dopisane, plik nawet nie powstal


def test_backfill_skips_days_missing_from_archive_response(tmp_path, monkeypatch):
    csv_path = str(tmp_path / "snapshots.csv")
    today = date.today()
    yesterday = today - timedelta(days=1)
    # archiwum zwraca dane TYLKO dla wczoraj, mimo ze lookback=3 (np. Open-Meteo
    # jeszcze nie ma danych za starsze dni) - funkcja nie powinna zgadywac/crashowac
    fake_hist = _fake_hourly_df(yesterday, yesterday, temp_by_day={yesterday: 12.0})
    monkeypatch.setattr(gui_app, "_fetch_historical", lambda lat, lon, days_back: fake_hist)

    gui_app._backfill_real_observations(csv_path, "TestStation", 50.0, 20.0, lookback_days=3)

    df = pd.read_csv(csv_path, dtype={"source": str})
    real_rows = df[df["source"] == gui_app._REAL_BACKFILL_SOURCE]
    assert set(real_rows["target_date"]) == {str(yesterday)}


def test_new_source_prefix_recognized_by_bias_correction(tmp_path, monkeypatch):
    """Integracja z forecaster.bias_correction: nowy prefiks
    'OpenMeteo_real' musi byc rozpoznawany jako 'rzeczywistosc'."""
    from forecaster.bias_correction import compute_lead_bias

    csv_path = str(tmp_path / "snapshots.csv")
    today = date.today()
    rows = []
    for i in range(6):
        target = today - timedelta(days=10 - i)
        issue = target - timedelta(days=1)
        rows.append({
            "station": "TestStation", "target_date": str(target), "issue_date": str(issue),
            "pull_seq": 1, "lead_days": 1, "min_temp_c": "", "avg_temp_c": 20.0,
            "max_temp_c": "", "precip_mm": "", "pressure_hpa": "", "wind_kmh": "",
            "source": "prognoza_blending_bias", "v4_point_c": "", "v4_lower_c": "", "v4_upper_c": "",
        })
        rows.append({
            "station": "TestStation", "target_date": str(target), "issue_date": "",
            "pull_seq": "", "lead_days": "", "min_temp_c": "", "avg_temp_c": "",
            "max_temp_c": 22.0, "precip_mm": "", "pressure_hpa": "", "wind_kmh": "",
            "source": "OpenMeteo_real_dailymax", "v4_point_c": "", "v4_lower_c": "", "v4_upper_c": "",
        })
    pd.DataFrame(rows, columns=gui_app._CSV_FIELDNAMES).to_csv(csv_path, index=False)

    table = compute_lead_bias(csv_path, station="TestStation", min_samples=5)
    assert 1 in table
    assert table[1]["n"] == 6
    assert table[1]["bias"] == pytest.approx(2.0, abs=1e-6)
