# data/fetcher.py
import requests
import pandas as pd
from datetime import datetime, timedelta


class WeatherFetcher:
    def __init__(self, lat=50.083, lon=19.917):
        self.lat = lat
        self.lon = lon
        self.base_url = "https://archive-api.open-meteo.com/v1/archive"

    def fetch_hourly(self, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Pobiera dane godzinowe z Open-Meteo.
        start_date, end_date: 'YYYY-MM-DD'
        """
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "start_date": start_date,
            "end_date": end_date,
            "hourly": "temperature_2m,relative_humidity_2m,precipitation,pressure_msl,wind_speed_10m,wind_direction_10m",
            "timezone": "Europe/Warsaw"
        }

        try:
            response = requests.get(self.base_url, params=params, timeout=15)
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Błąd połączenia z Open-Meteo: {e}")

        if response.status_code != 200:
            # API zwraca w treści JSON pole "reason" z opisem błędu (np. zły zakres dat)
            try:
                reason = response.json().get("reason", response.text[:200])
            except ValueError:
                reason = response.text[:200]
            raise ValueError(f"Open-Meteo zwróciło błąd HTTP {response.status_code}: {reason}")

        data = response.json()

        if "hourly" not in data:
            raise ValueError(
                "Błąd pobierania danych: brak klucza 'hourly' w odpowiedzi "
                f"(prawdopodobnie zbyt świeży zakres dat dla API archiwalnego: {start_date}..{end_date})"
            )

        df = pd.DataFrame({
            "datetime": data["hourly"]["time"],
            "temp": data["hourly"]["temperature_2m"],
            "pressure": data["hourly"]["pressure_msl"],
            "humidity": data["hourly"]["relative_humidity_2m"],
            "wind_speed": data["hourly"]["wind_speed_10m"],
            "wind_dir": data["hourly"]["wind_direction_10m"],
            "precip": data["hourly"]["precipitation"]
        })

        # Open-Meteo Archive API czasem zwraca puste listy zamiast błędu 400
        # dla dat zbyt bliskich "dziś" – usuwamy wtedy wiersze bez danych.
        df = df.dropna(subset=["temp"]).reset_index(drop=True)
        if df.empty:
            raise ValueError(
                f"Brak danych archiwalnych dla zakresu {start_date}..{end_date} "
                "(dane ERA5 z Open-Meteo mają zwykle kilka dni opóźnienia)."
            )

        return df

    def fetch_last_n_days(self, n=7, lag_days=5) -> pd.DataFrame:
        """
        Pobiera ostatnie n dni danych archiwalnych.

        lag_days: Open-Meteo Archive API (dane ERA5) nie ma jeszcze danych
        z ostatnich ~5 dni – bez tego przesunięcia zapytanie o "dzisiaj"
        kończy się błędem "brak klucza 'hourly'" i pustą tabelą w GUI.
        """
        end = datetime.now() - timedelta(days=lag_days)
        start = end - timedelta(days=n)
        return self.fetch_hourly(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
