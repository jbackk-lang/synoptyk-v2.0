# forecaster/resonance_calibration.py
"""
Domyka pętlę samokorekty sygnału 'rezonans' (TIMDR) tym samym mechanizmem,
którym bias_correction.py domyka pętlę dla głównego silnika prognozy: liczy
NA ŻYWO z krakow_forecast_snapshots.csv (dokładnie tego samego pliku, co
forecaster/bias_correction.py), czy dni oflagowane jako "rezonansowe"
faktycznie miały wyższy błąd prognozy (MAE, real - forecast) niż dni bez
rezonansu.

PO CO: 'rezonans' (analyzer/timdr_analyzer.py: `len(anomalies_today) >= 3`,
czyli >= K jednocześnie anomalnych parametrów) w forecaster/timdr_forecast.py
(`rezonans_active`) IMPLIKUJE "możliwą zmianę frontu" i poszerza pasmo
niepewności / tłumi ekstrapolację trendu - czyli zakłada, że błąd prognozy
w dniach rezonansowych POWINIEN być wyższy niż normalnie. Do tej pory to
założenie nigdy nie było sprawdzone na rzeczywistych danych - sygnał
rezonansu i maszyneria porównania prognoza-vs-rzeczywistość (bias_correction.py
/ compute_bias.py / krakow_forecast_snapshots.csv) były całkowicie
odseparowane (zero wzajemnych odwołań). Ten moduł je łączy.

PROXY, nie 1:1 odtworzenie: krakow_forecast_snapshots.csv NIE zawiera
godzinowych kanałów wymaganych przez TIMDRAnalyzer.analyze() (potrzebuje
kolumn 'datetime'/'temp'/'pressure'/'humidity'/'wind_speed'/'precip' -
snapshoty mają tylko DOBOWE min/avg/max_temp_c, pressure_hpa, wind_kmh,
precip_mm - bez wilgotności). Rezonans jest tu rekonstruowany jako PROXY:
dla każdej daty z realnym pomiarem liczymy, ile z DOSTĘPNYCH kanałów
(temp, pressure, precip, wind) jest anomalnych względem mean±2*std całego
okna kalibracji - dokładnie ta sama definicja "anomalii", co domyślna
gałąź AdaptiveThresholds.get_thresholds() gdy brak klimatologii (patrz
analyzer/adaptive_thresholds.py: `low = mean - 2*std, high = mean + 2*std`)
- nie wymyślamy tu nowego progu. Traktować jako przybliżenie zbudowane na
jedynych realnych danych, jakie w ogóle mamy sparowane z rzeczywistością,
nie jako podmiankę prawdziwego TIMDRAnalyzer.analyze().

UCZCIWOŚĆ (ten sam wzorzec co bias_correction.compute_lead_bias i co
protokół testowania z timdr-signal-framework: "test bez mocy = brak
wniosku, nie brak efektu"): gdy sparowanych dni jest za mało w
KTÓREJKOLWIEK z dwóch grup (rezonans / brak rezonansu) względem
`min_samples_per_group`, kalibracja NIE jest stosowana -
`confidence_multiplier` wraca 1.0 (zachowanie identyczne jak bez
kalibracji), `status` = "insufficient_data", z jawnym powodem. Nigdy nie
udajemy, że kalibracja się powiodła na garstce przypadków.
"""
from __future__ import annotations

import pandas as pd

from .bias_correction import _FORECAST_SOURCE_PREFIX, _REAL_SOURCE_PREFIXES

# Domyślny próg K sygnału rezonansu - musi się zgadzać z hardkodowanym
# `len(anomalies_today) >= 3` w analyzer/timdr_analyzer.py. Jeśli ta stała
# tam się kiedyś zmieni, warto przekazać `k=` jawnie zamiast polegać na
# tym DEFAULT_K.
DEFAULT_K = 3

# Brak korekty - dokładnie taki wpływ na timdr_forecast.py, jak przed
# wprowadzeniem kalibracji (instability += 1.0 * 1.0 == instability += 1.0).
DEFAULT_CONFIDENCE_MULTIPLIER = 1.0

# Kanały dostępne w krakow_forecast_snapshots.csv dla "rzeczywistości"
# (source zaczynające się od IMGW_real/web_szukaj/OpenMeteo_real) - patrz
# nagłówek CSV. Brak 'humidity' - snapshoty go nie logują.
_REAL_CHANNEL_COLUMNS = {
    "temp": "max_temp_c",
    "pressure": "pressure_hpa",
    "precip": "precip_mm",
    "wind": "wind_kmh",
}


