# analyzer/adaptive_thresholds.py
import pandas as pd
import numpy as np
from datetime import datetime
from data.cache import WeatherCache


class _LooThresholdMap:
    """Wynik get_thresholds() dla gałęzi fallback PO naprawie Pattern B:
    zamiast jednego progu dzielonego przez cały (month, param), trzyma
    słownik {klucz_wiersza: próg}, jeden próg leave-one-out na wiersz -
    patrz duży komentarz "NAPRAWIONE" w AdaptiveThresholds.get_thresholds.
    `use_timestamp_key=True`, gdy klucze to pd.Timestamp (kolumna
    'datetime' dostępna) - `lookup(dt)` normalizuje wtedy `dt` tym samym
    sposobem przed odpytaniem słownika."""

    def __init__(self, loo_map: dict, degenerate: dict, use_timestamp_key: bool):
        self._loo_map = loo_map
        self._degenerate = degenerate
        self._use_timestamp_key = use_timestamp_key

    def lookup(self, dt) -> dict:
        key = pd.Timestamp(dt) if self._use_timestamp_key else dt
        return self._loo_map.get(key, self._degenerate)


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
    
    @staticmethod
    def _degenerate_result() -> dict:
        return {'mean': 0, 'std': 1, 'low': -2, 'high': 2, 'p10': -1, 'p90': 1,
                'threshold_skret': 1, 'threshold_defekt': 1}

    @staticmethod
    def _build_result(mean, std, p10, p90) -> dict:
        if pd.isna(std) or std == 0:
            std = 1.0  # n=1 albo stala wartosc w oknie - unikamy low==high
        return {
            'mean': mean,
            'std': std,
            'low': mean - 2 * std,
            'high': mean + 2 * std,
            'p10': p10,
            'p90': p90,
            'threshold_skret': 1.5 * std if std > 0 else 1.0,
            'threshold_defekt': 0.3 * (p90 - p10) if (p90 - p10) > 0 else 1.0,
        }

    def get_thresholds(self, dt: datetime, param: str) -> dict:
        """
        NAPRAWIONE (Pattern B - maskowanie przez samo-odnoszące się okno,
        znalezione przy audycie ekosystemu TIMDR pod kątem progów liczonych
        z tej samej próbki, która się testuje - ten sam mechanizm co w
        potomnych repo SYNOPTYK-ARCTIC/arctic_synoptyk/resonance.py
        :flag_resonance_days, forecaster/resonance_calibration.py
        :_flag_resonance_days i FLIGHT-TRACKING-TIMDR/timdr_flight.py
        :twist_3d - to jest PIERWOTNE (ancestor) miejsce tego wzorca w
        ekosystemie, więc naprawa jest tu najważniejsza mimo najbardziej
        złożonej implementacji):

        Gałąź "brak klimatologii" liczyła RAZ mean/std per (month, param) na
        CAŁYM `df_recent`/`fallback_df` i dzieliła ten SAM próg między
        WSZYSTKIE wiersze tego miesiąca - czyli wartość ocenianego wiersza
        sama współtworzyła próg, którym była oceniana (a `fallback_df` to
        dosłownie "ten sam df, który i tak jest analizowany" - patrz
        `analyzer/timdr_analyzer.py:analyze()`). Przy krótkim oknie
        (użytkownik GUI może ustawić suwak "Historia (dni)" nisko) genuinny
        duży skok mógł zawyżyć własne std na tyle, że nigdy nie przekroczył
        progu.

        Naprawiono: gałąź fallback liczy teraz próg PER WIERSZ metodą
        leave-one-out (mean/std z pominięciem tego konkretnego wiersza),
        wektorowo przez sumy/sumy kwadratów (ta sama technika co w
        forecaster/resonance_calibration.py:_flag_resonance_days - patrz
        tam po wyprowadzenie wzoru), więc amortyzowany koszt per wywołanie
        `get_thresholds()` pozostaje O(1) (cache nadal trzyma WYNIK
        policzony raz na (month, param), tylko teraz jest to slownik
        {timestamp: próg}, nie pojedynczy próg) - nie cofa to wcześniejszej
        naprawy wydajności opisanej w __init__.

        UCZCIWE OGRANICZENIE (świadomie NIE naprawione tutaj): `p10`/`p90`
        (i pochodny `threshold_defekt`) NADAL liczone są z całego okna
        WŁĄCZNIE z ocenianym wierszem - kwantyle 10/90 percentyla są dużo
        mniej podatne na zawyżenie przez pojedynczy punkt niż mean/std
        (jeden punkt rzadko przesuwa 10. czy 90. percentyl), więc ryzyko
        maskowania jest tu wyraźnie mniejsze niż dla mean±2*std - ale nie
        zerowe przy bardzo małych oknach. Gałąź klimatologii (dane
        historyczne, nie to samo okno co analizowane) NIE jest tu
        zmieniana - nie jest samo-odnosząca się w tym samym sensie.
        """
        month = dt.month
        cache_key = (month, param)
        cached = self._thresholds_cache.get(cache_key)
        if cached is not None:
            if isinstance(cached, _LooThresholdMap):
                return cached.lookup(dt)
            return cached

        if (month, param) in self.climatology.index:
            row = self.climatology.loc[(month, param)]
            result = self._build_result(row['mean'], row['std'], row['p10'], row['p90'])
            self._thresholds_cache[cache_key] = result
            return result

        df_recent = self.cache.load_last_n_days(30)
        if df_recent.empty or param not in df_recent.columns:
            df_recent = self.fallback_df
        if df_recent is None or df_recent.empty or param not in df_recent.columns:
            result = self._degenerate_result()
            self._thresholds_cache[cache_key] = result
            return result

        if 'datetime' not in df_recent.columns:
            # Bez kolumny 'datetime' nie ma jak dopasowac progu LOO do
            # konkretnego wiersza (klucz musialby byc pozycyjnym indeksem,
            # ktory nie odpowiada `dt` przekazywanemu do get_thresholds) -
            # w praktyce nieosiagalne (oba zrodla df_recent - WeatherCache.
            # load_last_n_days i analyze()'s wlasne `df` - zawsze maja te
            # kolumne, patrz data/cache.py:_init_db i testy), ale
            # bezpieczniej jawnie zwrocic prog domyslny niz cicho policzyc
            # go zle.
            result = self._degenerate_result()
            self._thresholds_cache[cache_key] = result
            return result

        dt_col = pd.to_datetime(df_recent['datetime'])
        month_mask = dt_col.dt.month == month
        series = df_recent.loc[month_mask, param]
        valid = series.dropna()
        n = len(valid)
        if n < 4:
            # Za mało punktów, żeby LOO (n'=n-1 musi być >=3) miało sens -
            # ten sam próg minimalnej próbki co gdzie indziej w ekosystemie.
            result = self._degenerate_result()
            self._thresholds_cache[cache_key] = result
            return result

        p10 = valid.quantile(0.1)
        p90 = valid.quantile(0.9)

        s1, s2 = valid.sum(), (valid ** 2).sum()
        n_loo = n - 1
        mean_loo = (s1 - valid) / n_loo
        var_loo = ((s2 - valid ** 2) - (s1 - valid) ** 2 / n_loo) / (n_loo - 1)
        var_loo = var_loo.clip(lower=0)
        std_loo = var_loo.pow(0.5)

        keys = dt_col.loc[valid.index].map(pd.Timestamp)
        loo_map = {
            key: self._build_result(mean_loo.loc[i], std_loo.loc[i], p10, p90)
            for i, key in keys.items()
        }
        result_map = _LooThresholdMap(loo_map, self._degenerate_result(), use_timestamp_key=True)
        self._thresholds_cache[cache_key] = result_map
        return result_map.lookup(dt)
    
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
