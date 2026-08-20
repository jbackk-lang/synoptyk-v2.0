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
        # NAPRAWIONE: wydajność - get_thresholds() jest wywoływane per
        # (wiersz, param) w TIMDRAnalyzer.analyze() (do ~15x na wiersz:
        # is_anomaly + is_defect + is_trend_reversal x kilka parametrów),
        # a przy 30-dniowej historii godzinowej to ~720 wierszy x 15 =
        # ~10 800 wywołań NA JEDNĄ stację. Każde z nich, gdy climatology
        # jest puste (normalny stan dla gui_app.py), robiło zapytanie SQL
        # (self.cache.load_last_n_days) I liczyło mean/std/quantile na
        # całym fallback_df OD ZERA - a wynik dla danego parametru jest
        # w tej gałęzi stały (nie zależy od dt/wiersza, tylko od param) -
        # więc to była czysta, niepotrzebnie powtarzana praca (dla 3
        # miast + suwaki na max zgłoszone ~300s zamiast liczonych w
        # sekundach). Cache poniżej liczy każdą kombinację (miesiąc,
        # param)/(fallback, param) raz na całe wywołanie analyze().
        self._threshold_cache: dict = {}
        self._df_recent_cache = None  # sentinel: None = jeszcze nie wczytane

    def _get_df_recent(self):
        if self._df_recent_cache is None:
            self._df_recent_cache = self.cache.load_last_n_days(30)
        return self._df_recent_cache

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
            cache_key = ("clim", month, param)
            if cache_key in self._threshold_cache:
                return self._threshold_cache[cache_key]
            row = self.climatology.loc[(month, param)]
            mean = row['mean']
            std = row['std']
            p10 = row['p10']
            p90 = row['p90']
        else:
            # Ta gałąź NIE zależy od `dt` (ani `month`) - tylko od `param` -
            # więc jeden klucz cache na cały czas życia obiektu wystarczy.
            cache_key = ("fallback", param)
            if cache_key in self._threshold_cache:
                return self._threshold_cache[cache_key]
            df_recent = self._get_df_recent()
            if df_recent.empty or param not in df_recent.columns:
                df_recent = self.fallback_df
            if df_recent is None or df_recent.empty or param not in df_recent.columns:
                result = {'mean': 0, 'std': 1, 'low': -2, 'high': 2, 'p10': -1, 'p90': 1, 'threshold_skret': 1, 'threshold_defekt': 1}
                self._threshold_cache[cache_key] = result
                return result
            mean = df_recent[param].mean()
            std = df_recent[param].std()
            p10 = df_recent[param].quantile(0.1)
            p90 = df_recent[param].quantile(0.9)
            if pd.isna(std) or std == 0:
                std = 1.0  # n=1 albo stala wartosc w oknie - unikamy low==high
            if pd.isna(mean):
                result = {'mean': 0, 'std': 1, 'low': -2, 'high': 2, 'p10': -1, 'p90': 1, 'threshold_skret': 1, 'threshold_defekt': 1}
                self._threshold_cache[cache_key] = result
                return result

        result = {
            'mean': mean,
            'std': std,
            'low': mean - 2*std,
            'high': mean + 2*std,
            'p10': p10,
            'p90': p90,
            'threshold_skret': 1.5 * std if std > 0 else 1.0,
            'threshold_defekt': 0.3 * (p90 - p10) if (p90 - p10) > 0 else 1.0
        }
        self._threshold_cache[cache_key] = result
        return result
    
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
