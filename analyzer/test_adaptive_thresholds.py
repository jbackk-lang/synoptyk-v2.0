# analyzer/test_adaptive_thresholds.py
"""
Testy regresyjne dla naprawy Pattern B (maskowanie przez samo-odnoszące
się okno) w AdaptiveThresholds.get_thresholds() - gałąź "brak
klimatologii" (fallback_df/df_recent). Patrz duży komentarz "NAPRAWIONE"
w adaptive_thresholds.py:get_thresholds po pełny opis mechanizmu - ten
sam wzorzec i ta sama naprawa (leave-one-out), co w
SYNOPTYK-ARCTIC/arctic_synoptyk/resonance.py:flag_resonance_days,
forecaster/resonance_calibration.py:_flag_resonance_days i
FLIGHT-TRACKING-TIMDR/timdr_flight.py:twist_3d.

Testy budują AdaptiveThresholds z pustą (świeżo utworzoną, tymczasową)
bazą weather_cache.db - `cache.load_last_n_days(30)` zwróci wtedy zawsze
pusty DataFrame, więc get_thresholds() zawsze spada na `fallback_df`
(dokładnie ta sama ścieżka, którą realnie ćwiczy analyze() w
timdr_analyzer.py, patrz `self.thresholds.fallback_df = df`).
"""
import os
import tempfile
from datetime import datetime
from statistics import mean, stdev

import pandas as pd
import pytest

from analyzer.adaptive_thresholds import AdaptiveThresholds


@pytest.fixture
def thresholds():
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "weather_cache.db")
        yield AdaptiveThresholds(station="test_station", db_path=db_path)


def _old_self_referential_result(vals: list[float], idx: int) -> dict:
    """Odtwarza CELOWO starą (NAPRAWIONĄ) wersję get_thresholds(): mean/std
    liczone RAZ na CAŁEJ próbce, włącznie z ocenianym punktem - używana
    poniżej WYŁĄCZNIE jako punkt odniesienia w teście regresyjnym na
    maskowanie, nie importowana z produkcyjnego kodu (którego już nie ma)."""
    m = mean(vals)
    s = stdev(vals) if len(vals) > 1 else 1.0
    return {"low": m - 2 * s, "high": m + 2 * s}


def test_get_thresholds_leave_one_out_avoids_masking_on_small_window(thresholds):
    # Realistyczny scenariusz: użytkownik GUI ustawia mały suwak "Historia
    # (dni)" - tylko 4 punkty bazowe + 1 z dużym skokiem. Stara
    # (samo-odnosząca się) wersja progu liczyła mean+/-2*std z WŁASNYM
    # udziałem tego skoku w próbce - przy n=5 jeden ekstremalny punkt
    # potrafi sam zawyżyć własne std na tyle, że nigdy nie przekroczy
    # progu, niezależnie od amplitudy (patrz pętla po amplitudach niżej).
    base_vals = [5.0, 5.1, 4.9, 5.05]
    base_times = pd.date_range("2026-08-01", periods=4, freq="h")

    for amplitude in (4, 6, 8, 12, 20):
        extreme_val = base_vals[0] * amplitude
        extreme_time = base_times[-1] + pd.Timedelta(hours=1)
        df = pd.DataFrame({
            "datetime": list(base_times) + [extreme_time],
            "temp": base_vals + [extreme_val],
        })

        all_vals = base_vals + [extreme_val]
        old_result = _old_self_referential_result(all_vals, idx=4)
        old_flags = extreme_val > old_result["high"] or extreme_val < old_result["low"]
        assert not old_flags, (
            f"amplituda={amplitude}: oczekiwano, ze stara (samo-odnoszaca sie) metoda "
            f"NIE zauwazy anomalii - to jest teza tego testu (maskowanie)"
        )

        thresholds.fallback_df = df
        thresholds._thresholds_cache = {}  # nowe okno = nowa kalibracja (jak nowe analyze())
        assert thresholds.is_anomaly(extreme_val, extreme_time.to_pydatetime(), "temp"), (
            f"amplituda={amplitude}: naprawiona (leave-one-out) metoda powinna wykryc "
            f"anomalie tam, gdzie stara ja maskowala"
        )


def test_get_thresholds_different_rows_get_different_loo_thresholds(thresholds):
    # Regresja wprost na sedno naprawy: PRZED naprawa wszystkie wiersze
    # tego samego (month, param) dostawaly IDENTYCZNY prog (jeden mean/std
    # na caly fallback_df). PO naprawie kazdy wiersz ma WLASNY prog (bez
    # siebie samego w probce) - dwa rozne wiersze o roznych wartosciach
    # powinny wiec (w ogolnym przypadku) dostac rozne `mean`/`low`/`high`.
    vals = [5.0, 5.2, 4.8, 5.1, 30.0, 5.05]
    times = pd.date_range("2026-08-01", periods=len(vals), freq="h")
    df = pd.DataFrame({"datetime": times, "temp": vals})
    thresholds.fallback_df = df

    t_normal = thresholds.get_thresholds(times[0].to_pydatetime(), "temp")
    t_outlier = thresholds.get_thresholds(times[4].to_pydatetime(), "temp")
    assert t_normal["mean"] != t_outlier["mean"], (
        "kazdy wiersz powinien dostawac wlasny prog leave-one-out, nie jeden "
        "wspolny prog dla calego okna"
    )
    # LOO dla wiersza z outlierem liczy mean/std z POZOSTALYCH (bez 30.0) -
    # powinno byc bliskie ~5.03 (srednia pozostalych 5 "spokojnych" wartosci),
    # NIE ~9.something (co dalaby stara metoda wliczajaca 30.0 w siebie).
    assert t_outlier["mean"] == pytest.approx(sum([5.0, 5.2, 4.8, 5.1, 5.05]) / 5, abs=1e-9)


def test_get_thresholds_falls_back_to_degenerate_default_below_min_points(thresholds):
    # n<4 (n_loo<3) - za malo punktow na sensowny LOO, powinien wrocic
    # bezpieczny domyslny prog (zachowanie identyczne jak przed naprawa
    # dla tego brzegowego przypadku).
    times = pd.date_range("2026-08-01", periods=3, freq="h")
    df = pd.DataFrame({"datetime": times, "temp": [5.0, 5.1, 4.9]})
    thresholds.fallback_df = df
    result = thresholds.get_thresholds(times[0].to_pydatetime(), "temp")
    assert result == {"mean": 0, "std": 1, "low": -2, "high": 2, "p10": -1, "p90": 1,
                       "threshold_skret": 1, "threshold_defekt": 1}


def test_get_thresholds_empty_state_still_returns_degenerate_default(thresholds):
    result = thresholds.get_thresholds(datetime(2026, 8, 1), "temp")
    assert result["low"] == -2 and result["high"] == 2