def _load_real_multi_channel(csv_path: str, station: str | None = None) -> pd.DataFrame:
    """Zwraca DataFrame indeksowany target_date, z jedną kolumną na każdy
    dostępny kanał rzeczywistego pomiaru (patrz _REAL_CHANNEL_COLUMNS).
    Jeden wiersz na target_date (ostatni zapisany odczyt danego dnia -
    ten sam wybór, co `real.groupby("target_date")[real_col].last()` w
    bias_correction._load_pairs)."""
    df = pd.read_csv(csv_path, dtype={"source": str})
    if station is not None:
        df = df[df["station"] == station]

    real = df[df["source"].str.startswith(_REAL_SOURCE_PREFIXES, na=False)].copy()
    empty = pd.DataFrame(columns=list(_REAL_CHANNEL_COLUMNS)).rename_axis("target_date")
    if real.empty:
        return empty

    out = {}
    for channel, col in _REAL_CHANNEL_COLUMNS.items():
        if col in real.columns:
            out[channel] = real.groupby("target_date")[col].last()
    if not out:
        return empty
    return pd.DataFrame(out)


def _flag_resonance_days(real_df: pd.DataFrame, k: int = DEFAULT_K) -> pd.Series:
    """PROXY rezonansu na danych dobowych z CSV - patrz docstring modułu.
    Dzień jest "rezonansowy", gdy >= k z dostępnych kanałów jest anomalnych
    (poza mean±2*std całego okna kalibracji) TEGO SAMEGO dnia.

    Zwraca pd.Series[bool] indeksowany target_date (pusty Series, gdy
    real_df jest puste)."""
    if real_df.empty:
        return pd.Series(dtype=bool)

    anomaly_counts = pd.Series(0, index=real_df.index, dtype=int)
    for col in real_df.columns:
        series = real_df[col]
        valid = series.dropna()
        if len(valid) < 3:
            continue
        mean, std = valid.mean(), valid.std()
        if pd.isna(std) or std == 0:
            continue
        low, high = mean - 2 * std, mean + 2 * std
        is_anomaly = ((series > high) | (series < low)).fillna(False)
        anomaly_counts = anomaly_counts.add(is_anomaly.astype(int), fill_value=0)

    return anomaly_counts >= k


def _load_pairs_by_date(
    csv_path: str,
    station: str | None = None,
    forecast_col: str = "avg_temp_c",
    real_col: str = "max_temp_c",
) -> pd.DataFrame:
    """Jak `bias_correction._load_pairs`, ale zachowuje `target_date`
    (potrzebne, żeby połączyć każdą parę forecast/real z flagą rezonansu
    tego dnia) - powiela TĘ SAMĄ logikę parowania, patrz tam po pełny
    opis konwencji/edge case'ów."""
    df = pd.read_csv(csv_path, dtype={"source": str})
    if station is not None:
        df = df[df["station"] == station]

    fc = df[df["source"].str.startswith(_FORECAST_SOURCE_PREFIX, na=False)].copy()
    real = df[df["source"].str.startswith(_REAL_SOURCE_PREFIXES, na=False)].copy()
    columns = ["target_date", "lead_days", "forecast", "real"]
    if fc.empty or real.empty or real_col not in real.columns:
        return pd.DataFrame(columns=columns)

    real_by_date = real.groupby("target_date")[real_col].last()

    rows = []
    for _, r in fc.iterrows():
        real_val = real_by_date.get(r["target_date"])
        if real_val is None or pd.isna(real_val):
            continue
        if forecast_col not in r or pd.isna(r.get(forecast_col)) or pd.isna(r.get("lead_days")):
            continue
        rows.append({
            "target_date": r["target_date"],
            "lead_days": int(r["lead_days"]),
            "forecast": float(r[forecast_col]),
            "real": float(real_val),
        })
    return pd.DataFrame(rows, columns=columns)


def _insufficient(k: int, n_res: int, n_normal: int, reason: str) -> dict:
    return {
        "status": "insufficient_data",
        "k": k,
        "recommended_k": k,
        "n_resonance_days": n_res,
        "n_normal_days": n_normal,
        "confidence_multiplier": DEFAULT_CONFIDENCE_MULTIPLIER,
        "reason": reason,
    }


