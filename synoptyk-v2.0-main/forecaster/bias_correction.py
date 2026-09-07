# forecaster/bias_correction.py
"""
Empiryczna korekta obciążenia (bias correction) głównego silnika, per
lead_days, licząca się NA ŻYWO z historii pulli w
krakow_forecast_snapshots.csv.

To NIE jest model ML — to prosta, w pełni przejrzysta statystyka: dla
każdego lead_days (0..13) osobno bierzemy wszystkie pary (prognoza,
rzeczywistość), jakie zdążyły się już zrealizować, i liczymy średni błąd
(bias = rzeczywistość − prognoza) oraz średni błąd bezwzględny (MAE).

Ponieważ liczone jest na żywo z CSV przy każdym wywołaniu (nie ma osobnego
kroku "treningu" ani zapisanego stanu), tabela korekty aktualizuje się sama
w miarę przybywania nowych sparowanych pulli — im więcej dni logowania, tym
więcej lead_days ma wystarczająco dużo próbek, żeby korekta się właączyła.
To najprostsza uczciwa wersja "modelu uczącego się na własnych błędach",
bez fabrykowania czegoś bardziej wyrafinowanego niż jest.

Dopóki dla danego lead_days jest mniej niż `min_samples` sparowanych
obserwacji, korekta dla tego lead_days NIE jest stosowana (brak wpisu w
zwróconym słowniku) — żeby nie "korygować" na podstawie 1-2 przypadków, co
jest bliżej zgadywania niż statystyki.
"""
from __future__ import annotations

import pandas as pd

# Źródła traktowane jako "rzeczywistość" (ground truth) do kalibracji
# WŁASNEGO silnika. AccuWeather_real / AccuWeather_prognoza są CELOWO
# pominięte — to inny dostawca, służy do osobnej osi porównania (patrz
# README: "Synoptyk vs rzeczywistość" ORAZ "Synoptyk vs prognoza
# dostawcy" to dwie różne, nie mieszane ze sobą osie).
# "OpenMeteo_real" DODANE 2026-08-22: automatyczne uzupełnianie z
# gui_app.py::_backfill_real_observations (Open-Meteo Archive API, dobowe
# maksimum) — ręczne wpisy IMGW_real_*/web_szukaj_* ustały 2026-08-19 i nie
# miały następcy, bias_correction przestał dostawać świeże pary. Ten nowy
# prefiks działa RAZEM ze starymi, nie zamiast nich.
_REAL_SOURCE_PREFIXES = ("IMGW_real", "web_szukaj", "OpenMeteo_real")
_FORECAST_SOURCE_PREFIX = "prognoza"


