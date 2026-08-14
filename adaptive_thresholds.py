# analyzer/adaptive_thresholds.py
import pandas as pd
import numpy as np
from datetime import datetime
from data.cache import WeatherCache

class AdaptiveThresholds:
    def __init__(self, station="krakow_balice", db_path="weather_cache.db"):
        self.station = station
        self.cache = WeatherCache(db_path)
        self.climatology = self._load_climatology()
    
    def _load_climatology(self):
        df = self.cache.load_climatology(self.station)
        # Uwaga: nawet gdy dla tej stacji nie ma jeszcze wyliczonej klimatologii,
        # `df` wciąż ma poprawne nazwy kolumn (pochodzi z zapytania SQL do
        # istniejącej tabeli) — nie wolno go zastępować "gołym" pd.DataFrame(),
        # bo ten nie ma żadnych kolumn i set_index(['month','param']) wywali
        # KeyError: "None of ['month', 'param'] are in the columns".
        if df.empty:
            return pd.DataFrame(columns=['station', 'month', 'param', 'mean', 'std', 'p10', 'p90', 'updated_at']) \
                .set_index(['month', 'param'])
        return df.set_index(['month', 'param'])
    
    def get_thresholds(self, dt: datetime, param: str) -> dict:
        month = dt.month
        
        if (month, param) in self.climatology.index:
            row = self.climatology.loc[(month, param)]
            mean = row['mean']
            std = row['std']
            p10 = row['p10']
            p90 = row['p90']
        else:
            df_recent = self.cache.load_last_n_days(30)
            if df_recent.empty:
                return {'mean': 0, 'std': 1, 'low': -2, 'high': 2, 'p10': -1, 'p90': 1, 'threshold_skret': 1, 'threshold_defekt': 1}
            mean = df_recent[param].mean()
            std = df_recent[param].std()
            p10 = df_recent[param].quantile(0.1)
            p90 = df_recent[param].quantile(0.9)
        
        return {
            'mean': mean,
            'std': std,
            'low': mean - 2*std,
            'high': mean + 2*std,
            'p10': p10,
            'p90': p90,
            'threshold_skret': 1.5 * std if std > 0 else 1.0,
            'threshold_defekt': 0.3 * (p90 - p10) if (p90 - p10) > 0 else 1.0
        }
    
    def is_anomaly(self, value: float, dt: datetime, param: str) -> bool:
        thresholds = self.get_thresholds(dt, param)
        return value > thresholds['high'] or value < thresholds['low']
    
    def is_defect(self, current: float, previous: float, dt: datetime, param: str) -> bool:
        thresholds = self.get_thresholds(dt, param)
        return abs(current - previous) > thresholds['threshold_defekt']
    
    def is_trend_reversal(self, series: pd.Series, dt: datetime, param: str) -> bool:
        if len(series) < 3:
            return False
        diff = series.diff()
        if len(diff) >= 2 and diff.iloc[-1] is not None and diff.iloc[-2] is not None:
            sign_change = (diff.iloc[-1] > 0) != (diff.iloc[-2] > 0)
            thresholds = self.get_thresholds(dt, param)
            return sign_change and abs(diff.iloc[-1]) > thresholds['threshold_skret']
        return False
