"""
Synoptyk-v2.0  gui_app.py  – przepisany GUI
=============================================
Zmiany względem oryginału:
  • prognoza wielodniowa (1–14 dni naprzód), każdy dzień jako osobny wiersz z datą
  • 4 parametry: Temperatura, Ciśnienie, Opady, Wiatr
  • dane pobierane z Open-Meteo (hourly archive → resampled daily)
  • wyraźna informacja o dacie ostatnich danych (koniec cache'a vs. live)
  • ostrzeżenie w GUI gdy dane są starsze niż 2 doby
  • weather_cache.db pomijane – dane zawsze świeże z API
  • NAPRAWIONE: daleki horyzont (+3d..+13d) stabilizowany mieszanką z
    własną deterministyczną ekstrapolacją trendu (SynoptykV4) - Open-Meteo
    samo potrafi mocno zmieniać prognozę między pobraniami tego samego dnia
    na tym horyzoncie (przelicza swój model NWP kilka razy dziennie) -
    patrz _blend_weight()/_own_trend_points() niżej
  • DODANE: korekta obciążenia (bias correction) temp. średniej, licząca
    się na żywo z historii krakow_forecast_snapshots.csv per lead_days -
    "uczy się" własnych błędów bez osobnego kroku treningowego, kod sam
    raportuje w Dzienniku dla ilu lead_days ma wystarczająco próbek (próg
    5) - patrz forecaster/bias_correction.py
"""

from __future__ import annotations

import csv
import json
import os
import sys
import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
import gradio as gr
import requests

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ── opcjonalne importy z oryginalnego repo ─────────────────────────────────
try:
    from grid_engine import SpatialGridEngine, get_region_bbox
    _GRID_OK = True
except Exception:
    _GRID_OK = False

try:
    from synoptyk_f import SynoptykFEngine
    _SF_OK = True
except Exception:
    _SF_OK = False

try:
    from topomap_data import TOPOGRAPHY_DATABASE, get_node_metadata
    _TOPO_OK = True
except Exception:
    TOPOGRAPHY_DATABASE = {}
    def get_node_metadata(name):
        return {"lat": 52.0, "lon": 19.0, "altitude": 150, "uhi_factor": 1.0}
    _TOPO_OK = False

try:
    from analyzer.timdr_analyzer import TIMDRAnalyzer
    _TIMDR_OK = True
except Exception:
    _TIMDR_OK = False

try:
    from analyzer.synoptyk_v4 import SynoptykV4
    _V4_OK = True
except Exception:
    _V4_OK = False

try:
    from forecaster.bias_correction import compute_lead_bias, apply_bias_correction
    _BIAS_OK = True
except Exception:
    _BIAS_OK = False

# Ścieżka do CSV, z którego bias_correction liczy tabelę na żywo przy
# każdym uruchomieniu - patrz forecaster/bias_correction.py po pełne
# uzasadnienie (min_samples=5 domyślnie: brak korekty dopóki dla danego
# lead_days nie ma co najmniej 5 sparowanych obserwacji prognoza/realność).
_SNAPSHOTS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "krakow_forecast_snapshots.csv")

# ── regiony ────────────────────────────────────────────────────────────────
REGIONS_MAP: dict[str, list[str]] = {
    "cała_polska": [
        "Warszawa", "Krakow_Centrum", "Gdansk", "Wroclaw", "Poznan",
        "Lodz", "Szczecin", "Katowice", "Gdynia", "Bialystok",
        "Rzeszow", "Lublin", "Olsztyn", "Zakopane",
    ],
    "poland_south": ["Krakow_Centrum", "Tarnow", "Nowy_Sacz", "Zakopane", "Katowice", "Rzeszow", "Bielsko_Biala"],
    "poland_north": ["Gdansk", "Gdynia", "Suwalki", "Olsztyn", "Elblag", "Koszalin", "Szczecin"],
    "poland_central": ["Warszawa", "Lodz", "Radom", "Plock", "Czestochowa", "Kielce"],
    "poland_west": ["Poznan", "Wroclaw", "Szczecin", "Zielona_Gora", "Gorzow_Wlkp"],
    "poland_east": ["Lublin", "Bialystok", "Zamosc", "Przemysl", "Siedlce"],
}

POLISH_CITIES = sorted(list({
    *list(TOPOGRAPHY_DATABASE.keys()),
    "Warszawa", "Krakow_Centrum", "Gdansk", "Wroclaw", "Poznan", "Lodz",
    "Szczecin", "Bydgoszcz", "Lublin", "Bialystok", "Katowice", "Gdynia",
    "Czestochowa", "Radom", "Rzeszow", "Torun", "Kielce", "Olsztyn",
    "Bielsko_Biala", "Zielona_Gora", "Opole", "Elblag", "Plock", "Tarnow",
    "Koszalin", "Kalisz", "Legnica", "Nowy_Sacz", "Siedlce", "Suwalki",
    "Zakopane", "Zamosc", "Przemysl", "Sopot", "Gorzow_Wlkp",
}))

# ── stałe Open-Meteo ────────────────────────────────────────────────────────
# NAPRAWIONE: brak "winddirection_10m" tutaj był jedną z przyczyn tego, że
# TIMDRAnalyzer.analyze(df_hist) rzucał KeyError('wind_dir') na KAŻDYM
# wywołaniu przez cały ten sesyjny okres - patrz duży komentarz przy
# run_simulation() (sekcja "── TIMDR"), gdzie opisana jest cała historia
# tego błędu i jak został znaleziony.
_OPEN_METEO_HOURLY = (
    "temperature_2m,precipitation,pressure_msl,windspeed_10m,"
    "winddirection_10m,relativehumidity_2m"
)
_OPEN_METEO_FORECAST = (
    # NAPRAWIONE: bylo "surface_pressure" (cisnienie stacyjne, bez redukcji
    # do poziomu morza), podczas gdy _OPEN_METEO_HOURLY (historia, wyzej)
    # od zawsze uzywalo "pressure_msl" (zredukowane do poziomu morza) -
    # ta niespojnosc W TYM SAMYM PLIKU dawala ~27-30 hPa systematycznej
    # roznicy wzgledem realnych pomiarow IMGW/AccuWeather dla Krakowa
    # (~220 m n.p.m., typowa korekta stacja->poziom morza to ok. 25-30 hPa -
    # zweryfikowane: 998.7 hPa (prognoza, surface_pressure) vs 1028 hPa
    # (realny pomiar, zawsze podawany jako QFF/poziom morza) dla tego
    # samego dnia i miasta). Teraz obie funkcje uzywaja pressure_msl,
    # wiec prognoza i realne pomiary sa porownywalne bez przeliczania.
    "temperature_2m,precipitation,pressure_msl,windspeed_10m,winddirection_10m"
)

# 8 kierunków, strzalka pokazuje DOKAD wieje wiatr (nie skad - to odwrotnosc
# meteorologicznego "kierunku" 0-360, ktory podaje ZRODLO wiatru). Wybrane
# bo tak intuicyjniej czyta sie pojedyncza strzalke w waskiej komorce tabeli.
_WIND_ARROWS = ["↑", "↗", "→", "↘", "↓", "↙", "←", "↖"]


# ══════════════════════════════════════════════════════════════════════════════
# helpers
# ══════════════════════════════════════════════════════════════════════════════

