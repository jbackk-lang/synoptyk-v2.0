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
_REAL_SOURCE_PREFIXES = ("IMGW_real", "web_szukaj")
_FORECAST_SOURCE_PREFIX = "prognoza"


def _load_pairs(csv_path: str, station: str | None = None) -> pd.DataFrame:
    """Wczytuje CSV i zwraca pary (lead_days, forecast, real) dla każdego
    target_date, gdzie mamy zarówno prognozę, jak i późniejszy pomiar
    rzeczywisty.

    UWAGA: wiersze rzeczywiste w CSV to pojedynczy odczyt punktowy (nie
    dobowa średnia) — zapisywany historycznie w kolumnie max_temp_c (tak
    powstawał ten CSV od początku, patrz wpisy IMGW_real_15:00 itp.).
    Porównujemy go więc z avg_temp_c prognozy jako najbliższym przybliżeniu,
    co jest niedoskonałe (punkt w czasie vs średnia dobowa) i wprowadza
    własny szum do oszacowania obciążenia — to dodatkowy powód na
    stosunkowo wysoki domyślny próg `min_samples` w `compute_lead_bias()`.
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
    real_by_date = real.groupby("target_date")["max_temp_c"].last()

    rows = []
    for _, r in fc.iterrows():
        real_val = real_by_date.get(r["target_date"])
        if real_val is None or pd.isna(real_val):
            continue
        if pd.isna(r.get("avg_temp_c")) or pd.isna(r.get("lead_days")):
            continue
        rows.append({
            "lead_days": int(r["lead_days"]),
            "forecast": float(r["avg_temp_c"]),
            "real": float(real_val),
        })
    return pd.DataFrame(rows)


def compute_lead_bias(csv_path: str, station: str | None = None, min_samples: int = 5) -> dict[int, dict]:
    """Zwraca {lead_days: {"bias": ..., "mae": ..., "n": ...}} TYLKO dla
    lead_days z >= min_samples sparowanymi obserwacjami. Brak wpisu dla
    danego lead_days = brak korekty (za mało danych, NIE zakłada się zera).

    Jeśli plik CSV nie istnieje albo jest pusty/uszkodzony — zwraca pusty
    słownik (brak korekty), nie rzuca wyjątku; to ma być bezpieczny dodatek
    do prognozy, nie kolejny punkt awarii.
    """
    try:
        pairs = _load_pairs(csv_path, station=station)
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