def _load_pairs(
    csv_path: str,
    station: str | None = None,
    forecast_col: str = "avg_temp_c",
    real_col: str = "max_temp_c",
) -> pd.DataFrame:
    """Wczytuje CSV i zwraca pary (lead_days, forecast, real) dla każdego
    target_date, gdzie mamy zarówno prognozę, jak i późniejszy pomiar
    rzeczywisty.

    NAPRAWIONE (bug znaleziony przy analizie realnej trafności - patrz
    HISTORIA_BUDOWY.md/README): domyślne parowanie było `avg_temp_c`
    (prognoza) vs `max_temp_c` (rzeczywistość) - a `max_temp_c`
    rzeczywistości to od `_backfill_real_observations()`
    (gui_app.py, `OpenMeteo_real_dailymax`) DOBOWE MAKSIMUM, nie średnia.
    Porównanie "prognozowana średnia" vs "zmierzone maksimum" ma z
    definicji strukturalny, systematyczny offset (max >= avg każdego dnia,
    zwykle kilka stopni w lecie) - to samo w sobie zawyżało zmierzony
    bias/MAE, niezależnie od tego, jak dobry jest model. Starsze wiersze
    real (IMGW_real_15:00/web_szukaj_* - pojedynczy odczyt punktowy z
    popołudnia) miały ten sam problem w mniejszej skali (punkt bliski
    szczytowi dnia, nie prawdziwa średnia).

    Naprawa: `real_col` - domyślnie WCIĄŻ "max_temp_c" (wsteczna
    kompatybilność - istniejące wywołania bez zmian), ale
    `_backfill_real_observations()` od teraz wypełnia RÓWNIEŻ
    `min_temp_c`/`avg_temp_c` rzeczywistości (dobowe min/średnia z tego
    samego archiwum godzinowego) - więc wołający (patrz run_simulation w
    gui_app.py) może poprawnie parować: `forecast_col="avg_temp_c"` z
    `real_col="avg_temp_c"`, `forecast_col="max_temp_c"` z
    `real_col="max_temp_c"`, `forecast_col="min_temp_c"` z
    `real_col="min_temp_c"` - zamiast mieszać średnią z maksimum. Starsze
    wiersze real bez wypełnionego `min_temp_c`/`avg_temp_c` (puste ->
    pd.isna) po prostu nie wejdą do pary dla tych dwóch kolumn - poprawnie
    pomijane, tak jak już działa dla `v4_point_c` niżej.

    `forecast_col` - pozwala liczyć te same pary dla innej kolumny
    prognozy niż domyślna `avg_temp_c` (głównego, mieszanego silnika).
    Konkretnie: `v4_point_c` (samodzielny punkt SynoptykV4, dodany do CSV
    razem z `v4_lower_c`/`v4_upper_c` - patrz DODANE w gui_app.py przy
    `_fetch_forecast`) - żeby móc policzyć bias/MAE osobno dla V4 i
    faktycznie porównać oba tory z rzeczywistością, nie tylko między sobą.
    Wiersze sprzed tej zmiany mają puste `v4_point_c` - te po prostu nie
    wejdą do wyniku (pd.isna), nie trzeba nic dodatkowo obsługiwać.
    """
    df = pd.read_csv(csv_path, dtype={"source": str})
    if station is not None:
        df = df[df["station"] == station]

    fc = df[df["source"].str.startswith(_FORECAST_SOURCE_PREFIX, na=False)].copy()
    real = df[df["source"].str.startswith(_REAL_SOURCE_PREFIXES, na=False)].copy()
    if fc.empty or real.empty:
        return pd.DataFrame(columns=["lead_days", "forecast", "real"])

    # jedna rzeczywista wartość per target_date — jeśli kilka odczytów tego
    # samego dnia, bierzemy ostatni zapisany (najpełniejszy/najświeższy)
    if real_col not in real.columns:
        return pd.DataFrame(columns=["lead_days", "forecast", "real"])
    real_by_date = real.groupby("target_date")[real_col].last()

    rows = []
    for _, r in fc.iterrows():
        real_val = real_by_date.get(r["target_date"])
        if real_val is None or pd.isna(real_val):
            continue
        if forecast_col not in r or pd.isna(r.get(forecast_col)) or pd.isna(r.get("lead_days")):
            continue
        rows.append({
            "lead_days": int(r["lead_days"]),
            "forecast": float(r[forecast_col]),
            "real": float(real_val),
        })
    return pd.DataFrame(rows)


def compute_lead_bias(
    csv_path: str,
    station: str | None = None,
    min_samples: int = 5,
    forecast_col: str = "avg_temp_c",
    real_col: str = "max_temp_c",
) -> dict[int, dict]:
    """Zwraca {lead_days: {"bias": ..., "mae": ..., "n": ...}} TYLKO dla
    lead_days z >= min_samples sparowanymi obserwacjami. Brak wpisu dla
    danego lead_days = brak korekty (za mało danych, NIE zakłada się zera).

    Jeśli plik CSV nie istnieje albo jest pusty/uszkodzony — zwraca pusty
    słownik (brak korekty), nie rzuca wyjątku; to ma być bezpieczny dodatek
    do prognozy, nie kolejny punkt awarii.

    `forecast_col` - patrz `_load_pairs()`; użyj `"v4_point_c"`, żeby
    policzyć bias/MAE dla samodzielnego toru V4 zamiast głównego.

    `real_col` - DOMYŚLNIE "max_temp_c" (wsteczna kompatybilność), ale
    patrz NAPRAWIONE w `_load_pairs()`: żeby faktycznie porównywać
    "jabłka z jabłkami", wołający powinien parować
    `forecast_col="avg_temp_c"` z `real_col="avg_temp_c"` i
    `forecast_col="max_temp_c"` z `real_col="max_temp_c"` (i analogicznie
    dla min) - nie mieszać prognozowanej średniej z realnym maksimum.
    """
    try:
        pairs = _load_pairs(csv_path, station=station, forecast_col=forecast_col, real_col=real_col)
    except Exception:
        return {}

    result: dict[int, dict] = {}
    if pairs.empty:
        return result
    for lead, group in pairs.groupby("lead_days"):
        n = len(group)
        if n < min_samples:
            continue
        errors = group["real"] - group["forecast"]
        result[int(lead)] = {
            "bias": round(float(errors.mean()), 3),
            "mae": round(float(errors.abs().mean()), 3),
            "n": int(n),
        }
    return result


def apply_bias_correction(value: float, lead_days: int, bias_table: dict[int, dict]) -> float:
    """Dodaje wyliczone obciążenie (jeśli jest dostępne dla danego lead_days)
    do wartości prognozy. Brak wpisu w bias_table -> zwraca value bez zmian
    (jeszcze za mało danych, żeby cokolwiek korygować)."""
    entry = bias_table.get(int(lead_days))
    if entry is None:
        return value
    return round(value + entry["bias"], 1)
