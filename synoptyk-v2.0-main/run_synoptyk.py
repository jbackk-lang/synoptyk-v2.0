"""
Run Synoptyk – Skrypt wykonawczy, teraz faktycznie oparty o silnik TIMDR:
  1. pobiera realne dane (Open-Meteo) dla wybranego regionu,
  2. odpala TIMDRAnalyzer (skręt/anomalia/rezonans/defekt) na tych danych,
  3. odszumia szereg temperatury filtrem falkowym (SynoptykFEngine),
  4. liczy korektę UHI/wysokość ZASILONĄ sygnałami TIMDR (szersza
     niepewność i ostrzeżenie, jeśli TIMDR wykrył coś niestabilnego),
  zamiast wcześniejszego stałego base_temp=28.0 niezależnego od danych.
"""
import argparse
import sys

from grid_engine import SpatialGridEngine, get_region_bbox
from synoptyk_f import SynoptykFEngine
from topomap_data import TOPOGRAPHY_DATABASE, get_node_metadata
from data.fetcher import WeatherFetcher
from analyzer.timdr_analyzer import TIMDRAnalyzer

# Węzły dostępne per region — żeby nie próbować liczyć "Krakow_Center" dla USA
# ============================================
#  API REGIONÓW — POLSKA + USA (NOWE)
# ============================================

REGIONS = {

    # ----------------------------------------
    # 🇵🇱 POLSKA — regiony meteorologiczne
    # ----------------------------------------

    "poland": [
        "Warszawa",
        "Krakow_Centrum",
        "Gdansk",
        "Wroclaw",
        "Poznan",
        "Szczecin"
    ],

    "poland_south": [
        "Krakow_Centrum",
        "Tarnow",
        "Nowy_Sacz",
        "Zakopane",
        "Katowice",
        "Rzeszow",
        "Bielsko_Biala"
    ],

    "poland_north": [
        "Gdansk",
        "Gdynia",
        "Sopot",
        "Suwalki",
        "Olsztyn",
        "Elblag",
        "Koszalin"
    ],

    "poland_central": [
        "Warszawa",
        "Lodz",
        "Radom",
        "Plock",
        "Wloclawek",
        "Czestochowa"
    ],

    "poland_west": [
        "Poznan",
        "Szczecin",
        "Zielona_Gora",
        "Gorzow_Wlkp",
        "Leszno",
        "Pila"
    ],

    "poland_east": [
        "Lublin",
        "Bialystok",
        "Zamosc",
        "Przemysl",
        "Terespol",
        "Sandomierz"
    ],

    # ----------------------------------------
    # 🇺🇸 USA — pełne API stanów
    # ----------------------------------------

    "usa_states": {
        "Alabama": "Birmingham",
        "Alaska": "Anchorage",
        "Arizona": "Phoenix",
        "Arkansas": "Little_Rock",
        "California": "Los_Angeles",
        "Colorado": "Denver",
        "Connecticut": "Hartford",
        "Delaware": "Wilmington",
        "Florida": "Miami",
        "Georgia": "Atlanta",
        "Hawaii": "Honolulu",
        "Idaho": "Boise",
        "Illinois": "Chicago",
        "Indiana": "Indianapolis",
        "Iowa": "Des_Moines",
        "Kansas": "Wichita",
        "Kentucky": "Louisville",
        "Louisiana": "New_Orleans",
        "Maine": "Portland_ME",
        "Maryland": "Baltimore",
        "Massachusetts": "Boston",
        "Michigan": "Detroit",
        "Minnesota": "Minneapolis",
        "Mississippi": "Jackson",
        "Missouri": "St_Louis",
        "Montana": "Billings",
        "Nebraska": "Omaha",
        "Nevada": "Las_Vegas",
        "New_Hampshire": "Manchester",
        "New_Jersey": "Newark",
        "New_Mexico": "Albuquerque",
        "New_York": "New_York_City",
        "North_Carolina": "Charlotte",
        "North_Dakota": "Fargo",
        "Ohio": "Columbus",
        "Oklahoma": "Oklahoma_City",
        "Oregon": "Portland_OR",
        "Pennsylvania": "Philadelphia",
        "Rhode_Island": "Providence",
        "South_Carolina": "Charleston",
        "South_Dakota": "Sioux_Falls",
        "Tennessee": "Nashville",
        "Texas": "Houston",
        "Utah": "Salt_Lake_City",
        "Vermont": "Burlington",
        "Virginia": "Richmond",
        "Washington": "Seattle",
        "West_Virginia": "Charleston_WV",
        "Wisconsin": "Milwaukee",
        "Wyoming": "Cheyenne"
    },

    # ----------------------------------------
    # 🇺🇸 USA — regiony meteorologiczne
    # ----------------------------------------

    "usa_northeast": [
        "New_York_City",
        "Boston",
        "Philadelphia",
        "Baltimore",
        "Hartford"
    ],

    "usa_southeast": [
        "Miami",
        "Atlanta",
        "Charlotte",
        "Charleston",
        "Jacksonville"
    ],

    "usa_midwest": [
        "Chicago",
        "Detroit",
        "Columbus",
        "Indianapolis",
        "Milwaukee"
    ],

    "usa_south": [
        "Houston",
        "Dallas",
        "Austin",
        "San_Antonio",
        "New_Orleans"
    ],

    "usa_west": [
        "Los_Angeles",
        "San_Francisco",
        "Seattle",
        "Portland_OR",
        "Las_Vegas"
    ],

    "usa_mountains": [
        "Denver",
        "Salt_Lake_City",
        "Boise",
        "Billings",
        "Cheyenne"
    ]
}


