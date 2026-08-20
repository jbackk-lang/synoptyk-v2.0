import requests
import pandas as pd
from datetime import datetime, timedelta

REGIONS = {
    "wieliczka": (49.987, 20.065),
    "krakow": (50.064, 19.945),
    "tarnow": (50.012, 20.985),
    "nowy_sacz": (49.621, 20.697),
    "zakopane": (49.299, 19.949)
}

def fetch_real_weather(lat, lon, days=14):
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        "&hourly=temperature_2m,precipitation,wind_speed_10m,pressure_msl"
    )

    r = requests.get(url).json()

    df = pd.DataFrame({
        "time": r["hourly"]["time"],
        "temp": r["hourly"]["temperature_2m"],
        "precip": r["hourly"]["precipitation"],
        "wind": r["hourly"]["wind_speed_10m"],
        "pressure": r["hourly"]["pressure_msl"]
    })

    df["time"] = pd.to_datetime(df["time"])
    return df

def fetch_all_regions(days=14):
    out = {}
    for name, (lat, lon) in REGIONS.items():
        out[name] = fetch_real_weather(lat, lon, days)
    return out