def calibrate_resonance(
    csv_path: str,
    station: str | None = None,
    k: int = DEFAULT_K,
    min_samples_per_group: int = 8,
    forecast_col: str = "avg_temp_c",
    real_col: str = "max_temp_c",
) -> dict:
    """
    Liczy, czy dni oflagowane jako rezonansowe (proxy `_flag_resonance_days`,
    próg `k`) faktycznie miały wyższy błąd prognozy (MAE = |real - forecast|)
    niż dni bez rezonansu, i z tego wyprowadza:

      - `confidence_multiplier`: mnożnik niepewności do użycia w miejscu
        sztywnego `instability += 1.0` w forecaster/timdr_forecast.py
        (`rezonans_active`) - stosunek mae_resonance/mae_normal, PODŁOGOWANY
        do 1.0 (rezonans z definicji ma tylko poszerzać niepewność, nigdy
        jej nie zawężać poniżej poziomu bazowego) i SUFITOWANY do 3.0 (żeby
        jeden skrajny dzień nie zdominował całej kalibracji).
      - `recommended_k`: sugerowana korekta progu K (analyzer/timdr_analyzer.py)
        - +1 (surowszy próg, k<=5), gdy dni rezonansowe NIE są w praktyce
        gorsze (ratio < 1.05, czyli obecny K łapie głównie fałszywe alarmy);
        -1 (luźniejszy próg, k>=2), gdy są WYRAŹNIE gorsze (ratio > 2.0,
        czyli można by łapać więcej takich dni obniżając próg); inaczej bez
        zmian.

    Zwraca dict z kluczem "status":
      "calibrated" - wystarczająco danych w OBU grupach (>= min_samples_per_group
        sparowanych dni każda) - zawiera też mae_resonance/mae_normal/n_resonance_days/n_normal_days.
      "insufficient_data" - za mało sparowanych dni w którejś z grup (albo
        CSV brakuje/jest pusty/uszkodzony) - `confidence_multiplier` = 1.0
        (brak korekty), `reason` z opisem. Nigdy nie rzuca wyjątku.
    """
    try:
        real_df = _load_real_multi_channel(csv_path, station=station)
        pairs = _load_pairs_by_date(csv_path, station=station, forecast_col=forecast_col, real_col=real_col)
    except Exception as exc:  # brak pliku, uszkodzony CSV, zła kolumna...
        return _insufficient(k, 0, 0, f"błąd wczytywania CSV ({exc!r})")

    if real_df.empty or pairs.empty:
        return _insufficient(k, 0, 0, "brak sparowanych danych prognoza+rzeczywistość w CSV")

    resonance_flags = _flag_resonance_days(real_df, k=k)
    pairs = pairs.copy()
    pairs["is_resonance"] = pairs["target_date"].map(resonance_flags).fillna(False)

    errors = (pairs["real"] - pairs["forecast"]).abs()
    res_mask = pairs["is_resonance"]
    n_res = int(res_mask.sum())
    n_normal = int((~res_mask).sum())

    if n_res < min_samples_per_group or n_normal < min_samples_per_group:
        return _insufficient(
            k, n_res, n_normal,
            f"za mało sparowanych dni w jednej z grup (rezonans={n_res}, "
            f"normalne={n_normal}), potrzeba >= {min_samples_per_group} w obu",
        )

    mae_resonance = float(errors[res_mask].mean())
    mae_normal = float(errors[~res_mask].mean())
    ratio = (mae_resonance / mae_normal) if mae_normal > 0 else 1.0
    confidence_multiplier = min(3.0, max(1.0, ratio))

    recommended_k = k
    if ratio < 1.05 and k < 5:
        recommended_k = k + 1
    elif ratio > 2.0 and k > 2:
        recommended_k = k - 1

    return {
        "status": "calibrated",
        "k": k,
        "recommended_k": recommended_k,
        "n_resonance_days": n_res,
        "n_normal_days": n_normal,
        "mae_resonance": round(mae_resonance, 3),
        "mae_normal": round(mae_normal, 3),
        "confidence_multiplier": round(confidence_multiplier, 3),
    }


def get_resonance_confidence_multiplier(
    csv_path: str,
    station: str | None = None,
    k: int = DEFAULT_K,
    min_samples_per_group: int = 8,
    **kwargs,
) -> float:
    """Wygodny wrapper dla forecaster/timdr_forecast.py: zwraca WYŁĄCZNIE
    mnożnik (1.0 = brak korekty - ani gdy dane są niewystarczające, ani przy
    jakimkolwiek błędzie). Nigdy nie rzuca wyjątku - bezpieczne do
    wstrzyknięcia jako domyślny argument konstruktora."""
    try:
        result = calibrate_resonance(
            csv_path, station=station, k=k, min_samples_per_group=min_samples_per_group, **kwargs,
        )
        return result["confidence_multiplier"]
    except Exception:
        return DEFAULT_CONFIDENCE_MULTIPLIER
