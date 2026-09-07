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
        self._fallback_df = None
        # NAPRAWIONE (wydajność - "GUI liczy 10x dłużej po zwiększeniu
        # suwaka Historia (dni)"): get_thresholds() w gałęzi "brak
        # climatology" niżej odpytuje SQLite (self.cache.load_last_n_days)
        # PRZY KAŻDYM wywołaniu. analyze() w timdr_analyzer.py woła
        # get_thresholds() raz na (wiersz, parametr) w pętli po całej
        # historii godzinowej - przy 30 dniach historii (~720 wierszy) x 5
        # parametrów x kilka sprawdzeń (anomalia/defekt/skręt) to tysiące
        # zapytań SQL, mimo że wynik i tak ZAWSZE ląduje na tym samym
        # fallback_df w typowym użyciu tego GUI (weather_cache.db jest
        # pusta, patrz komentarz w get_thresholds niżej) - realny koszt
        # SQL round-tripu płacony tysiące razy tylko po to, żeby i tak
        # spaść na fallback. Wynik dla danej pary (miesiąc, parametr) jest
        # identyczny przy KAŻDYM wywołaniu w ramach jednego analyze()
        # (fallback_df się nie zmienia w trakcie) - cache keyowany (month,
        # param) redukuje to do garstki realnych obliczeń. Czyszczony
        # automatycznie przy każdym przypisaniu fallback_df (patrz property
        # niżej), żeby nie oddać po cichu przestarzałych progów z
        # poprzedniej stacji/przebiegu.
        self._thresholds_cache: dict = {}

    @property
    def fallback_df(self):
        return self._fallback_df

    @fallback_df.setter
    def fallback_df(self, df):
        self._fallback_df = df
        self._thresholds_cache = {}

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
        cache_key = (month, param)
        cached = self._thresholds_cache.get(cache_key)
        if cached is not None:
            return cached

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
                result = {'mean': 0, 'std': 1, 'low': -2, 'high': 2, 'p10': -1, 'p90': 1, 'threshold_skret': 1, 'threshold_defekt': 1}
                self._thresholds_cache[cache_key] = result
                return result
            mean = df_recent[param].mean()
            std = df_recent[param].std()
            p10 = df_recent[param].quantile(0.1)
            p90 = df_recent[param].quantile(0.9)
            if pd.isna(std) or std == 0:
                std = 1.0  # n=1 albo stala wartosc w oknie - unikamy low==high
            if pd.isna(mean):
                result = {'mean': 0, 'std': 1, 'low': -2, 'high': 2, 'p10': -1, 'p90': 1, 'threshold_skret': 1, 'threshold_defekt': 1}
                self._thresholds_cache[cache_key] = result
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
        self._thresholds_cache[cache_key] = result
        return result
    
    def is_anomaly(self, value: float, dt: datetime, param: str) -> bool:
        thresholds = self.get_thresholds(dt, param)
        return value > thresholds['high'] or value < thresholds['low']
    
    def is_defect(self, current: float, previous: float, dt: datetime, param: str) -> bool:
        thresholds = self.get_thresholds(dt, param)
        return abs(current - previous) > thresholds['threshold_defekt']
    
    def is_trend_reversal(self, diff_curr: float, diff_prev: float, dt: datetime, param: str) -> bool:
        """
        NAPRAWIONE (wydajność - profiler pokazał 1,27s/2,19s analyze() tutaj):
        wcześniej przyjmowało cały wycinek `series` (df[param].iloc[okno]) i
        liczyło `series.diff()` NA NOWO przy każdym z ~3585 wywołań
        (5 parametrów x liczba wierszy) - tworzenie nowego obiektu pandas
        Series na tak małym wycinku ma nieproporcjonalnie duży narzut wobec
        samej operacji. `diff.iloc[-1]`/`diff.iloc[-2]` zależą WYŁĄCZNIE od
        3 ostatnich surowych wartości kolumny (idx, idx-1, idx-2) - rozmiar
        okna (idx-5..idx w wywołującym kodzie) nigdy na nie nie wpływał, więc
        wołający liczy teraz `df[param].diff()` RAZ na cały parametr (5
        wywołań zamiast ~3585) i przekazuje tu gotowe dwie liczby.
        Zachowanie identyczne jak poprzednio: porównania na NaN (gdy diff
        jeszcze niezdefiniowany) naturalnie dają False, bez potrzeby
        jawnego sprawdzania (oryginalny warunek `is not None` był zresztą
        bez znaczenia dla float NaN - `np.nan is not None` to zawsze True).
        """
        sign_change = (diff_curr > 0) != (diff_prev > 0)
        thresholds = self.get_thresholds(dt, param)
        return bool(sign_change and abs(diff_curr) > thresholds['threshold_skret'])
