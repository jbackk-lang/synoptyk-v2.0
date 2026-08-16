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
_OPEN_METEO_HOURLY = (
    "temperature_2m,precipitation,pressure_msl,windspeed_10m,"
    "relativehumidity_2m"
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
        "humidity":    h["relativehumidity_2m"],
    }).set_index("time")
    return df


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

    how: "mean" | "min" | "max" — jak agregować godzinowe dane do dziennych
    przed ekstrapolacją (żeby np. dla temp_min ekstrapolować trend samych
    dobowych minimów, nie średnich).
    """
    if not _V4_OK or df_hist is None or col not in df_hist.columns:
        return None
    s = df_hist[col].dropna()
    if how == "min":
        daily = s.resample("1D").min().dropna()
    elif how == "max":
        daily = s.resample("1D").max().dropna()
    else:
        daily = s.resample("1D").mean().dropna()
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


# Pamięć ostatniego pulla per (stacja, data docelowa) — w procesie GUI,
# resetuje się przy restarcie appki. Celowo najprostsza możliwa forma
# (dict w pamięci), bo problem do rozwiązania jest jeden: wykryć skok
# między dwoma kolejnymi uruchomieniami tego samego dnia dla tego samego
# dnia docelowego, nie budować pełnej historii.
_LAST_PULL: dict[tuple[str, str], dict] = {}


def detect_engine_volatility(prev_row: dict, new_row: dict) -> dict:
    """Wykrywa skok głównego silnika między poprzednim a bieżącym pullem dla
    tego samego dnia docelowego. Progi dobrane pod skoki widziane w
    krakow_forecast_snapshots.csv (np. +4d..+9d o 2-5°C, opad jutra
    12.1mm→33.3mm w ciągu tej samej doby, przed wdrożeniem blendingu)."""
    flags = {}
    if abs(prev_row["Temp śr [°C]"] - new_row["Temp śr [°C]"]) > 2.0:
        flags["temp_jump"] = True
    if abs(prev_row["Opady [mm]"] - new_row["Opady [mm]"]) > 10.0:
        flags["precip_jump"] = True
    if abs(prev_row["Ciśnienie [hPa]"] - new_row["Ciśnienie [hPa]"]) > 5.0:
        flags["pressure_jump"] = True
    if abs(prev_row["Wiatr max [km/h]"] - new_row["Wiatr max [km/h]"]) > 8.0:
        flags["wind_jump"] = True
    return flags


# ══════════════════════════════════════════════════════════════════════════════
# główna funkcja backendu
# ══════════════════════════════════════════════════════════════════════════════

def run_simulation(
    mode: str,
    selected_region: str,
    selected_city: str,
    history_days: int,
    forecast_days: int,
    offline_demo: bool,
) -> tuple[str, pd.DataFrame]:

    logs: list[str] = []
    rows: list[dict] = []

    nodes = (
        [selected_city]
        if mode == "Pojedyncze miasto"
        else REGIONS_MAP.get(selected_region.lower(), REGIONS_MAP["poland_south"])
    )

    logs.append(
        f"{'Miasto: ' + selected_city if mode == 'Pojedyncze miasto' else 'Region: ' + selected_region.upper()}"
        f" | Historia: {history_days}d | Prognoza: {forecast_days}d | Stacji: {len(nodes)}"
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
                    "Temp min [°C]": "–", "Temp śr [°C]": "–", "Temp max [°C]": "–",
                    "Opady [mm]": "–", "Ciśnienie [hPa]": "–", "Wiatr max [km/h]": "–",
                    "Kier.": "–", "Temp śr V4 [°C]": "–",
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
            logs.append(f"⚠️  {node}: błąd pobierania historii: {e}")

        # ── TIMDR (opcjonalnie) ─────────────────────────────────────────────
        timdr_results: dict = {}
        if _TIMDR_OK and df_hist is not None:
            try:
                analyzer = TIMDRAnalyzer(station=node)
                timdr_results = analyzer.analyze(df_hist)
            except Exception:
                pass

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

        # ── prognoza Open-Meteo ─────────────────────────────────────────────
        try:
            df_fc = _fetch_forecast(lat, lon, forecast_days)
            daily = _daily_stats(df_fc)

            for day_idx, (day_dt, row_s) in enumerate(daily.iterrows()):
                day_label = day_dt.date()
                # napis "Dziś / Jutro / +Nd"
                delta = (day_label - date.today()).days
                if delta == 0:
                    typ = "Dziś"
                elif delta == 1:
                    typ = "Jutro"
                else:
                    typ = f"+{delta}d"

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
                if day_idx in bias_table:
                    t_avg = apply_bias_correction(t_avg, day_idx, bias_table)
                    typ += " 🎯"

                # sygnały TIMDR → szersze pasmo (wyświetlane w polu Typ)
                signals = [k for k in ("anomalia", "defekt", "rezonans") if timdr_results.get(k)]
                if signals:
                    typ += f" ⚡{'·'.join(s[:3] for s in signals)}"

                # ── EV: skok głównego silnika względem poprzedniego pulla ──
                current_vals = {
                    "Temp śr [°C]": t_avg, "Opady [mm]": precip,
                    "Ciśnienie [hPa]": press, "Wiatr max [km/h]": wind,
                }
                pull_key = (node, str(day_label))
                prev_vals = _LAST_PULL.get(pull_key)
                if prev_vals is not None and detect_engine_volatility(prev_vals, current_vals):
                    typ += " ⚡EV"
                _LAST_PULL[pull_key] = current_vals

                # SynoptykV4 - rownolegly punkt + pasmo (patrz komentarz wyzej)
                v4_str = "–"
                if v4_forecast is not None and day_idx < len(v4_forecast["point"]):
                    v4_point = round(float(v4_forecast["point"][day_idx]), 1)
                    v4_lower = round(float(v4_forecast["lower"][day_idx]), 1)
                    v4_upper = round(float(v4_forecast["upper"][day_idx]), 1)
                    v4_str = f"{v4_point} [{v4_lower}–{v4_upper}]"

                rows.append({
                    "Stacja":          node,
                    "Data":            str(day_label),
                    "Typ":             typ,
                    "Temp min [°C]":   t_min,
                    "Temp śr [°C]":    t_avg,
                    "Temp max [°C]":   t_max,
                    "Opady [mm]":      precip,
                    "Ciśnienie [hPa]": press,
                    "Wiatr max [km/h]":wind,
                    "Kier.":           wind_arrow,
                    "Dane hist. do":   data_end_str,
                    "Temp śr V4 [°C]": v4_str,
                })

        except Exception as e:
            logs.append(f"✗  {node}: błąd prognozy: {e}")

    df_out = pd.DataFrame(rows)
    # porządkowanie kolumn
    cols_order = [
        "Stacja", "Data", "Typ",
        "Temp min [°C]", "Temp śr [°C]", "Temp max [°C]",
        "Opady [mm]", "Ciśnienie [hPa]", "Wiatr max [km/h]", "Kier.",
        "Dane hist. do", "Temp śr V4 [°C]",
    ]
    for c in cols_order:
        if c not in df_out.columns:
            df_out[c] = "–"
    df_out = df_out[cols_order]

    log_str = "\n".join(logs) if logs else "✔ Dane pobrane bez błędów."
    return log_str, df_out


# ══════════════════════════════════════════════════════════════════════════════
# GUI
# ══════════════════════════════════════════════════════════════════════════════

def update_visibility(mode: str):
    if mode == "Pojedyncze miasto":
        return gr.update(visible=False), gr.update(visible=True)
    return gr.update(visible=True), gr.update(visible=False)


def create_app():
    theme = gr.themes.Soft(primary_hue="sky", neutral_hue="slate")

    with gr.Blocks(
        theme=theme,
        title="Synoptyk-v2.0",
        css="""
        #header { font-size: 1.3rem; font-weight: 700; color: #0ea5e9; }
        #warn   { color: #f59e0b; font-size: 0.85rem; }
        .label-text { font-weight: 600 !important; }
        """,
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
            with gr.Column(scale=1, min_width=220):

                mode = gr.Radio(
                    choices=["Cały Region", "Pojedyncze miasto"],
                    value="Cały Region",
                    label="Tryb",
                )
                region = gr.Dropdown(
                    choices=list(REGIONS_MAP.keys()),
                    value="poland_south",
                    label="Region",
                    visible=True,
                )
                city = gr.Dropdown(
                    choices=POLISH_CITIES,
                    value="Krakow_Centrum",
                    label="Miasto",
                    visible=False,
                )

                gr.Markdown("---")

                history_days = gr.Slider(
                    minimum=3, maximum=30, value=7, step=1,
                    label="Historia (dni) — okno filtra falkowego",
                )
                forecast_days = gr.Slider(
                    minimum=1, maximum=14, value=7, step=1,
                    label="Prognoza (dni naprzód)",
                )
                offline = gr.Checkbox(value=False, label="Tryb Demo (offline)")

                gr.Markdown(
                    "ℹ️ Prognoza pochodzi z Open-Meteo Forecast API. "
                    "Korekta UHI i filtr falkowy (db4) są stosowane na temperaturze. "
                    "Kolumna „Temp śr V4” to niezależny, eksperymentalny silnik "
                    "(SynoptykV4 — ekstrapolacja trendu z rzeczywistej historii, "
                    "bez modelu Open-Meteo) pokazywany obok do porównania.",
                    elem_id="warn",
                )

                btn = gr.Button("▶ Uruchom prognozę", variant="primary", size="lg")

            # ── wyniki ────────────────────────────────────────────────────
            with gr.Column(scale=6):
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
                table = gr.Dataframe(
                    label="Prognoza wielodniowa",
                    wrap=True,
                    column_widths=[
                        "120px", "95px", "75px",
                        "100px", "100px", "100px",
                        "90px", "110px", "110px", "45px",
                        "105px", "150px",
                    ],
                )

        # ── eventy ────────────────────────────────────────────────────────
        mode.change(
            fn=update_visibility,
            inputs=[mode],
            outputs=[region, city],
        )

        btn.click(
            fn=run_simulation,
            inputs=[mode, region, city, history_days, forecast_days, offline],
            outputs=[logs_box, table],
        )

    return demo


if __name__ == "__main__":
    app = create_app()
    app.launch(server_name="127.0.0.1", server_port=7860)
