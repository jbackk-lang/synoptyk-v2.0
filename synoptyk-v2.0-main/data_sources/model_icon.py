import requests
import pandas as pd
from datetime import datetime, timedelta

def fetch_icon(lat, lon, days=14):
    end = datetime.utcnow().date()
    start = end - timedelta(days=days)

    url = (
        "https://api.open-meteo.com/v1/forecast?"
        f"latitude={lat}&longitude={lon}"
        f"&start_date={start}&end_date={end}"
        "&hourly=temperature_2m,precipitation,wind_speed_10m,pressure_msl"
        "&models=icon_eu"
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
