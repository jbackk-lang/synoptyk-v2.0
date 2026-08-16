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
        # NAPRAWIONE: gdy zarówno tabela climatology, JAK I hourly w
        # weather_cache.db są puste (co jest normalnym stanem dla gui_app.py
        # - "GUI v2 pobiera dane bezpośrednio z API i nie korzysta z cache",
        # patrz docstring gui_app.py), get_thresholds() zwracał sztywne
        # {'mean': 0, 'std': 1, 'low': -2, 'high': 2}. To dawało bezwarunkowe
        # "anomalia" dla KAŻDEJ realnej wartości ciśnienia (~1013), wilgotności
        # (~0-100) czy temperatury (~10-35) - is_anomaly() sprawdza tylko
        # value > high(=2) - żadna z tych wartości nigdy nie mieści się w
        # [-2, 2]. Efekt: po naprawieniu błędu przekazywania danych do
        # analyze() (patrz gui_app.py, _adapt_for_timdr) sygnał "anomalia"
        # zapalałby się na PRAWIE KAŻDYM wierszu - równie bezużyteczne jak
        # wcześniejsze "nigdy". `fallback_df`: opcjonalny zbiór danych (np.
        # ten sam df, który i tak jest analizowany), z którego liczone są
        # statystyki NA ŻYWO, gdy nie ma ani climatology, ani cache - lepsze
        # niż sztywna stała, bo dopasowane do realnej skali parametru,
        # gorsze niż prawdziwa klimatologia (bo "normalne" definiowane jest
        # przez samo okno, więc nie złapie anomalii obecnej przez całe okno).
        self.fallback_df = None
    
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
            if df_recent.empty or param not in df_recent.columns:
                df_recent = self.fallback_df
            if df_recent is None or df_recent.empty or param not in df_recent.columns:
                return {'mean': 0, 'std': 1, 'low': -2, 'high': 2, 'p10': -1, 'p90': 1, 'threshold_skret': 1, 'threshold_defekt': 1}
            mean = df_recent[param].mean()
            std = df_recent[param].std()
            p10 = df_recent[param].quantile(0.1)
            p90 = df_recent[param].quantile(0.9)
            if pd.isna(std) or std == 0:
                std = 1.0  # n=1 albo stala wartosc w oknie - unikamy low==high
            if pd.isna(mean):
                return {'mean': 0, 'std': 1, 'low': -2, 'high': 2, 'p10': -1, 'p90': 1, 'threshold_skret': 1, 'threshold_defekt': 1}
        
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