def run_simulation(region: str, days: int, grid_res: float, offline_demo: bool = False):
    print("=== Uruchamianie SYNOPTYK-F (zintegrowany z TIMDR) ===")
    print(f"Region: {region.upper()} | Dni: {days} | Siatka: {grid_res}°")

    try:
        bbox = get_region_bbox(region)
    except ValueError as e:
        print(f"BŁĄD: {e}")
        sys.exit(1)

    grid = SpatialGridEngine(bbox, grid_res).generate_mesh()
    engine = SynoptykFEngine(wavelet="db4")
    print(f"Wygenerowano siatkę o wymiarach: {grid['shape']}")

    nodes = REGION_NODES.get(region.lower())
    if not nodes:
        print(f"BŁĄD: brak zdefiniowanych węzłów pomiarowych dla regionu {region!r}.")
        sys.exit(1)

    print("\n--- Wybrane punkty węzłowe ---")
    for node in nodes:
        meta = get_node_metadata(node)
        lat, lon = NODE_COORDS[node]

        if offline_demo:
            print(f"Stacja: {node:<20} | [DEMO offline — brak realnych danych]")
            continue

        try:
            fetcher = WeatherFetcher(lat=lat, lon=lon)
            df = fetcher.fetch_last_n_days(days)
        except Exception as e:
            print(f"Stacja: {node:<20} | BŁĄD pobierania danych: {e}")
            continue

        analyzer = TIMDRAnalyzer(station=node)
        timdr_results = analyzer.analyze(df)

        result = engine.predict_temperature_timdr(
            df, uhi_factor=meta["uhi_factor"], topo_alt=meta["altitude"],
            timdr_results=timdr_results,
        )
        print(
            f"Stacja: {node:<20} | Alt: {meta['altitude']}m | UHI: +{meta['uhi_factor']}°C | "
            f"Prognoza: {result['point']}°C [{result['lower']} .. {result['upper']}] | {result['timdr_note']}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Synoptyk-F Weather Engine (TIMDR-integrated)")
    parser.add_argument("--region", type=str, default="malopolska",
                         help="Region: malopolska, poland, europe, usa, usa_northeast, usa_west")
    parser.add_argument("--days", type=int, default=7, help="Okno danych wejściowych w dniach")
    parser.add_argument("--grid", type=float, default=0.125, help="Krok siatki w stopniach")
    parser.add_argument("--offline-demo", action="store_true",
                         help="Pokaż tylko strukturę (siatka + węzły) bez pobierania danych na żywo")

    args = parser.parse_args()
    run_simulation(args.region, args.days, args.grid, offline_demo=args.offline_demo)