def _circular_mean_deg(values) -> float:
    """Srednia kierunku wiatru (stopnie 0-360) - zwykla srednia arytmetyczna
    dawalaby bledny wynik przy wartosciach blisko granicy 0/360 (np. srednia
    z 350 i 10 to fizycznie 0, nie 180). Patrz analyzer/synoptyk_v4.py,
    forecast_wind_direction() - ten sam mechanizm (srednia wektorowa)."""
    arr = np.asarray(values, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return float("nan")
    rad = np.radians(arr)
    u = np.mean(np.sin(rad))
    v = np.mean(np.cos(rad))
    return (np.degrees(np.arctan2(u, v)) + 360) % 360


def _wind_arrow(deg_from: float) -> str:
    """Zamienia kierunek meteorologiczny (skad wieje) na pojedyncza strzalke
    pokazujaca DOKAD wieje (deg_from + 180), zaokraglona do 1 z 8 kierunkow."""
    if deg_from != deg_from:  # NaN check bez importu math/np tutaj
        return "–"
    deg_to = (deg_from + 180.0) % 360.0
    idx = int(((deg_to + 22.5) % 360.0) // 45.0)
    return _WIND_ARROWS[idx]


def _get_coords(node: str) -> tuple[float, float]:
    if _TOPO_OK and node in TOPOGRAPHY_DATABASE:
        d = TOPOGRAPHY_DATABASE[node]
        return d["lat"], d["lon"]
    meta = get_node_metadata(node)
    return meta.get("lat", 52.0), meta.get("lon", 19.0)


def _fetch_historical(lat: float, lon: float, days_back: int) -> pd.DataFrame:
    """Pobiera historyczne dane godzinowe z Open-Meteo Archive API."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days_back - 1)
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        f"&hourly={_OPEN_METEO_HOURLY}"
        f"&timezone=Europe%2FWarsaw"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    j = r.json()
    h = j["hourly"]
    df = pd.DataFrame({
        "time":        pd.to_datetime(h["time"]),
        "temp":        h["temperature_2m"],
        "precip":      h["precipitation"],
        "pressure":    h["pressure_msl"],
        "wind":        h["windspeed_10m"],
        "wind_dir":    h["winddirection_10m"],
        "humidity":    h["relativehumidity_2m"],
    }).set_index("time")
    return df


def _load_csv_history_fallback(csv_path: str, station: str) -> pd.DataFrame | None:
    """Awaryjne zastępstwo dla _fetch_historical(), gdy Open-Meteo (żywe LUB
    archiwalne API) nie odpowiada - np. serwer padł, sieć padła, limit
    zapytań. Zamiast całkowicie tracić stację w tabeli, buduje "historię"
    z tego, co już jest zapisane w krakow_forecast_snapshots.csv dla tej
    stacji (Twoje wklejone pulle - prognozy własne i/lub realne obserwacje).

    To NIE jest to samo co godzinowe archiwum Open-Meteo - tu mamy najwyżej
    jeden wiersz na dzień (dobowe min/śr/max, nie 24 punkty), więc dalsze
    kroki (filtr falkowy, SynoptykV4) dostają dużo uboższy sygnał. Traktować
    jako "lepsze niż nic w razie awarii", nie jako pełnoprawny zamiennik.

    Bierze wszystkie wiersze dla stacji z target_date < dziś (żeby nie
    mieszać już-wpisanych PROGNOZ na przyszłość z historią), niezależnie od
    kolumny `source` (real/prognoza) - im więcej punktów, tym stabilniejszy
    trend, a i tak nie wiadomo z góry, co akurat będzie w CSV w chwili
    awarii. Zwraca None, jeśli zebrało się mniej niż 2 dni (SynoptykV4.forecast
    wymaga minimum 2 punktów - patrz _own_trend_points)."""
    try:
        df = pd.read_csv(csv_path, dtype={"source": str})
    except Exception:
        return None

    sub = df[df["station"] == station].copy()
    if sub.empty:
        return None

    sub["target_date"] = pd.to_datetime(sub["target_date"], errors="coerce")
    sub = sub.dropna(subset=["target_date"])
    sub = sub[sub["target_date"].dt.date < date.today()]
    if sub.empty:
        return None

    # jeśli dla tego samego dnia jest kilka pulli, bierz ostatni (najnowszy
    # zapis) - jak przy parowaniu z rzeczywistością gdzie indziej w projekcie
    sub = sub.sort_values("target_date").drop_duplicates("target_date", keep="last")
    sub = sub.set_index("target_date")

    out = pd.DataFrame({
        "temp":     sub["avg_temp_c"],
        # CSV ma już osobne dobowe min/max (w odróżnieniu od godzinowego
        # df_hist z Open-Meteo, gdzie min/max liczy się przez resample.min/
        # max na jednej kolumnie "temp") - patrz _own_trend_points, które
        # jeśli znajdzie "temp_min"/"temp_max" bezpośrednio, użyje ich
        # zamiast (bezsensownego dla już-dobowych danych) agregowania
        # pojedynczej wartości "temp" jako min/max samej siebie.
        "temp_min": sub["min_temp_c"],
        "temp_max": sub["max_temp_c"],
        "precip":   sub["precip_mm"],
        "pressure": sub["pressure_hpa"],
        "wind":     sub["wind_kmh"],
    }).dropna(subset=["temp"], how="all")

    if len(out) < 2:
        return None
    return out


_CSV_FIELDNAMES = [
    "station", "target_date", "issue_date", "pull_seq", "lead_days",
    "min_temp_c", "avg_temp_c", "max_temp_c", "precip_mm",
    "pressure_hpa", "wind_kmh", "source", "v4_point_c", "v4_lower_c", "v4_upper_c",
]

_CSV_RETENTION_DAYS = 30

_ARCHIVE_CSV_SUFFIX = "_archive.csv"  # krakow_forecast_snapshots.csv -> krakow_forecast_snapshots_archive.csv


def _archive_path_for(csv_path: str) -> str:
    base, _ext = os.path.splitext(csv_path)
    return base + _ARCHIVE_CSV_SUFFIX


def _prune_old_csv_rows(csv_path: str, keep_days: int = _CSV_RETENTION_DAYS) -> None:
    """Utrzymuje krakow_forecast_snapshots.csv w rozsądnym rozmiarze, ALE NIC
    NIE KASUJE bezpowrotnie: wiersze, których target_date jest starsza niż
    `keep_days` dni wstecz od dziś, są NAJPIERW dopisywane do pliku
    archiwalnego (`krakow_forecast_snapshots_archive.csv`, ten sam schemat
    kolumn, NIGDY nie przycinany), a dopiero potem usuwane z pliku "gorącego".
    Historia jest więc zawsze dostępna do analizy — tylko podzielona na
    "bieżący log" (mały, szybki do wczytania przy każdym uruchomieniu) i
    "archiwum" (pełna historia, osobno).

    Wywoływane po każdym automatycznym dopisie (patrz
    _autosave_forecast_to_csv), więc plik roboczy nie rośnie w nieskończoność
    przy wielu uruchomieniach GUI dziennie.

    Wyjątek: wiersze stacji `_META_` (znaczniki typu ENGINE_BASELINE_...,
    patrz README) NIE są tu ruszane w ogóle - to nie są dane pomiarowe/
    prognozy, tylko trwałe adnotacje o stanie silnika, mają obowiązywać
    niezależnie od wieku i zostają w pliku roboczym na stałe."""
    try:
        df = pd.read_csv(csv_path, dtype={"source": str})
    except Exception:
        return
    if "target_date" not in df.columns or df.empty:
        return
    td = pd.to_datetime(df["target_date"], errors="coerce")
    cutoff = pd.Timestamp(date.today() - timedelta(days=keep_days))
    # td.isna() (data nie do sparsowania) -> zostaw, nie zgadujemy czy stara
    keep_mask = (td >= cutoff) | (df["station"] == "_META_") | td.isna()
    if keep_mask.all():
        return  # nic do wyniesienia do archiwum, oszczędź zapis plików

    to_archive = df.loc[~keep_mask, _CSV_FIELDNAMES]
    if not to_archive.empty:
        try:
            archive_path = _archive_path_for(csv_path)
            file_exists = os.path.exists(archive_path)
            to_archive.to_csv(archive_path, mode="a", index=False, header=not file_exists)
        except Exception:
            # Nie udało się zarchiwizować - NIE tnij pliku roboczego, żeby
            # nie stracić danych, których nigdzie nie zdążyliśmy zapisać.
            return

    try:
        df.loc[keep_mask, _CSV_FIELDNAMES].to_csv(csv_path, index=False)
    except Exception:
        pass  # sprzątanie pliku roboczego to wygoda, nie krytyczna ścieżka


_REAL_BACKFILL_SOURCE = "OpenMeteo_real_dailymax"
_REAL_BACKFILL_LOOKBACK_DAYS = 14


def _backfill_real_observations(csv_path: str, station: str, lat: float, lon: float,
                                 lookback_days: int = _REAL_BACKFILL_LOOKBACK_DAYS) -> None:
    """Uzupełnia RZECZYWISTE obserwacje (nie prognozy) dla dni, które już
    minęły, a nie mają jeszcze żadnego wiersza source~real (IMGW_real_*/
    web_szukaj_*/OpenMeteo_real_*) w CSV — żeby bias_correction.py miał
    świeże pary (prognoza, rzeczywistość) BEZ ręcznego dopisywania, tak jak
    dotąd (te ręczne wpisy ustały 2026-08-19 — stąd ta funkcja).

    Źródło: Open-Meteo Archive API przez _fetch_historical() (już używane
    wyżej w tym pliku do historii godzinowej — ta sama, sprawdzona ścieżka
    HTTP, nie nowa zależność). Agregacja do jednego wiersza dziennego:
    `max_temp_c` = dobowe MAKSIMUM z 24 odczytów godzinowych (kolumna
    `max_temp_c`, zgodnie z konwencją reszty CSV — patrz
    forecaster/bias_correction.py, gdzie real to "pojedynczy odczyt
    punktowy"; tu to dobowe maksimum, więc bardziej spójne, nie mniej).
    `precip_mm` = suma dobowa, `pressure_hpa`/`wind_kmh` = średnia dobowa.

    source="OpenMeteo_real_dailymax" — NOWY prefiks, dopisany do
    `bias_correction._REAL_SOURCE_PREFIXES`, używany RAZEM ze starymi
    IMGW_real/web_szukaj, nie zamiast nich (stare wpisy zostają jak są).

    Wywoływane automatycznie przy każdym uruchomieniu GUI (patrz miejsce
    wywołania w run_simulation, obok _autosave_forecast_to_csv) — nie
    wymaga ręki. Failuje cicho (Open-Meteo bywa niedostępne) — to wygoda,
    nie krytyczna ścieżka; przy następnym uruchomieniu spróbuje ponownie."""
    try:
        existing = pd.read_csv(csv_path, dtype={"source": str})
    except Exception:
        existing = pd.DataFrame(columns=_CSV_FIELDNAMES)

    today = date.today()
    already_covered: set[str] = set()
    if not existing.empty and "source" in existing.columns:
        real_mask = existing["source"].astype(str).str.startswith(
            ("IMGW_real", "web_szukaj", "OpenMeteo_real"), na=False)
        covered = existing.loc[(existing["station"] == station) & real_mask, "target_date"]
        already_covered = set(covered.astype(str))

    missing_dates = [
        today - timedelta(days=back)
        for back in range(1, lookback_days + 1)
        if str(today - timedelta(days=back)) not in already_covered
    ]
    if not missing_dates:
        return  # nic do uzupełnienia - wszystkie dni w oknie już mają realny wiersz

    try:
        df_hist = _fetch_historical(lat, lon, days_back=lookback_days + 1)
    except Exception:
        return  # Open-Meteo niedostępne teraz - spróbujemy przy kolejnym uruchomieniu

    new_rows = []
    for d in missing_dates:
        day_data = df_hist[df_hist.index.date == d]
        if day_data.empty:
            continue  # archiwum jeszcze nie ma tego dnia (np. dziś, dane niepełne) - pomiń, nie zgaduj
        new_rows.append({
            "station": station, "target_date": str(d), "issue_date": "",
            "pull_seq": "", "lead_days": "", "min_temp_c": "", "avg_temp_c": "",
            "max_temp_c": round(float(day_data["temp"].max()), 1),
            "precip_mm": round(float(day_data["precip"].sum()), 1),
            "pressure_hpa": round(float(day_data["pressure"].mean()), 1),
            "wind_kmh": round(float(day_data["wind"].mean()), 1),
            "source": _REAL_BACKFILL_SOURCE,
            "v4_point_c": "", "v4_lower_c": "", "v4_upper_c": "",
        })
    if not new_rows:
        return

    try:
        file_exists = os.path.exists(csv_path)
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES)
            if not file_exists:
                w.writeheader()
            for r in new_rows:
                w.writerow(r)
    except Exception:
        return  # dopisanie realnych obserwacji to wygoda, nie krytyczna ścieżka

    _prune_old_csv_rows(csv_path)


def _autosave_forecast_to_csv(csv_path: str, station: str, issue_date_str: str, rows: list[dict]) -> None:
    """Dopisuje WŁASNĄ prognozę (dokładnie te same liczby, co trafiają do
    tabeli GUI - po korekcie UHI/falkowej/blendingu/obciążenia, PRZED
    prefiksem "▲") do krakow_forecast_snapshots.csv automatycznie, przy
    każdym uruchomieniu - bez konieczności ręcznego wklejania wyniku z GUI,
    tak jak robiło się to dotychczas. source="prognoza_blending_bias" -
    ten sam, którego już używają ręcznie wklejone pulle, więc bias_correction
    i porównania w CSV nie muszą tego rozróżniać.

    pull_seq liczony per (stacja, issue_date) jako max istniejącego + 1 -
    ta sama konwencja co przy ręcznym dopisywaniu przez całą tę sesję, więc
    kilka uruchomień GUI tego samego dnia dostaje kolejne numery, nie
    nadpisuje się nawzajem.

    Nie dotyczy wierszy ⚠️FB (fallback) ani Trybu Demo - te NIE są wywoływane
    z tą funkcją (patrz miejsce wywołania w run_simulation) - dopisywanie do
    CSV danych, które same pochodzą z CSV (fallback), byłoby kołowe."""
    if not rows:
        return
    try:
        existing = pd.read_csv(csv_path, dtype={"source": str})
        mask = (
            (existing["station"] == station)
            & (existing["issue_date"] == issue_date_str)
            & (existing["source"] == "prognoza_blending_bias")
        )
        prior_seqs = pd.to_numeric(existing.loc[mask, "pull_seq"], errors="coerce").dropna()
        pull_seq = int(prior_seqs.max()) + 1 if len(prior_seqs) else 1
    except Exception:
        pull_seq = 1

    try:
        file_exists = os.path.exists(csv_path)
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_CSV_FIELDNAMES)
            if not file_exists:
                w.writeheader()
            for r in rows:
                out_row = {k: r.get(k, "") for k in _CSV_FIELDNAMES}
                out_row["station"] = station
                out_row["issue_date"] = issue_date_str
                out_row["pull_seq"] = pull_seq
                out_row["source"] = "prognoza_blending_bias"
                w.writerow(out_row)
    except Exception:
        return  # autosave to wygoda, nie krytyczna ścieżka - nie wywalamy appki przez to

    _prune_old_csv_rows(csv_path)


def _adapt_for_timdr(df_hist: pd.DataFrame) -> pd.DataFrame:
    """Dostosowuje df_hist (indeks czasowy, kolumna 'wind') do formatu, jakiego
    oczekują TIMDRAnalyzer/WindAnalyzer (kolumna 'datetime', kolumna
    'wind_speed') - to jest DOKŁADNIE format zwracany przez oryginalny
    data/fetcher.py:WeatherFetcher.fetch_hourly(), dla którego te klasy
    zostały napisane. _fetch_historical() (wyżej) to NIEZALEŻNA, równoległa
    implementacja pobierania historii - ma inny schemat kolumn, i przez całą
    tę sesję nikt tego nie zauważył, bo wywołanie analyzer.analyze(df_hist)
    w run_simulation() było owinięte w "except Exception: pass" (patrz
    historia w komentarzu przy tym wywołaniu) - efekt: TIMDRAnalyzer rzucał
    KeyError('wind_dir') na KAŻDYM uruchomieniu, cicho połykany, więc cały
    system sygnałów ⚡anomalia/defekt/rezonans nigdy faktycznie nie zadziałał
    w GUI, mimo że wyglądało jakby "analiza po prostu nic nie znalazła"."""
    out = df_hist.reset_index().rename(columns={
        df_hist.index.name or "index": "datetime",
        "wind": "wind_speed",
    })
    return out


def _fetch_forecast(lat: float, lon: float, days_ahead: int) -> pd.DataFrame:
    """Pobiera prognozę godzinową z Open-Meteo Forecast API (maks. 16 dni)."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly={_OPEN_METEO_FORECAST}"
        f"&forecast_days={min(days_ahead, 16)}"
        f"&timezone=Europe%2FWarsaw"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    j = r.json()
    h = j["hourly"]
    df = pd.DataFrame({
        "time":     pd.to_datetime(h["time"]),
        "temp":     h["temperature_2m"],
        "precip":   h["precipitation"],
        "pressure": h["pressure_msl"],
        "wind":     h["windspeed_10m"],
        "wind_dir": h["winddirection_10m"],
    }).set_index("time")
    return df


def _daily_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Resample godzinowy → dzienny (min/avg/max). Kierunek wiatru agregowany
    srednia wektorowa (_circular_mean_deg), nie zwykla srednia - patrz jej
    docstring."""
    agg = df.resample("1D").agg({
        "temp":     ["min", "mean", "max"],
        "precip":   "sum",
        "pressure": "mean",
        "wind":     "max",
        "wind_dir": _circular_mean_deg,
    })
    agg.columns = [
        "temp_min", "temp_avg", "temp_max",
        "precip_sum", "pressure_avg", "wind_max", "wind_dir_avg",
    ]
    return agg.round(1)


def _uhi_lapse(val: float, uhi: float, alt: int, col: str) -> float:
    """Korekta UHI i gradient wysokości – tylko dla temperatury."""
    if col.startswith("temp"):
        lapse = (alt / 100.0) * 0.65
        return round(val + uhi - lapse, 1)
    return val


def _own_trend_points(df_hist: pd.DataFrame, col: str, how: str, steps_ahead: int) -> np.ndarray | None:
    """Własna, w pełni deterministyczna ekstrapolacja trendu (SynoptykV4.forecast)
    na dziennie zagregowanej serii z REALNEJ historii (nie z modelu Open-Meteo).

    Po co: uruchomiona dwa razy tego samego dnia na tych samych danych
    historycznych zawsze da identyczny wynik — w odróżnieniu od
    _fetch_forecast(), które odpytuje live Open-Meteo i może zwrócić inne
    wartości za każdym razem, bo dostawca sam przelicza swój model NWP
    kilka razy dziennie (patrz _blend_weight niżej i komentarz w
    run_simulation przy `w = _blend_weight(...)`).

    how: "mean" | "min" | "max" | "sum" — jak agregować godzinowe dane do
    dziennych przed ekstrapolacją (żeby np. dla temp_min ekstrapolować trend
    samych dobowych minimów, nie średnich; "sum" dla opadu - suma dobowa,
    nie średnia z godzinowych stawek, inaczej wynik nie ma sensu fizycznego).
    """
    if not _V4_OK or df_hist is None:
        return None
    # Fallback z CSV (_load_csv_history_fallback) daje już GOTOWE dobowe
    # min/max jako osobne kolumny ("temp_min"/"temp_max"), bo tam nie ma
    # godzinowych danych do samodzielnego agregowania - resample().min()
    # na jednej już-dobowej wartości "temp" zwróciłoby tylko tę samą
    # wartość dla min i max. Jeśli taka kolumna istnieje, użyj jej wprost
    # (resample("1D").mean() jest tu bezpiecznym przepustem dla pojedynczej
    # wartości na dzień, nie realną agregacją).
    direct_col = f"{col}_{how}"
    if direct_col in df_hist.columns:
        s = df_hist[direct_col].dropna()
        daily = s.resample("1D").mean().dropna()
    elif col in df_hist.columns:
        s = df_hist[col].dropna()
        if how == "min":
            daily = s.resample("1D").min().dropna()
        elif how == "max":
            daily = s.resample("1D").max().dropna()
        elif how == "sum":
            daily = s.resample("1D").sum().dropna()
        else:
            daily = s.resample("1D").mean().dropna()
    else:
        return None
    if len(daily) < 2:
        return None
    try:
        t_hist = np.arange(len(daily), dtype=float)
        s_hist = daily.to_numpy(dtype=float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            # k_neighbors=5: patrz wyjaśnienie przy istniejącym v4_forecast
            # w run_simulation — to samo uzasadnienie dotyczy tutaj.
            fc = SynoptykV4(k_neighbors=5).forecast(
                t_hist, s_hist, steps_ahead=steps_ahead, damping=0.85,
            )
        return np.asarray(fc["point"], dtype=float)
    except Exception:
        return None


def _blend_weight(lead_days: int) -> float:
    """Waga własnej ekstrapolacji trendu w mieszance z live-prognozą Open-Meteo.

    0.0 dla dni 0-2 (pełne zaufanie do świeżej prognozy modelu — na krótkim
    horyzoncie ona i tak jest trafniejsza niż prosta ekstrapolacja trendu),
    rośnie liniowo do 1.0 przy +10d i dalej.

    Uzasadnienie: dla dalekiego horyzontu (+4d..+13d) Open-Meteo samo w
    sobie potrafi mocno zmienić prognozę między dwoma pobraniami zrobionymi
    tego samego dnia (własny model NWP dostawcy przelicza się kilka razy
    dziennie) — zaobserwowane empirycznie w krakow_forecast_snapshots.csv
    (patrz pull_seq 2 vs 3 dla issue_date=2026-08-16: +4d..+9d skoczyło o
    2-5°C, opad jutra 12.1mm→33.3mm, w ciągu tego samego dnia). Własna
    ekstrapolacja trendu (SynoptykV4, patrz _own_trend_points) jest
    deterministyczna względem tej samej historii, więc mieszanie w nią
    tłumi tę niestabilność kosztem części "świeżości" modelu na dalekim
    horyzoncie, gdzie i tak jego skuteczność jest ograniczona.

    Nie dotyczy opadów — trend liniowy z historii opadów nie ma sensu dla
    zjawiska tak progowego/skokowego jak opad; ta kolumna zostaje czystym
    przepuszczeniem z API bez mieszania.
    """
    return max(0.0, min(1.0, (lead_days - 2) / 8.0))


# Pamięć ostatniego pulla per (stacja, data docelowa).
# NAPRAWIONE: pierwotnie zwykły dict w pamięci procesu — restart serwera
# (Ctrl+C + ponowne `python gui_app.py`, albo po prostu zamknięcie okna
# terminala między sprawdzeniami w ciągu dnia) czyścił go do zera, więc
# _LAST_PULL nigdy nie miał z czym porównać pierwszego pulla po restarcie
# i ⚡EV milczał, dopóki nie zrobiono dwóch pulli bez zamykania appki
# między nimi — w praktyce prawie nigdy. Teraz zapisywany na dysk (mały
# plik JSON obok gui_app.py) i wczytywany przy starcie modułu, więc
# przetrwa restart. To NIE jest baza danych — jeśli plik zniknie/uszkodzi
# się, po prostu zaczyna się od pustej pamięci (fail-safe, nie fail-loud).
_LAST_PULL_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_last_pull_cache.json")


def _load_last_pull_cache() -> dict[tuple[str, str], dict]:
    try:
        with open(_LAST_PULL_CACHE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {tuple(k.split("|", 1)): v for k, v in raw.items()}
    except Exception:
        return {}


def _save_last_pull_cache(cache: dict[tuple[str, str], dict]) -> None:
    try:
        raw = {f"{k[0]}|{k[1]}": v for k, v in cache.items()}
        with open(_LAST_PULL_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(raw, f)
    except Exception:
        pass  # cache to wygoda, nie krytyczna sciezka - nie wywalamy appki przez to


_LAST_PULL: dict[tuple[str, str], dict] = _load_last_pull_cache()


def clear_last_pull_cache() -> str:
    """Ręczne czyszczenie pamięci ⚡EV (nie dotyka krakow_forecast_snapshots.csv
    ani bias_correction - to osobna, celowo trwała historia). Przydatne gdy
    plik zebrał stare wpisy z innych stacji/trybów/testów, które nie są już
    istotne - kolejny pull po czyszczeniu nie będzie miał z czym porównać,
    więc ⚡EV zacznie znów działać dopiero od pulla PO NASTĘPNYM."""
    _LAST_PULL.clear()
    try:
        if os.path.exists(_LAST_PULL_CACHE_PATH):
            os.remove(_LAST_PULL_CACHE_PATH)
        removed = True
    except Exception:
        removed = False
    return (
        "🔄 Cache EV (_last_pull_cache.json) wyczyszczony."
        if removed else
        "🔄 Pamięć EV wyczyszczona w procesie, ale nie udało się usunąć pliku na dysku "
        "(sprawdź uprawnienia) - zostanie nadpisany przy następnym uruchomieniu."
    )


_BIAS_BADGE_SOLID_N = 15  # próg "solidnej" próbki - patrz _bias_badge() niżej


def _bias_badge(lead_days: int, bias_table: dict, solid_n: int = _BIAS_BADGE_SOLID_N) -> str:
    """Kolorowy znaczek statusu korekty obciążenia dla danego lead_days:
      🔴 czerwony    - korekta jeszcze niedostępna (lead_days spoza bias_table,
                        czyli < min_samples sparowanych obserwacji - patrz
                        forecaster/bias_correction.py)
      🟠 pomarańczowy - korekta aktywna, ale na małej próbce (min_samples..solid_n-1)
                        - traktuj jako orientacyjną, nie w pełni wiarygodną
      🟢 zielony      - korekta aktywna, na solidniejszej próbce (>= solid_n)

    Próg solid_n=15 jest heurystyczny (nie ma tu formalnego testu istotności
    statystycznej) - wybrany na oko jako "ponad dwa tygodnie codziennych
    pulli", nie coś wyliczonego z rozkładu błędu. Kolorowe kółka to zwykłe
    znaki Unicode (nie wymagają HTML/CSS w tabeli Gradio), więc działają
    identycznie w gr.Dataframe jak zwykły tekst.
    """
    entry = bias_table.get(int(lead_days))
    if entry is None:
        return "🔴"
    return "🟢" if entry["n"] >= solid_n else "🟠"


def detect_engine_volatility(prev_row: dict, new_row: dict) -> dict:
    """Wykrywa skok głównego silnika między poprzednim a bieżącym pullem dla
    tego samego dnia docelowego. Progi dobrane pod skoki widziane w
    krakow_forecast_snapshots.csv (np. +4d..+9d o 2-5°C, opad jutra
    12.1mm→33.3mm w ciągu tej samej doby, przed wdrożeniem blendingu)."""
    flags = {}
    # .get() + _diff() zamiast bezpośredniego indeksowania: stary
    # _last_pull_cache.json sprzed skrócenia nagłówków (patrz NAPRAWIONE przy
    # column_widths niżej) miał inne klucze - brakujący klucz ma po prostu
    # nie wywoływać skoku (nie crashować KeyError na pierwszym uruchomieniu
    # po zmianie nazw).
    def _diff(key: str) -> float | None:
        a, b = prev_row.get(key), new_row.get(key)
        return abs(a - b) if a is not None and b is not None else None

    checks = [
        ("Śr °C", 2.0, "temp_jump"),
        ("Opad mm", 10.0, "precip_jump"),
        ("Ciśn hPa", 5.0, "pressure_jump"),
        ("Wiatr km/h", 8.0, "wind_jump"),
    ]
    for key, threshold, flag_name in checks:
        d = _diff(key)
        if d is not None and d > threshold:
            flags[flag_name] = True
    return flags


# ══════════════════════════════════════════════════════════════════════════════
# główna funkcja backendu
# ══════════════════════════════════════════════════════════════════════════════

def run_simulation(
    mode: str,
    selected_region: str,
    selected_city: str,
    selected_cities: list[str] | None,
    history_days: int,
    forecast_days: int,
    offline_demo: bool,
) -> tuple[str, pd.DataFrame, str]:

    logs: list[str] = []
    rows: list[dict] = []

    # DODANE: trzeci tryb "Wybór miast" - dowolna kombinacja miast z listy,
    # nie ograniczona do sztywnego podziału na regiony w REGIONS_MAP (np.
    # Kraków + Gdańsk + Warszawa naraz, bez wspólnego regionu). Pusty wybór
    # (użytkownik odznaczył wszystko) -> fallback na Kraków, żeby przycisk
    # "Uruchom" nigdy nie zwracał pustej tabeli bez wyjaśnienia dlaczego.
    if mode == "Pojedyncze miasto":
        nodes = [selected_city]
    elif mode == "Wybór miast":
        nodes = list(selected_cities) if selected_cities else ["Krakow_Centrum"]
        if not selected_cities:
            logs.append("⚠️  Nie wybrano żadnego miasta - użyto domyślnego (Krakow_Centrum).")
    else:
        nodes = REGIONS_MAP.get(selected_region.lower(), REGIONS_MAP["poland_south"])

    if mode == "Pojedyncze miasto":
        scope_label = "Miasto: " + selected_city
    elif mode == "Wybór miast":
        scope_label = "Miasta: " + ", ".join(nodes)
    else:
        scope_label = "Region: " + selected_region.upper()

    logs.append(
        f"{scope_label} | Historia: {history_days}d | Prognoza: {forecast_days}d | Stacji: {len(nodes)}"
    )

    engine = SynoptykFEngine(wavelet="db4") if _SF_OK else None

    for node in nodes:
        lat, lon = _get_coords(node)
        meta = get_node_metadata(node)
        uhi   = meta.get("uhi_factor", 1.0)
        alt   = meta.get("altitude", 150)

        # ── korekta obciążenia (self-learning z historii CSV) ───────────────
        # Patrz forecaster/bias_correction.py: NIE jest to model ML, tylko
        # sredni blad prognoza-vs-rzeczywistosc liczony na zywo per lead_days.
        # Kod SAM raportuje, dla ilu lead_days ma wystarczajaco probek -
        # zeby bylo widac w Dzienniku, czy korekta w ogole dziala, a nie
        # zeby cicho cos poprawiala bez informacji z ilu danych to wynika.
        bias_table: dict = {}
        if _BIAS_OK:
            bias_table = compute_lead_bias(_SNAPSHOTS_CSV, station=node, min_samples=5)
            if bias_table:
                summary = ", ".join(
                    f"+{lead}d(n={e['n']},{e['bias']:+.1f}°C)"
                    for lead, e in sorted(bias_table.items())
                )
                logs.append(f"🎯 {node}: korekta obciążenia aktywna dla: {summary}")
            else:
                logs.append(f"🎯 {node}: korekta obciążenia jeszcze nieaktywna (za mało sparowanych pulli w CSV, próg 5/lead_days)")

        if offline_demo:
            today = date.today()
            for d in range(forecast_days):
                day = today + timedelta(days=d)
                rows.append({
                    "Stacja": node, "Data": str(day), "Typ": "DEMO",
                    "Min °C": "–", "Śr °C": "–", "Max °C": "–",
                    "Opad mm": "–", "Ciśn hPa": "–", "Wiatr km/h": "–",
                    "Kier.": "–", "V4 °C": "–",
                })
            continue

        # ── historia (do trendu falkowego) ─────────────────────────────────
        df_hist = None
        data_end_str = "brak danych"
        try:
            df_hist = _fetch_historical(lat, lon, history_days)
            data_end = df_hist.index[-1].date()
            data_end_str = str(data_end)
            age_days = (date.today() - data_end).days
            if age_days > 2:
                logs.append(f"⚠️  {node}: ostatnie dane historyczne z {data_end_str} ({age_days}d temu)!")
        except Exception as e:
            # Open-Meteo (archive-api) nie odpowiada - próba fallbacku z
            # krakow_forecast_snapshots.csv zamiast od razu tracić stację.
            # Patrz _load_csv_history_fallback() po uzasadnienie i ograniczenia.
            logs.append(f"⚠️  {node}: błąd pobierania historii z Open-Meteo ({e}) - próbuję fallbacku z CSV")
            df_hist = _load_csv_history_fallback(_SNAPSHOTS_CSV, node)
            if df_hist is not None:
                data_end = df_hist.index[-1].date()
                data_end_str = f"{data_end} (fallback CSV)"
                logs.append(f"✓  {node}: fallback z CSV aktywny ({len(df_hist)} dni z wklejonych pulli)")
            else:
                logs.append(f"✗  {node}: brak wystarczających danych w CSV do fallbacku (min. 2 dni)")

        # ── TIMDR (opcjonalnie) ─────────────────────────────────────────────
        # NAPRAWIONE: analyzer.analyze(df_hist) rzucał KeyError('wind_dir')
        # (potem, po dodaniu wind_dir, złapałby kolejno 'wind_speed' i
        # 'datetime' - TIMDRAnalyzer/WindAnalyzer oczekują schematu kolumn
        # z data/fetcher.py:WeatherFetcher, nie tego z _fetch_historical()
        # powyżej) - patrz _adapt_for_timdr(). Błąd był NIEWIDOCZNY całą tę
        # sesję, bo "except Exception: pass" cicho go łykał - kod tak samo
        # "działał", tabela tak samo się wypełniała, tylko sygnały
        # ⚡anomalia/defekt/rezonans nigdy się nie zapalały, bo w
        # rzeczywistości analiza nigdy się nie wykonywała. Teraz błąd trafia
        # do Dziennika zamiast znikać po cichu - żeby taki regres nie mógł
        # się już ukryć bez śladu.
        timdr_results: dict = {}
        if _TIMDR_OK and df_hist is not None:
            try:
                analyzer = TIMDRAnalyzer(station=node)
                timdr_results = analyzer.analyze(_adapt_for_timdr(df_hist))
            except Exception as e:
                logs.append(f"⚠️  {node}: błąd analizy TIMDR (sygnały ⚡): {e}")

        # ── korekta falkowa bazowa temperatury ─────────────────────────────
        base_correction = 0.0
        if engine is not None and df_hist is not None:
            try:
                temp_arr = df_hist["temp"].dropna().to_numpy(dtype=float)
                if len(temp_arr) >= 8:
                    denoised = engine.filter_signal(temp_arr)
                    raw_last = float(temp_arr[-1])
                    den_last = float(denoised[-1])
                    base_correction = den_last - raw_last   # δ do zastosowania na prognozie
            except Exception:
                pass

        # ── SynoptykV4: rownolegly silnik prognozy (ekstrapolacja trendu z
        # rzeczywistej historii, NIE z modelu Open-Meteo) - dodany do
        # porownania obok istniejacego silnika (Open-Meteo + korekta
        # falkowa/UHI). Nie zastepuje niczego - liczony jest tylko dodatkowo,
        # zeby mozna bylo obserwowac przez kilka dni, ktory jest blizej
        # rzeczywistych pomiarow, zanim cokolwiek zostanie podmienione
        # na stale jako domyslny. Uzywa dziennej sredniej z tej samej
        # historii co korekta falkowa powyzej - BEZ dodatkowej korekty
        # UHI/lapse rate, bo te efekty sa juz obecne w realnych pomiarach
        # historycznych (w odroznieniu od prognozy modelu siatkowego
        # Open-Meteo, ktora ich nie uwzglednia i dlatego wymaga korekty).
        v4_forecast = None
        if _V4_OK and df_hist is not None:
            try:
                daily_hist = df_hist["temp"].dropna().resample("1D").mean().dropna()
                if len(daily_hist) >= 2:
                    t_hist = np.arange(len(daily_hist), dtype=float)
                    s_hist = daily_hist.to_numpy(dtype=float)
                    # k_neighbors=5: przy domyslnym suwaku "Historia" (7 dni)
                    # resampled do dziennych wartosci daje n=7 punktow - z
                    # k_neighbors=8 (domyslny w SynoptykV4) kazde wywolanie
                    # odpalaloby RuntimeWarning o degeneracji do global-fit
                    # (patrz analyzer/synoptyk_v4.py, "Znane ograniczenia").
                    # Dla n~7 dziennych probek globalny trend i tak jest
                    # najbardziej sensowna interpretacja (nie ma tu miejsca
                    # na "lokalna" analize w skali podobowej), wiec k=5 tylko
                    # wycisza szum ostrzezen bez zmiany sensu wyniku - dla
                    # dluzszej historii (suwak >5 dni) nadal daje lokalnosc.
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        v4_forecast = SynoptykV4(k_neighbors=5).forecast(
                            t_hist, s_hist, steps_ahead=forecast_days, damping=0.85,
                        )
            except Exception:
                pass

        # ── własna ekstrapolacja trendu dla pozostałych parametrów ─────────
        # (temp_avg już mamy z v4_forecast powyżej — reużywamy go zamiast
        # liczyć drugi raz to samo). Patrz _own_trend_points/_blend_weight
        # wyżej po pełne uzasadnienie i skąd wzięła się potrzeba tego.
        own_temp_avg = np.asarray(v4_forecast["point"], dtype=float) if v4_forecast is not None else None
        own_temp_min = _own_trend_points(df_hist, "temp", "min", forecast_days)
        own_temp_max = _own_trend_points(df_hist, "temp", "max", forecast_days)
        own_pressure = _own_trend_points(df_hist, "pressure", "mean", forecast_days)
        own_wind     = _own_trend_points(df_hist, "wind", "max", forecast_days)
        # DODANE: tylko na wypadek awarii Open-Meteo (patrz blok "PAD SERWERA"
        # niżej) - w normalnym mieszaniu opad celowo NIE dostaje własnego
        # trendu (patrz _blend_weight: "nie dotyczy opadów"), bo trend liniowy
        # nie pasuje do zjawiska progowego. Tu to ostatnia deska ratunku, więc
        # lepsze przybliżenie niż całkowity brak wiersza.
        own_precip   = _own_trend_points(df_hist, "precip", "sum", forecast_days)

        # DODANE: surowe (bez prefiksu "▲", przed formatowaniem na tekst)
        # wartości tego pulla - do automatycznego dopisu do
        # krakow_forecast_snapshots.csv na końcu pętli dni (patrz
        # _autosave_forecast_to_csv niżej). Osobna lista od `rows` (które
        # idą do tabeli GUI jako sformatowany tekst) - łatwiej trzymać
        # czyste liczby niż odklejać "▲" z powrotem.
        own_pull_rows: list[dict] = []

        # ── prognoza Open-Meteo ─────────────────────────────────────────────
        try:
            df_fc = _fetch_forecast(lat, lon, forecast_days)
            daily = _daily_stats(df_fc)
        except Exception as e:
            # PAD SERWERA: żywe Open-Meteo Forecast API nie odpowiada. Zamiast
            # tracić całą stację (jak wcześniej - "✗ błąd prognozy", zero
            # wierszy), budujemy wiersze z tego, co już policzone wyżej z
            # REALNEJ historii (own_temp_*/own_pressure/own_wind/own_precip -
            # z krakow_forecast_snapshots.csv, jeśli i żywe archiwum też padło,
            # patrz _load_csv_history_fallback). Wyraźnie oznaczone w "Typ",
            # bez korekty obciążenia/EV/▲ - te mechanizmy porównują się do
            # normalnych pulli z API, więc nie mają tu sensownego punktu
            # odniesienia.
            logs.append(f"✗  {node}: błąd prognozy z Open-Meteo ({e}) - próbuję fallbacku z realnej historii")
            if own_temp_avg is None:
                logs.append(f"✗  {node}: brak danych do fallbacku (za mało historii) - stacja pominięta")
                continue
            today = date.today()
            n = forecast_days
            for day_idx in range(n):
                day_label = today + timedelta(days=day_idx)
                day_text = "Dziś" if day_idx == 0 else f"{day_idx + 1}d"
                t_avg = round(float(own_temp_avg[day_idx]), 1) if day_idx < len(own_temp_avg) else None
                t_min = round(float(own_temp_min[day_idx]), 1) if own_temp_min is not None and day_idx < len(own_temp_min) else t_avg
                t_max = round(float(own_temp_max[day_idx]), 1) if own_temp_max is not None and day_idx < len(own_temp_max) else t_avg
                press = round(float(own_pressure[day_idx]), 1) if own_pressure is not None and day_idx < len(own_pressure) else None
                wind  = round(float(own_wind[day_idx]), 1) if own_wind is not None and day_idx < len(own_wind) else None
                precip = round(max(0.0, float(own_precip[day_idx])), 1) if own_precip is not None and day_idx < len(own_precip) else None
                v4_str = "–"
                if v4_forecast is not None and day_idx < len(v4_forecast["point"]):
                    v4_point = round(float(v4_forecast["point"][day_idx]), 1)
                    v4_lower = round(float(v4_forecast["lower"][day_idx]), 1)
                    v4_upper = round(float(v4_forecast["upper"][day_idx]), 1)
                    v4_str = f"{v4_point} [{v4_lower}–{v4_upper}]"
                def _na(v):
                    return "–" if v is None else v
                rows.append({
                    "Stacja":   node,
                    "Data":     str(day_label),
                    "Typ":      f"⚠️FB {day_text}",
                    "Min °C":   _na(t_min),
                    "Śr °C":    _na(t_avg),
                    "Max °C":   _na(t_max),
                    "Opad mm":  _na(precip),
                    "Ciśn hPa": _na(press),
                    "Wiatr km/h": _na(wind),
                    "Kier.":    "–",
                    "Hist. do": data_end_str,
                    "V4 °C":    v4_str,
                })
            logs.append(f"⚠️  {node}: {n} wierszy z fallbacku (⚠️FB w kolumnie Typ) - to NIE jest świeża prognoza Open-Meteo")
            continue

        try:
            for day_idx, (day_dt, row_s) in enumerate(daily.iterrows()):
                day_label = day_dt.date()
                # napis "Dziś / 2d / 3d / ... / 14d"
                # ZMIENIONE: "Jutro" i "+Nd" (kończące się na "+13d" przy
                # 14-dniowej prognozie) zastąpione ciągłym numerowaniem dnia
                # (delta+1) - użytkownik nie chciał kończyć na "13". Gołe
                # liczby bez jednostki ("2", "3"...) wyglądały niejasno obok
                # daty w sąsiedniej kolumnie "Data" - dopisane "d" (dzień),
                # bez "+" z przodu. "Dziś" zostaje bez zmian (jedyny
                # opisowy, nie numeryczny dzień).
                delta = (day_label - date.today()).days
                if delta == 0:
                    day_text = "Dziś"
                else:
                    day_text = f"{delta + 1}d"

                # korekta UHI + lapse rate + falkowa
                # NAPRAWIONE: zaokrąglamy CAŁĄ sumę (nie tylko base_correction),
                # inaczej szum zmiennoprzecinkowy z _uhi_lapse zostaje w wyniku
                # (np. "18.400000000000002" zamiast "18.4"). To samo dla
                # opadów/ciśnienia/wiatru — wcześniej w ogóle nie zaokrąglane.
                t_min  = round(_uhi_lapse(row_s["temp_min"],  uhi, alt, "temp") + base_correction, 1)
                t_avg  = round(_uhi_lapse(row_s["temp_avg"],  uhi, alt, "temp") + base_correction, 1)
                t_max  = round(_uhi_lapse(row_s["temp_max"],  uhi, alt, "temp") + base_correction, 1)
                precip = round(row_s["precip_sum"], 1)
                press  = round(row_s["pressure_avg"], 1)
                wind   = round(row_s["wind_max"], 1)
                wind_arrow = _wind_arrow(row_s.get("wind_dir_avg", float("nan")))

                # ── stabilizacja dalekiego horyzontu własną ekstrapolacją ──
                # (patrz _blend_weight: nie dotyczy opadów, ani dni 0-2)
                w = _blend_weight(day_idx)
                if w > 0.0:
                    if own_temp_min is not None and day_idx < len(own_temp_min):
                        t_min = round((1 - w) * t_min + w * float(own_temp_min[day_idx]), 1)
                    if own_temp_avg is not None and day_idx < len(own_temp_avg):
                        t_avg = round((1 - w) * t_avg + w * float(own_temp_avg[day_idx]), 1)
                    if own_temp_max is not None and day_idx < len(own_temp_max):
                        t_max = round((1 - w) * t_max + w * float(own_temp_max[day_idx]), 1)
                    if own_pressure is not None and day_idx < len(own_pressure):
                        press = round((1 - w) * press + w * float(own_pressure[day_idx]), 1)
                    if own_wind is not None and day_idx < len(own_wind):
                        wind = round((1 - w) * wind + w * float(own_wind[day_idx]), 1)

                # ── korekta obciążenia z historii (patrz log wyżej) ────────
                # Kolorowy znaczek zamiast płaskiego 🎯 - patrz _bias_badge()
                # niżej po progi i uzasadnienie. Doklejany do KAŻDEGO dnia
                # (nie tylko aktywnych), żeby czerwony "jeszcze niedostępne"
                # było widoczne wprost, a nie domyślne przez brak znaczka.
                # NAPRAWIONE: znaczek na PIERWSZYM miejscu, dzień docelowy po
                # nim (nie odwrotnie) - kółka stoją w jednej kolumnie po
                # lewej krawędzi komórki niezależnie od długości "Dziś" vs
                # "+13d", więc łatwiej je od razu wyłapać wzrokiem w dół tabeli.
                if day_idx in bias_table:
                    t_avg = apply_bias_correction(t_avg, day_idx, bias_table)
                typ = f"{_bias_badge(day_idx, bias_table)} {day_text}"

                # sygnały TIMDR - USUNIĘTE z kolumny "Typ" (był tam "⚡",
                # wcześniej "⚡ano·def"/"⚡ano·def·rez"). Przez czułość progu
                # opadu (patrz "Znane ograniczenia" w README) sygnał
                # praktycznie zawsze jest aktywny - w tabeli nie odróżniał
                # więc nic od niczego, tylko zajmował miejsce. `timdr_results`
                # jest nadal liczone (patrz wyżej) - gdyby ktoś chciał to
                # z powrotem, wystarczy dociągnąć znów do `typ`.

                # ── EV: skok głównego silnika względem poprzedniego pulla ──
                # DODANE: wydzielone z "Typ" do osobnej kolumny "EV" - "Typ"
                # zbierał już znaczek korekty + dzień + sygnały TIMDR (prawie
                # zawsze aktywne, patrz czułość progu opadu) + EV (rzadki,
                # najbardziej istotny sygnał) w jednym stłoczonym polu, przez
                # co EV ginęło wzrokiem w gąszczu tekstu. Osobna kolumna =
                # łatwe skanowanie w dół, w którym wierszu coś skoczyło.
                current_vals = {
                    "Śr °C": t_avg, "Opad mm": precip,
                    "Ciśn hPa": press, "Wiatr km/h": wind,
                    # DODANE: Min/Max dołączone tylko do porównania "co się
                    # zmieniło" (niżej) - detect_engine_volatility() czyta
                    # jawnie nazwane klucze (patrz jej definicja), więc te
                    # dwa dodatkowe nie wpływają na progi/logikę EV.
                    "Min °C": t_min, "Max °C": t_max,
                }
                pull_key = (node, str(day_label))
                prev_vals = _LAST_PULL.get(pull_key)
                ev_flag = "⚡EV" if (
                    prev_vals is not None and detect_engine_volatility(prev_vals, current_vals)
                ) else "–"

                # DODANE: wizualne odróżnienie "faktycznie nowa wartość w tym
                # pullu" od "identyczna jak poprzednio" - użytkownik zgłosił,
                # że kilka pulli z rzędu (nawet po restarcie serwera) dało
                # bajt-identyczne wyniki i za każdym razem musiał wklejać tu,
                # żeby to sprawdzić. Wartość, która zmieniła się względem
                # _LAST_PULL dla tego (stacja, dzień), dostaje prefiks "▲";
                # niezmieniona zostaje zwykłym tekstem. Pierwszy pull dla
                # danego dnia (brak wpisu w cache) liczy się jako
                # "zmienione" - nie ma z czym porównać.
                # NAPRAWIONE x2: dwie pierwsze wersje próbowały pokolorować
                # wartość przez <span> z datatype="markdown" (escapowane -
                # użytkownik widział dosłowny tekst tagu), potem
                # datatype="html" (dalej nic - Gradio widocznie i tak
                # oczyszcza/ignoruje class/style w tej ścieżce, albo scoped
                # CSS Svelte nie przebija się do wstrzykiwanej treści -
                # nieudokumentowane, nie warto dalej zgadywać). Zwykły znak
                # w zwykłym tekście (datatype="str", tak jak ⚡EV/🔴🟠🟢,
                # które już DZIAŁAJĄ w tej samej tabeli) nie zależy od
                # żadnego renderowania HTML, więc gwarantowanie się pokaże.
                def _mark(key: str, value) -> str:
                    changed = prev_vals is None or prev_vals.get(key) != current_vals.get(key)
                    # str(27.0) -> "27.0" (Python zawsze dodaje ".0" dla
                    # całkowitych floatów) - {:g} usuwa zbędne zero, żeby
                    # wygladało tak jak przed tą zmianą ("27" nie "27.0").
                    s = f"{value:g}" if isinstance(value, float) else str(value)
                    return f"▲{s}" if changed else s

                _LAST_PULL[pull_key] = current_vals

                # SynoptykV4 - rownolegly punkt + pasmo (patrz komentarz wyzej)
                v4_str = "–"
                if v4_forecast is not None and day_idx < len(v4_forecast["point"]):
                    v4_point = round(float(v4_forecast["point"][day_idx]), 1)
                    v4_lower = round(float(v4_forecast["lower"][day_idx]), 1)
                    v4_upper = round(float(v4_forecast["upper"][day_idx]), 1)
                    v4_str = f"{v4_point} [{v4_lower}–{v4_upper}]"

                # ZMIENIONE: osobna kolumna "EV" zwinięta z powrotem do
                # "Stacja" - użytkownik chciał ją tam, wyrównaną do prawej
                # strony komórki (patrz text-align:right na .stacja-cell w
                # CSS niżej), zamiast osobnej kolumny zajmującej miejsce.
                stacja_str = f"{node} ⚡EV" if ev_flag == "⚡EV" else node

                rows.append({
                    "Stacja":   stacja_str,
                    "Data":     str(day_label),
                    "Typ":      typ,
                    "Min °C":   _mark("Min °C", t_min),
                    "Śr °C":    _mark("Śr °C", t_avg),
                    "Max °C":   _mark("Max °C", t_max),
                    "Opad mm":  _mark("Opad mm", precip),
                    "Ciśn hPa": _mark("Ciśn hPa", press),
                    "Wiatr km/h": _mark("Wiatr km/h", wind),
                    "Kier.":    wind_arrow,
                    "Hist. do": data_end_str,
                    "V4 °C":    v4_str,
                })

                own_pull_rows.append({
                    "target_date": str(day_label),
                    "lead_days": day_idx,
                    "min_temp_c": t_min, "avg_temp_c": t_avg, "max_temp_c": t_max,
                    "precip_mm": precip, "pressure_hpa": press, "wind_kmh": wind,
                    "v4_point_c": v4_point if v4_forecast is not None and day_idx < len(v4_forecast["point"]) else "",
                    "v4_lower_c": v4_lower if v4_forecast is not None and day_idx < len(v4_forecast["point"]) else "",
                    "v4_upper_c": v4_upper if v4_forecast is not None and day_idx < len(v4_forecast["point"]) else "",
                })

            # DODANE: automatyczny zapis tego pulla do CSV - patrz
            # _autosave_forecast_to_csv() po pełne uzasadnienie. Tylko dla
            # normalnej ścieżki (żywe Open-Meteo) - fallback ⚠️FB i Tryb Demo
            # nie wywołują tego (fallback sam pochodzi z CSV, dopisywanie
            # byłoby kołowe; Demo to gołe "–", nic sensownego do zapisania).
            _autosave_forecast_to_csv(_SNAPSHOTS_CSV, node, str(date.today()), own_pull_rows)

            # DODANE: automatyczne uzupełnienie RZECZYWISTYCH obserwacji za
            # dni, które już minęły (patrz _backfill_real_observations() po
            # pełne uzasadnienie - ręczne wpisy IMGW_real_*/web_szukaj_*
            # ustały 2026-08-19, bias_correction.py przestał dostawać nowe
            # pary do porównania). Ta sama ścieżka HTTP co _fetch_historical
            # wyżej, więc nic nowego sieciowo - tylko dopisanie brakujących
            # dni jako osobny wiersz per stacja.
            _backfill_real_observations(_SNAPSHOTS_CSV, node, lat, lon)

        except Exception as e:
            logs.append(f"✗  {node}: błąd prognozy: {e}")

    df_out = pd.DataFrame(rows)
    # porządkowanie kolumn
    # NAPRAWIONE: pełne nagłówki ("Temp min [°C]", "Ciśnienie [hPa]" itd.)
    # ucinały się do "Temp...", "Ciśnie..." przy wąskich kolumnach - Gradio
    # obcina nagłówek do szerokości kolumny niezależnie od wrap. Skrócone do
    # jednostki + istotnego słowa (Min/Śr/Max °C, Opad mm, Ciśn hPa,
    # Wiatr km/h, Hist. do, V4 °C) - to i tak jest oczywiste w kontekście
    # tabeli prognozy, więc żadna informacja się nie gubi.
    # ZMIENIONE: osobna kolumna "EV" usunięta - "⚡EV" jest teraz dopisywane
    # bezpośrednio do "Stacja" (patrz stacja_str wyżej), wyrównane do prawej
    # strony komórki przez CSS (.col-stacja niżej), zamiast zajmować całą
    # dodatkową kolumnę.
    cols_order = [
        "Stacja", "Data", "Typ",
        "Min °C", "Śr °C", "Max °C",
        "Opad mm", "Ciśn hPa", "Wiatr km/h", "Kier.",
        "Hist. do", "V4 °C",
    ]
    for c in cols_order:
        if c not in df_out.columns:
            df_out[c] = "–"
    df_out = df_out[cols_order]

    _save_last_pull_cache(_LAST_PULL)

    log_str = "\n".join(logs) if logs else "✔ Dane pobrane bez błędów."

    # NAPRAWIONE: pierwotnie ten komunikat pokazywał się tylko przy >1
    # stacji - ale zrzut ekranu użytkownika pokazał ten sam efekt też dla
    # POJEDYNCZEGO miasta przy 14-dniowej prognozie (7 wierszy widocznych
    # z 14 - Prognoza (dni)=14 potwierdzone w Dzienniku, więc backend
    # policzył poprawnie, tylko tabela mieściła na oko ok. 7 wierszy zanim
    # trzeba było przewinąć WEWNĄTRZ komponentu). max_height podniesione do
    # 1300px (patrz gr.Dataframe niżej), więc 14 dni jednej stacji powinno
    # się teraz mieścić bez przewijania - próg podniesiony do 16, żeby
    # komunikat pokazywał się głównie tam, gdzie faktycznie jest potrzebny
    # (Cały Region/Wybór miast z wieloma stacjami), nie przy zwykłym
    # pojedynczym mieście.
    _VISIBLE_ROWS_APPROX = 16
    n_stations = len(nodes)
    if len(df_out) > _VISIBLE_ROWS_APPROX:
        if n_stations > 1:
            co = f"{n_stations} stacji ({', '.join(nodes)})"
        else:
            co = f"{forecast_days} dni prognozy dla {nodes[0]}"
        row_note = (
            f"📊 **{co}, {len(df_out)} wierszy łącznie** — widoczna jest "
            f"tylko część (tabela mieści ok. {_VISIBLE_ROWS_APPROX} wierszy "
            f"na raz). Przewiń tabelę **w dół wewnątrz niej samej** (nie "
            f"stronę), żeby zobaczyć resztę."
        )
    else:
        row_note = ""

    return log_str, df_out, row_note


# ══════════════════════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════════════════════

def update_visibility(mode: str):
    """Zwraca widoczność dla (region, city, cities_multi) - w tej kolejności,
    musi odpowiadać outputs=[region, city, cities_multi] w mode.change()."""
    if mode == "Pojedyncze miasto":
        return gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)
    if mode == "Wybór miast":
        return gr.update(visible=False), gr.update(visible=False), gr.update(visible=True)
    return gr.update(visible=True), gr.update(visible=False), gr.update(visible=False)


# NAPRAWIONE: theme/css jako moduł-poziomowe stałe, nie tylko lokalne w
# create_app() - Gradio >=6.0 PRZESTAŁO honorować theme/css przekazane do
# konstruktora gr.Blocks() (tylko ostrzega UserWarning i po cichu je
# pomija), trzeba je podać też w app.launch() na końcu pliku. Ponieważ
# requirements.txt ma "gradio>=4.0.0" bez górnej granicy, świeży `pip
# install` może ściągnąć 6.x i cały CSS (w tym #forecast_table wyżej -
# patrz naprawa "skoków" w tabeli) po prostu by zniknął bez żadnego błędu.
# Przekazanie w obu miejscach jest bezpieczne wstecznie - starsze Gradio
# (4.x/5.x) też akceptuje theme/css w launch().
_THEME = gr.themes.Soft(primary_hue="sky", neutral_hue="slate")
_CSS = """
        #header { font-size: 1.3rem; font-weight: 700; color: #0ea5e9; }
        #warn   { color: #f59e0b; font-size: 0.85rem; }
        .label-text { font-weight: 600 !important; }

        /* NAPRAWIONE: "Stacja"/"Data" zawijały się do dwóch linii przy
           domyślnych (za wąskich) szerokościach kolumn (wrap=True), co
           dawało różną wysokość kolejnych wierszy - "skoki" w tabeli.
           Teraz: wrap=False + wystarczająco szerokie kolumny (patrz
           column_widths niżej), a to CSS wymusza jedną linię na komórkę
           (na wypadek gdyby konkretna wersja Gradio i tak próbowała
           zawijać) i wyrównuje wszystko do jednakowej, gęstej siatki -
           stąd tabularne cyfry (żeby kolumny liczb nie "skakały" przez
           różną szerokość znaków 1 vs 8) i wyśrodkowanie w każdej komórce.
        */
        /* NAPRAWIONE: "border-collapse: collapse" na <table> potrafi cicho
           psuć "position: sticky" na nagłówku (znany konflikt CSS) - Gradio
           renderuje przewijaną tabelę właśnie przez sticky header + scroll
           na kontenerze. Efekt zgłoszony przez użytkownika: przy wyniku
           dłuższym niż mieści się na ekranie (>7 wierszy) w ogóle nie było
           widać suwaka/scrollbara - wyglądało jak "wynik się nie
           zaktualizował", a naprawdę dodatkowe wiersze były w DOM, tylko
           kontener nie dawał się przewinąć. "border-spacing: 0" + "separate"
           daje wizualnie ten sam efekt (brak przerw między komórkami) bez
           łamania sticky/scroll. Jawne overflow-y na wypadek gdyby motyw
           Gradio go nie ustawiał sam mimo max_height w komponencie. */
        #forecast_table table {
            border-collapse: separate;
            border-spacing: 0;
            font-variant-numeric: tabular-nums;
        }
        #forecast_table > div {
            overflow-y: auto !important;
            overflow-x: auto !important;
        }
        /* DODANE: 🔴🟠🟢/⚡ nie renderowały się w komórkach tabeli (puste/
           "tofu" znaki) na niektórych systemach - domyślny stos fontów
           motywu Gradio (Soft) nie zawiera fontu z glifami emoji, a bez
           jawnego fallbacku przeglądarka nie zawsze sama podstawia font
           systemowy dla pojedynczego znaku. Jawny fallback do fontów
           emoji (Segoe UI Emoji na Windows, Apple Color Emoji na macOS,
           Noto Color Emoji na Linux) wymusza poprawne renderowanie tych
           konkretnych glifów, nie zmieniając wyglądu reszty tekstu. */
        #forecast_table table td, #forecast_table table th {
            white-space: nowrap !important;
            text-align: center !important;
            padding: 7px 10px !important;
            font-size: 0.92rem;
            line-height: 1.3rem;
            border: 1px solid rgba(148, 163, 184, 0.18);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                Helvetica, Arial, sans-serif, "Apple Color Emoji",
                "Segoe UI Emoji", "Segoe UI Symbol", "Noto Color Emoji";
        }
        /* Zmienione wartości mają prefiks "▲" w zwykłym tekście (patrz
           _mark() w run_simulation) - nie potrzebuje żadnego CSS. */
        /* "Stacja" (1. kolumna) wyrównana do prawej strony komórki - niesie
           teraz też "⚡EV" dopisane do nazwy miasta (patrz stacja_str w
           run_simulation), więc lewe wyrównanie zostawiało nierówną,
           "postrzępioną" krawędź tekstu; prawe wyrównanie równa to ładnie
           niezależnie od tego, czy w wierszu jest EV, czy nie. */
        #forecast_table table td:nth-child(1) {
            text-align: right !important;
        }
        /* NAPRAWIONE: nagłówki ("Temp min [°C]", "Ciśnienie [hPa]" itd.)
           ucinały się do "Temp...", "Ciśnie..." - Gradio obcina nagłówek do
           szerokości kolumny bez wglądu w to, że treść jest dłuższa niż
           dane pod spodem. Skrócone same etykiety (patrz cols_order w
           run_simulation) ORAZ mniejsza czcionka nagłówka niż komórek
           danych - dwie niezależne naprawy tego samego objawu, każda
           zmniejsza ryzyko powrotu problemu przy kolejnej zmianie nazw.
        */
        #forecast_table table th {
            font-weight: 700;
            font-size: 0.78rem;
            padding: 6px 8px !important;
        }
        #forecast_table table tr { height: 2.3rem; }

        /* Znaczek 🔴🟠🟢 (korekta obciążenia) i sygnały TIMDR mieszkają
           w kolumnie "Typ" (3. kolumna wg cols_order - Stacja, Data, Typ,
           EV, ...) razem z tekstem "Dziś"/"Jutro"/"+Nd" o różnej długości.
           ⚡EV ma teraz własną, 4. kolumnę - patrz DODANE przy column_widths.
           Wyśrodkowanie (domyślne dla reszty tabeli) rozjeżdżało kółka na
           boki - wyrównane do lewej trzymają się jednego miejsca w kolumnie,
           bliżej efektu "równo w szeregu". */
        #forecast_table table td:nth-child(3),
        #forecast_table table th:nth-child(3) {
            text-align: left !important;
        }
        #forecast_table table td:nth-child(3) { padding-left: 12px !important; }

        /* NAPRAWIONE: chipy z nazwami miast w "Miasta (wybór)" łamały się
           w połowie słowa ("Krakow_Cen" / "trum") w wąskiej lewej kolumnie -
           komponent przeniesiony do szerokiej prawej (patrz create_app()),
           a to jako druga, niezależna warstwa zabezpieczenia (na wypadek
           wąskiego okna przeglądarki): wymuszamy brak zawijania i elipsę
           zamiast łamania w środku słowa na dowolnym elemencie tekstowym
           wewnątrz komponentu, niezależnie od dokładnych nazw klas, które
           Gradio generuje inaczej w różnych wersjach. */
        #cities_multi span, #cities_multi div {
            white-space: nowrap;
            text-overflow: ellipsis;
        }

        /* DODANE: "Uruchom prognozę" wyróżniony na zielono zamiast domyślnego
           niebieskiego z motywu (_THEME = primary_hue="sky") - to jedyny
           przycisk, który faktycznie odpala pobieranie/analizę, więc ma się
           wizualnie odróżniać od reszty (w tym od "Wyczyść cache", który
           zostaje w neutralnym stylu motywu). */
        #run_btn {
            background: #16a34a !important;
            border-color: #15803d !important;
            color: #ffffff !important;
        }
        #run_btn:hover {
            background: #15803d !important;
        }
        """


def create_app():
    with gr.Blocks(
        theme=_THEME,
        title="Synoptyk-v2.0",
        css=_CSS,
    ) as demo:

        gr.Markdown(
            "# 🌪️ Synoptyk-v2.0 — Prognoza wielodniowa\n"
            "Temperatura · Ciśnienie · Opady · Wiatr  |  dane: Open-Meteo (live)",
            elem_id="header",
        )

        with gr.Row():
            # ── panel sterowania ──────────────────────────────────────────
            # NAPRAWIONE: lewa kolumna byla scale=1 vs prawa scale=3 (25%
            # szerokosci) - zmniejszone do wezszej proporcji, zeby wiecej
            # miejsca zostalo dla tabeli prognozy (teraz i tak szerszej,
            # bo doszly kolumny "Kier." i "Temp śr V4").
            # NAPRAWIONE (2): dalsze zwezenie (min_width 220->190,
            # scale prawej 6->8) - lewe menu miało zbyt dużo pustego
            # miejsca i długie etykiety suwaków zawijały się do 3 linii
            # (patrz skrócone etykiety niżej).
            with gr.Column(scale=1, min_width=190):

                # ZMIENIONE: domyślny tryb startowy to teraz "Pojedyncze
                # miasto" / Kraków, nie "Cały Region". Powód: "Cały Region"
                # (7 stacji × do 14 dni = do 98 wierszy) w praktyce nie mieści
                # się w max_height=700px tabeli - widać wtedy głównie tylko
                # pierwszą stację (Kraków) plus kilka wierszy kolejnej, dopóki
                # nie przewinie się w dół. To NIE jest błąd zwracania danych
                # (zweryfikowane: backend faktycznie zwraca wszystkie stacje
                # regionu, patrz test w historii sesji) - tylko efekt
                # ograniczonej wysokości widoku. Start od pojedynczego miasta
                # daje od razu kompletny, niewymagający scrolla widok.
                # DODANE: trzeci tryb "Wybór miast" - dowolna kombinacja
                # miast (nie ograniczona do sztywnych grup z REGIONS_MAP),
                # np. Kraków + Gdańsk + Warszawa naraz.
                mode = gr.Radio(
                    choices=["Cały Region", "Pojedyncze miasto", "Wybór miast"],
                    value="Pojedyncze miasto",
                    label="Tryb",
                )
                region = gr.Dropdown(
                    choices=list(REGIONS_MAP.keys()),
                    value="poland_south",
                    label="Region",
                    visible=False,
                )
                city = gr.Dropdown(
                    choices=POLISH_CITIES,
                    value="Krakow_Centrum",
                    label="Miasto",
                    visible=True,
                )
                # NAPRAWIONE: "Miasta (wybór)" (multiselect) był tutaj, w
                # wąskiej (190px) lewej kolumnie - nazwy miast w chipach
                # zawijały się w połowie słowa ("Krakow_Cen" / "trum"),
                # bo pojedynczy chip miał za mało miejsca. Przeniesiony do
                # szerokiej prawej kolumny (patrz niżej, nad tabelą) - tam
                # jest miejsce na pełne nazwy bez łamania. Widoczność nadal
                # sterowana tym samym update_visibility(mode).

                # ZMIENIONE: przycisk "Uruchom prognozę" przeniesiony spod
                # samego dołu panelu (pierwsza poprawka) TERAZ pod sekcję
                # wyboru trybu/miast (Tryb + Region/Miasto/Miasta), zamiast
                # nad nią - bo wybór trybu (zwłaszcza "Wybór miast") dzieje
                # się PRZED uruchomieniem i będzie używany najczęściej, więc
                # przycisk ma być bezpośrednio pod tym, co się właśnie
                # ustawiło, a nie nad tym. Działanie (btn.click na dole
                # pliku) nie zależy od kolejności renderowania w Blocks.
                btn = gr.Button("▶ Uruchom prognozę", variant="primary", size="lg", elem_id="run_btn")
                # DODANE: ręczne czyszczenie _last_pull_cache.json - pamięć
                # ⚡EV (poprzedni pull per stacja/dzień) rosła bezterminowo i
                # mogła zawierać stare wpisy z innych stacji/trybów/testów,
                # które nie są już istotne (patrz clear_last_pull_cache()
                # niżej). Nie czyści krakow_forecast_snapshots.csv (dane do
                # bias_correction) - to osobny, celowo trwały plik.
                clear_cache_btn = gr.Button("🔄 Wyczyść cache (⚡EV)", size="sm")

                gr.Markdown("---")

                # NAPRAWIONE: pełne etykiety ("Historia (dni) — okno filtra
                # falkowego") zawijały się do 2-3 linii w wąskiej kolumnie,
                # rozjeżdżając panel - skrócone, pełne wyjaśnienie zostaje
                # w bloku ℹ️ niżej.
                history_days = gr.Slider(
                    minimum=3, maximum=30, value=7, step=1,
                    label="Historia (dni)",
                )
                forecast_days = gr.Slider(
                    minimum=1, maximum=14, value=7, step=1,
                    label="Prognoza (dni)",
                )
                offline = gr.Checkbox(value=False, label="Tryb Demo (offline)")

                gr.Markdown(
                    "ℹ️ „Historia (dni)” = okno danych wejściowych do filtra "
                    "falkowego (db4) i korekty UHI, stosowanych na temperaturze. "
                    "Prognoza pochodzi z Open-Meteo Forecast API. "
                    "Kolumna „Temp śr V4” to niezależny, eksperymentalny silnik "
                    "(SynoptykV4 — ekstrapolacja trendu z rzeczywistej historii, "
                    "bez modelu Open-Meteo) pokazywany obok do porównania.",
                    elem_id="warn",
                )

                gr.Markdown(
                    "**Znaczek przy dacie (Typ) — korekta obciążenia:**\n\n"
                    # ZMIENIONE: kółka opisów były w jednej linii oddzielone
                    # "·" - zawijały się nieregularnie w wąskiej kolumnie,
                    # trudno było skojarzyć kolor z opisem na pierwszy rzut
                    # oka. Lista (jeden znaczek na linię) zamiast płynącego
                    # tekstu.
                    "- 🟢 aktywna, solidna próbka (≥15 sparowanych pulli)\n"
                    "- 🟠 aktywna, mała próbka (uwaga, orientacyjna)\n"
                    "- 🔴 jeszcze niedostępna (za mało danych w historii)\n\n"
                    "Dodatkowo: `⚡EV` = wykryty skok głównego silnika względem "
                    "poprzedniego uruchomienia; `▲` przy wartości = zmieniła się "
                    "względem poprzedniego pulla.\n\n"
                    # NAPRAWIONE: pomyłka w poprzedniej wersji tej notatki -
                    # chodziło o SUWAK PRZEWIJANIA SAMEJ TABELI (scrollbar
                    # kontenera wyników), nie o suwaki "Historia"/"Prognoza"
                    # w tym panelu. Odświeżanie tabeli jest teraz opisane
                    # jako jej własny scrollbar, patrz naprawa "border-
                    # collapse: separate" wyżej w kodzie, dzięki której
                    # przewijanie w ogóle działa.
                    "📊 Tabela wyników ma **własny suwak przewijania** "
                    "(w pionie i w poziomie) — jeśli wynik jest dłuższy lub "
                    "szerszy niż widoczny obszar, przewiń **wewnątrz samej "
                    "tabeli**, żeby zobaczyć resztę wierszy/kolumn. Widok "
                    "się przy tym odświeży poprawnie.",
                    elem_id="warn",
                )

            # ── wyniki ────────────────────────────────────────────────────
            with gr.Column(scale=6):
                # NAPRAWIONE: przeniesione z wąskiej lewej kolumny (patrz
                # komentarz przy Miasto/Region wyżej) - tutaj chipy z nazwami
                # miast mają dość miejsca, żeby nie łamać się w połowie słowa.
                cities_multi = gr.Dropdown(
                    choices=POLISH_CITIES,
                    value=["Krakow_Centrum"],
                    multiselect=True,
                    label="Miasta (wybór) — tryb „Wybór miast”",
                    visible=False,
                    elem_id="cities_multi",
                )
                # NAPRAWIONE: "Dziennik" byl zwyklym, zawsze rozwinietym
                # Textbox(lines=3) nad tabela - naglowek + pole zajmowaly
                # zauwazalna czesc wysokosci prawej kolumny, kosztem tabeli
                # prognozy (glownej tresci). Teraz domyslnie zwiniety w
                # Accordion - rozwija sie na klik, gdy faktycznie trzeba
                # zobaczyc logi/ostrzezenia.
                with gr.Accordion("Dziennik", open=False):
                    logs_box = gr.Textbox(
                        label="",
                        lines=2,
                        show_label=False,
                        placeholder="Tutaj pojawią się informacje o pobieraniu danych...",
                    )
                # DODANE: krótka, ZAWSZE WIDOCZNA (nie w zwiniętym Dzienniku)
                # informacja o liczbie stacji/wierszy przy wielu miastach.
                # Powód: przy "Cały Region"/"Wybór miast" z >1 stacją tabela
                # ma więcej wierszy niż mieści max_height (patrz niżej) - bez
                # przewinięcia w dół widać tylko PIERWSZĄ stację i wygląda to
                # jak "reszta się nie pokazała", mimo że backend poprawnie
                # zwraca wszystkie (zweryfikowane bezpośrednim testem
                # run_simulation() dla 2 i 3 wybranych miast - obie stacje/
                # wszystkie trzy zawsze obecne w wyniku). Ten komunikat ma
                # to jednoznacznie wyjaśnić bez konieczności zgadywania.
                row_count_note = gr.Markdown("", elem_id="row_count_note")
                # NAPRAWIONE: wrap=True + za wąskie kolumny ("Stacja"=120px,
                # "Data"=95px) łamały "Krakow_Centrum"/"2026-08-16" do dwóch
                # linii - różne wiersze wychodziły różnej wysokości ("skoki").
                # wrap=False + poszerzone Stacja/Data = jeden rząd = jedna
                # linia, zawsze.
                # NAPRAWIONE: domyślne max_height=500px pokazywało tylko
                # ok. 2-3 wiersze, 700px w praktyce (zrzut użytkownika) tylko
                # ok. 7 - realna wysokość wiersza w przeglądarce wyszła
                # znacznie większa niż wyliczona z CSS (2.3rem), więc czysto
                # teoretyczne wyliczenie nie sprawdziło się. Zamiast dalej
                # zgadywać - poszerzone hojnie do 1300px, żeby 14-dniowa
                # prognoza pojedynczego miasta mieściła się praktycznie bez
                # scrolla nawet przy większej realnej wysokości wiersza.
                # Gradio Dataframe ma też WŁASNY przycisk pełnego ekranu
                # (ikona ⛶ obok etykiety "Prognoza wielodniowa") - dla
                # trybu "Cały Region"/"Wybór miast" (więcej niż ~30 wierszy)
                # to i tak wygodniejsze niż jakikolwiek stały max_height.
                table = gr.Dataframe(
                    label="Prognoza wielodniowa",
                    elem_id="forecast_table",
                    wrap=False,
                    max_height=1300,
                    # ZMIENIONE (cofnięte): próba pokolorowania zmienionych
                    # wartości przez datatype="markdown"/"html" + <span> nie
                    # zadziałała w dwóch kolejnych podejściach - użytkownik
                    # za każdym razem widział tabelę bez żadnego wyróżnienia
                    # (albo dosłowny tekst tagu). Zamiast dalej zgadywać, co
                    # dokładnie w tej wersji Gradio blokuje style/class w
                    # komórce, _mark() w run_simulation() oznacza teraz
                    # zmienione wartości zwykłym znakiem "▲" w zwykłym
                    # tekście - stąd z powrotem domyślny "str" dla
                    # wszystkich kolumn (bez jawnego datatype=).
                    # "Stacja" poszerzone 150px->180px - mieści teraz też
                    # dopisane "⚡EV" (patrz stacja_str w run_simulation),
                    # wyrównane do prawej strony komórki (.col-stacja w CSS
                    # niżej). "Typ" zwężone do 90px (sam znaczek + krótki
                    # dzień, np. "🟠 13d"). "Wiatr km/h" zwężone do 85px
                    # (wartości krótsze niż "Ciśn hPa"). Osobna kolumna "EV"
                    # usunięta. wrap=False + nowrap w CSS = ucina zamiast
                    # łamać wiersz, więc wysokość rzędów zostaje równa.
                    column_widths=[
                        "180px", "105px", "90px",
                        "95px", "95px", "95px",
                        "90px", "110px", "85px", "50px",
                        "115px", "160px",
                    ],
                )

        # ── eventy ────────────────────────────────────────────────────────
        mode.change(
            fn=update_visibility,
            inputs=[mode],
            outputs=[region, city, cities_multi],
        )

        btn.click(
            fn=run_simulation,
            inputs=[mode, region, city, cities_multi, history_days, forecast_days, offline],
            outputs=[logs_box, table, row_count_note],
        )

        clear_cache_btn.click(
            fn=clear_last_pull_cache,
            outputs=[logs_box],
        )

    return demo


if __name__ == "__main__":
    app = create_app()
    # DODANE: .queue() - bez niej Gradio Blocks obsługuje kliknięcie
    # "Uruchom prognozę" jako zwykły, pojedynczy request/response przez
    # HTTP. run_simulation() robi żywe zapytania sieciowe (Open-Meteo -
    # do 2 na stację x do kilkunastu stacji w trybie "Cały Region"/"Wybór
    # miast") i potrafi trwać kilka-kilkanaście sekund. To dokładnie
    # scenariusz zgłaszany jako "zmieniłem suwak/wybór miast, kliknąłem
    # Uruchom, tabela się nie zmienia" - bez kolejki (WebSocket zamiast
    # gołego requestu) dłuższe wywołania są bardziej podatne na to, że
    # odpowiedź nie zostanie poprawnie powiązana z UI po stronie
    # przeglądarki, mimo że backend policzył wynik poprawnie. .queue() to
    # standardowa, zalecana przez dokumentację Gradio poprawka dla funkcji
    # trwających dłużej niż ułamek sekundy - nie zmienia niczego w samej
    # logice run_simulation(), tylko sposób komunikacji z przeglądarką.
    app.queue()
    # theme/css podane też tutaj (patrz komentarz przy _THEME/_CSS wyżej) -
    # try/except na wypadek starszego Gradio, gdzie launch() mógłby nie
    # przyjmować tych kwargs (wtedy i tak działają przez gr.Blocks() w
    # create_app(), więc fallback nic nie traci poza podwójnym ustawieniem).
    # DODANE: inbrowser=True - otwiera domyślną przeglądarkę na
    # http://127.0.0.1:7860 automatycznie, gdy serwer jest już gotowy
    # (Gradio sam czeka na start, nie ma tu wyścigu jak przy ręcznym
    # "start http://..." w .bat PRZED uruchomieniem serwera). Razem ze
    # zmianą w run.bat (osobny serwer API przeniesiony do run_api.bat,
    # nieuruchamiany domyślnie) - jedno okno terminala + jedna karta
    # przeglądarki, otwierana sama, zamiast dwóch okien konsoli i
    # ręcznego wpisywania adresu (na to poprosił użytkownik).
    # NAPRAWIONE: port był na sztywno wpisany (7860), więc jeśli był już
    # zajęty (np. druga uruchomiona instancja, albo inny program na tym
    # porcie), app.launch() rzucał nieobsłużony OSError - traceback i
    # natychmiastowe zamknięcie procesu. To dokładnie zgłoszony objaw
    # "wywala okienko" / "konsola się zamyka": run.bat próbował wcześniej
    # sam znaleźć wolny port (pętla z heredokiem `python - <<EOF`), ale
    # ta składnia jest z basha/POSIX-a, nie z Windows cmd.exe - w cmd
    # `<<EOF` nie jest obsługiwane i powoduje błąd parsowania, który może
    # ubić całe okno konsoli, ZANIM `python gui_app.py` w ogóle się
    # uruchomi. Do tego GRADIO_SERVER_PORT ustawiane przez ten fragment
    # run.bat i tak nie było tu nigdzie odczytywane - port był zawsze
    # 7860 niezależnie od tego, co ustawił .bat. Naprawiono oba problemy:
    # szukanie wolnego portu przeniesione tutaj, do Pythona (prostsze,
    # przenośne, faktycznie połączone z app.launch()).
    def _find_free_port(preferred=7860, span=40):
        import socket
        candidates = [preferred] + list(range(preferred + 1, preferred + span))
        env_port = os.environ.get("GRADIO_SERVER_PORT")
        if env_port:
            try:
                candidates = [int(env_port)] + candidates
            except ValueError:
                pass
        for p in candidates:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind(("127.0.0.1", p))
                s.close()
                return p
            except OSError:
                s.close()
                continue
        return None

    _port = _find_free_port(7860)
    if _port is None:
        print("[BŁĄD] Nie znaleziono wolnego portu w zakresie 7860-7900.")
        print("Zamknij inne uruchomione instancje Synoptyka albo zwolnij port ręcznie.")
        input("Naciśnij Enter, aby zamknąć...")
        raise SystemExit(1)

    print(f"[OK] Uruchamianie GUI na porcie {_port}...")
    try:
        app.launch(server_name="127.0.0.1", server_port=_port, theme=_THEME, css=_CSS, inbrowser=True)
    except TypeError:
        app.launch(server_name="127.0.0.1", server_port=_port, inbrowser=True)
    except OSError as e:
        # ostatnia linia obrony - gdyby port zdążył zostać zajęty między
        # sprawdzeniem a launch() (wyścig, rzadkie, ale możliwe)
        print(f"[BŁĄD] Nie udało się uruchomić serwera na porcie {_port}: {e}")
        input("Naciśnij Enter, aby zamknąć...")
        raise
