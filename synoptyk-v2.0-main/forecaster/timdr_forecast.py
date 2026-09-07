# forecaster/timdr_forecast.py
"""
TIMDRForecast — prognoza faktycznie zasilana sygnałami z TIMDRAnalyzer.

Różnica względem starego SynopticF (j_compress/j_decompress):
  - stary: prognoza = random.gauss(mean, std) — losowa, niepowtarzalna,
    ignoruje jakiekolwiek sygnały TIMDR (skręt/anomalia/rezonans/defekt).
  - nowy: prognoza = deterministyczna ekstrapolacja trendu, ZMODYFIKOWANA
    przez sygnały TIMDR:
      * 'skręt' (trend reversal) dla danego parametru w ostatnich godzinach
        -> liczymy nachylenie trendu tylko OD momentu skrętu, a nie z całego
        okna (bo stary trend już się nie utrzymuje).
      * 'anomalia' / 'defekt' blisko końca okna -> poszerzamy pasmo
        niepewności i ciągniemy prognozę w stronę średniej klimatologicznej
        (mean reversion) — anomalia częściej wraca do normy niż się utrwala.
      * 'rezonans' (≥3 parametry anomalne jednocześnie) -> sygnał możliwej
        zmiany frontu; dodatkowo poszerzamy niepewność i skracamy horyzont,
        w którym ufamy ekstrapolacji trendu.
  - wynik jest w pełni odtwarzalny (brak losowości) i zawiera jawne pasmo
    niepewności zamiast pojedynczej "magicznej" liczby.

KALIBRACJA REZONANSU (DODANE - patrz forecaster/resonance_calibration.py):
  wpływ 'rezonansu' na niepewność (`instability += 1.0` przy `rezonans_active`)
  był dotąd STAŁY, nigdy nie zweryfikowanym na realnych danych założeniem.
  `resonance_confidence_multiplier` (domyślnie 1.0 = brak zmiany zachowania)
  skaluje ten wkład na podstawie tego, czy dni z rezonansem naprawdę miały
  wyższy błąd prognozy niż dni bez niego (compute_bias-style porównanie na
  krakow_forecast_snapshots.csv) - patrz `TIMDRForecast.from_calibrated()`
  poniżej, żeby zbudować instancję z takiej kalibracji zamiast ręcznie
  wyliczać mnożnik.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import timedelta

from .j_compress import j_compress
from .resonance_calibration import DEFAULT_CONFIDENCE_MULTIPLIER, calibrate_resonance

PARAMS = ["temp", "pressure", "humidity", "wind_speed"]


def _linear_slope(values: list[float]) -> float:
    """Nachylenie trendu (jednostka/krok) metodą najmniejszych kwadratów."""
    n = len(values)
    if n < 2:
        return 0.0
    x = np.arange(n)
    y = np.array(values, dtype=float)
    x_mean, y_mean = x.mean(), y.mean()
    denom = ((x - x_mean) ** 2).sum()
    if denom == 0:
        return 0.0
    return float(((x - x_mean) * (y - y_mean)).sum() / denom)


def _recent_signal_indices(timdr_results: dict, kind: str, param: str, n_rows: int, lookback: int = 24) -> list[int]:
    """
    Zwraca indeksy (pozycje w oknie) wpisów danego typu sygnału TIMDR
    dotyczących danego parametru, w ostatnich `lookback` wierszach.
    Odporne na niejednorodny kształt krotek (patrz analyzer/timdr_analyzer.py:
    wpis 'defekt' dla wiatru ma inny układ niż pozostałe).
    """
    hits = []
    for entry in timdr_results.get(kind, []):
        if len(entry) < 2:
            continue
        first, second = entry[0], entry[1]
        matched_param = None
        if isinstance(second, str) and second == param:
            matched_param = param
        elif isinstance(first, str) and first == param:
            matched_param = param
        if matched_param:
            hits.append(True)
    # Uproszczenie: TIMDRAnalyzer nie przechowuje bieżącego indeksu wiersza,
    # więc traktujemy obecność JAKIEGOKOLWIEK trafienia jako "aktywne w oknie"
    # (repo nie loguje pozycji — to należałoby rozszerzyć w TIMDRAnalyzer,
    # żeby zwracał (index, dt, param, value) zamiast (dt, param, value)).
    return list(range(max(0, n_rows - lookback), n_rows)) if hits else []


class TIMDRForecast:
    def __init__(self, figure_window_days: int = 7,
                 resonance_confidence_multiplier: float = DEFAULT_CONFIDENCE_MULTIPLIER):
        """
        resonance_confidence_multiplier: mnożnik wkładu sygnału 'rezonans'
        do niepewności prognozy (patrz `_forecast_param`, `rezonans_active`).
        1.0 (domyślnie) = zachowanie identyczne jak przed kalibracją. Wartość
        > 1.0 pochodzi zwykle z `resonance_calibration.calibrate_resonance()`
        - patrz `from_calibrated()` niżej - i oznacza, że dni rezonansowe w
        realnych danych faktycznie miały wyższy błąd prognozy, więc rezonans
        powinien poszerzać niepewność MOCNIEJ niż stały wkład 1.0.
        """
        self.figure_window_days = figure_window_days
        self.resonance_confidence_multiplier = resonance_confidence_multiplier

    @classmethod
    def from_calibrated(cls, csv_path: str, station: str | None = None,
                         figure_window_days: int = 7, k: int | None = None,
                         min_samples_per_group: int = 8) -> tuple["TIMDRForecast", dict]:
        """
        Buduje TIMDRForecast, którego wkład rezonansu do niepewności jest
        skalibrowany na realnych danych z `csv_path` (patrz
        forecaster/resonance_calibration.py:calibrate_resonance).

        Zwraca (instancja, wynik_kalibracji) - `wynik_kalibracji["status"]`
        to "calibrated" albo "insufficient_data" (patrz tam) - wołający
        (np. gui_app.py) może to zalogować/pokazać, zamiast cicho udawać,
        że kalibracja zawsze się udaje. Przy "insufficient_data" instancja
        i tak dostaje bezpieczny domyślny mnożnik 1.0 (brak zmiany
        zachowania względem stanu sprzed kalibracji).
        """
        kwargs = {} if k is None else {"k": k}
        result = calibrate_resonance(
            csv_path, station=station, min_samples_per_group=min_samples_per_group, **kwargs,
        )
        instance = cls(
            figure_window_days=figure_window_days,
            resonance_confidence_multiplier=result["confidence_multiplier"],
        )
        return instance, result

    def _forecast_param(self, df: pd.DataFrame, param: str, steps: int, timdr_results: dict) -> dict:
        series = df[param].dropna().tolist()
        window = series[-self.figure_window_days * 24:] if len(series) > self.figure_window_days * 24 else series
        if len(window) < 2:
            last = window[-1] if window else 0.0
            return {"forecast": [last] * steps, "lower": [last] * steps, "upper": [last] * steps,
                    "slope_per_hour": 0.0, "timdr_adjustment": "brak_danych"}

        # NAPRAWIONE: j_compress zwraca teraz dict (falkowa kompresja v2),
        # nie krotke (mean, std) jak w starym API. Rozpakowujemy z dict,
        # zamiast `mean, std = j_compress(window)`, co rzucalo ValueError.
        compressed = j_compress(window)
        mean, std = compressed['mean'], compressed['std']
        std = std or 1e-6

        skret_idx = _recent_signal_indices(timdr_results, "skręt", param, len(window))
        anomalia_idx = _recent_signal_indices(timdr_results, "anomalia", param, len(window))
        defekt_idx = _recent_signal_indices(timdr_results, "defekt", param, len(window))
        rezonans_active = len(timdr_results.get("rezonans", [])) > 0

        adjustments = []

        # 1. Jeśli wykryto skręt trendu — licz nachylenie tylko z "ogona" po skręcie
        if skret_idx:
            tail_start = skret_idx[0]
            slope_window = window[tail_start:]
            adjustments.append("skręt: trend liczony od punktu odwrócenia")
        else:
            slope_window = window
        slope = _linear_slope(slope_window)

        # 2. Anomalia/defekt blisko końca okna -> mean reversion + szersza niepewność
        instability = 0.0
        if anomalia_idx:
            instability += 0.5
            adjustments.append("anomalia: ściągnięcie prognozy w stronę średniej")
        if defekt_idx:
            instability += 0.5
            adjustments.append("defekt: poszerzone pasmo niepewności")
        if rezonans_active:
            # NAPRAWIONE: wkład rezonansu był stałym 1.0, nigdy nie
            # zweryfikowanym na realnych danych. Teraz skalowany przez
            # resonance_confidence_multiplier (domyślnie 1.0 == bez zmian) -
            # patrz forecaster/resonance_calibration.py i docstring modułu.
            instability += 1.0 * self.resonance_confidence_multiplier
            adjustments.append(
                "rezonans: możliwa zmiana frontu, ekstrapolacja trendu ograniczona "
                f"(mnożnik kalibracji={self.resonance_confidence_multiplier:.2f})"
            )

        mean_reversion_weight = min(0.6, instability * 0.2)  # 0 (brak) .. 0.6 (max)
        uncertainty_multiplier = 1.0 + instability * 0.5

        last_value = window[-1]
        forecast, lower, upper = [], [], []
        for t in range(1, steps + 1):
            # jeśli rezonans aktywny, tłumimy wpływ trendu wraz z horyzontem
            trend_damping = 1.0
            if rezonans_active:
                trend_damping = max(0.2, 1.0 - t / (steps * 1.5))

            raw_point = last_value + slope * t * trend_damping
            point = (1 - mean_reversion_weight) * raw_point + mean_reversion_weight * mean
            point = float(np.clip(point, mean - 4 * std, mean + 4 * std))

            band = std * uncertainty_multiplier * np.sqrt(t)  # niepewność rośnie z horyzontem
            forecast.append(round(point, 2))
            lower.append(round(point - band, 2))
            upper.append(round(point + band, 2))

        return {
            "forecast": forecast,
            "lower": lower,
            "upper": upper,
            "slope_per_hour": round(slope, 4),
            "timdr_adjustment": "; ".join(adjustments) if adjustments else "brak aktywnych sygnałów TIMDR",
        }

    def _forecast_wind_dir(self, df: pd.DataFrame, steps: int, timdr_results: dict) -> dict:
        """Kierunek wiatru: średnia wektorowa (kołowa) z ostatnich 24h jako
        prognoza-persystencja, poszerzona niepewność jeśli TIMDR wykrył
        'nagłą zmianę kierunku' (front) w defekt."""
        if "wind_dir" not in df.columns or df["wind_dir"].dropna().empty:
            return {"forecast": [], "lower": [], "upper": [], "slope_per_hour": 0.0,
                    "timdr_adjustment": "brak_danych"}

        subset = df["wind_dir"].dropna().tail(24).values
        u = np.mean(np.sin(np.radians(subset)))
        v = np.mean(np.cos(np.radians(subset)))
        persisted_dir = (np.degrees(np.arctan2(u, v)) + 360) % 360

        front_detected = any(
            len(e) >= 2 and (e[0] == "wind_dir" or (len(e) > 1 and e[1] == "wind_dir"))
            for e in timdr_results.get("defekt", [])
        )
        uncertainty = 60.0 if front_detected else 20.0
        adj = "defekt: wykryto niedawną nagłą zmianę kierunku — szeroka niepewność (możliwe przejście frontu)" \
            if front_detected else "persystencja kierunku wiatru (brak przesłanek do zmiany)"

        forecast = [round(persisted_dir, 1)] * steps
        lower = [round((persisted_dir - uncertainty) % 360, 1)] * steps
        upper = [round((persisted_dir + uncertainty) % 360, 1)] * steps
        return {"forecast": forecast, "lower": lower, "upper": upper,
                "slope_per_hour": 0.0, "timdr_adjustment": adj}

    def predict(self, df: pd.DataFrame, timdr_results: dict, horizon_days: int = 3,
                anchor_date=None) -> dict:
        """
        Prognoza godzinowa dla wszystkich parametrów, zasilona sygnałami TIMDR.

        anchor_date: opcjonalna data "od której" liczą się etykiety dat prognozy
        (np. dzisiejsza data rzeczywista). Jeśli None (domyślnie) — używana jest
        ostatnia data z `df`, co przy danych z opóźnionego API archiwalnego
        (patrz data/fetcher.py: lag_days) skutkuje "starymi" datami w prognozie,
        mimo że same wartości liczbowe wciąż są aktualną ekstrapolacją trendu.
        """
        steps = horizon_days * 24
        if anchor_date is not None:
            last_date = pd.to_datetime(anchor_date)
        else:
            last_date = pd.to_datetime(df["datetime"].iloc[-1])
        dates = [last_date + timedelta(hours=i + 1) for i in range(steps)]

        results = {}
        for param in PARAMS:
            if param not in df.columns:
                continue
            res = self._forecast_param(df, param, steps, timdr_results)
            res["dates"] = dates
            results[param] = res

        if "wind_dir" in df.columns:
            res = self._forecast_wind_dir(df, steps, timdr_results)
            res["dates"] = dates
            results["wind_dir"] = res
        return results

    def predict_daily(self, df: pd.DataFrame, timdr_results: dict, horizon_days: int = 3,
                       anchor_date=None) -> dict:
        hourly = self.predict(df, timdr_results, horizon_days, anchor_date=anchor_date)
        daily = {}
        for param, data in hourly.items():
            f, lo, up, dates = data["forecast"], data["lower"], data["upper"], data["dates"]
            daily_forecast, daily_lower, daily_upper, daily_dates = [], [], [], []
            for i in range(0, len(f), 24):
                chunk_f = f[i:i + 24]
                chunk_lo = lo[i:i + 24]
                chunk_up = up[i:i + 24]
                if chunk_f:
                    daily_forecast.append(round(sum(chunk_f) / len(chunk_f), 2))
                    daily_lower.append(round(sum(chunk_lo) / len(chunk_lo), 2))
                    daily_upper.append(round(sum(chunk_up) / len(chunk_up), 2))
                    daily_dates.append(dates[i].date())
            daily[param] = {
                "daily_forecast": daily_forecast,
                "daily_lower": daily_lower,
                "daily_upper": daily_upper,
                "dates": daily_dates,
                "timdr_adjustment": data["timdr_adjustment"],
            }
        return daily
