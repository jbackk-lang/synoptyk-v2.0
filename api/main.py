from fastapi import FastAPI, HTTPException

from api.regions import REGIONS
from topomap_data import get_node_metadata
from data_sources.real_weather import fetch_real_weather
from data_sources.model_ecmwf import fetch_ecmwf
from data_sources.model_icon import fetch_icon
from synoptyk.compare import compare
from synoptyk.trend import trend

app = FastAPI(title="Synoptyk API v2.0")


@app.get("/api/regions")
def get_regions():
    return REGIONS


@app.get("/api/forecast")
def get_forecast(region: str):
    if region not in REGIONS:
        raise HTTPException(status_code=404, detail="Nieznany region")

    stations = REGIONS[region]

    # "usa_states" w api/regions.py to słownik {stan: miasto}, nie lista stacji —
    # rozbijamy go tutaj, żeby endpoint nie wywalał się przy iteracji po kluczach.
    if isinstance(stations, dict):
        stations = list(stations.values())

    results = {}

    for station in stations:
        # SynoptykEngine.resolve_coords(...) nie istniało w repo — współrzędne
        # bierzemy z tej samej bazy topograficznej, której używa gui_app.py.
        meta = get_node_metadata(station)
        lat, lon = meta.get("lat", 52.0), meta.get("lon", 19.0)

        try:
            real = fetch_real_weather(lat, lon)
            ecmwf = fetch_ecmwf(lat, lon)
            icon = fetch_icon(lat, lon)

            comp_ecmwf = compare(real, ecmwf)
            comp_icon = compare(real, icon)
            tr = trend(real)

            results[station] = {
                "trend": tr,
                "delta_ecmwf": comp_ecmwf[["ΔT", "ΔPrec", "ΔWind"]].mean().to_dict(),
                "delta_icon": comp_icon[["ΔT", "ΔPrec", "ΔWind"]].mean().to_dict()
            }
        except Exception as e:
            # Błąd dla jednej stacji nie powinien wywalać całego zapytania /api/forecast.
            results[station] = {"error": str(e)}

    return results
