# forecaster/synoptic_f.py
"""
SYNOPTIC‑F – Model Prognozowania Strukturalnego.
Rozszerzony o prognozę kierunku wiatru.
"""

from .j_compress import j_compress
from .j_decompress import j_decompress
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

class SynopticF:
    def __init__(self, figure_window=7):
        self.figure_window = figure_window

    def _extract_figure(self, df: pd.DataFrame, param: str):
        data = df[param].dropna().tolist()
        if len(data) < self.figure_window:
            window = data
        else:
            window = data[-self.figure_window:]

        compressed = j_compress(window)
        mean, std = compressed['mean'], compressed['std']
        return {
            'param': param,
            'window': window,
            'mean': mean,
            'std': std,
            'length': len(window)
        }

    def _generate_forecast(self, figure, steps):
        mean, std = figure['mean'], figure['std']
        return j_decompress(mean, std, steps)

    def predict(self, df: pd.DataFrame, horizon_days: int = None) -> dict:
        if horizon_days is None:
            horizon_days = self.figure_window

        params = ['temp', 'pressure', 'humidity', 'wind_speed', 'wind_dir']
        results = {}

        for param in params:
            if param not in df.columns:
                continue

            figure = self._extract_figure(df, param)
            forecast = self._generate_forecast(figure, horizon_days * 24)

            last_date = pd.to_datetime(df['datetime'].iloc[-1])
            forecast_dates = [last_date + timedelta(hours=i+1) for i in range(len(forecast))]

            results[param] = {
                'figure': figure,
                'forecast': forecast,
                'dates': forecast_dates,
                'horizon_days': horizon_days
            }

        return results

    def predict_daily(self, df: pd.DataFrame, horizon_days: int = None) -> dict:
        results = self.predict(df, horizon_days)
        daily_results = {}

        for param, data in results.items():
            forecast = data['forecast']
            dates = data['dates']

            daily_forecast = []
            daily_dates = []
            for i in range(0, len(forecast), 24):
                chunk = forecast[i:i+24]
                if chunk:
                    # Dla kierunku wiatru – średnia wektorowa (nie arytmetyczna)
                    if param == 'wind_dir':
                        # Konwersja na wektory, średnia, powrót do stopni
                        u = sum(np.sin(np.radians(chunk))) / len(chunk)
                        v = sum(np.cos(np.radians(chunk))) / len(chunk)
                        avg_dir = (np.degrees(np.arctan2(u, v)) + 360) % 360
                        daily_forecast.append(avg_dir)
                    else:
                        daily_forecast.append(sum(chunk) / len(chunk))
                    daily_dates.append(dates[i].date() if i < len(dates) else None)

            daily_results[param] = {
                'daily_forecast': daily_forecast,
                'dates': daily_dates,
                'horizon_days': len(daily_forecast)
            }

        return daily_results
