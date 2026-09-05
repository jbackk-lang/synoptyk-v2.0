# analyzer/timdr_analyzer.py
import pandas as pd
from .adaptive_thresholds import AdaptiveThresholds
from .wind_analyzer import WindAnalyzer

# Próg K domyślny sygnału 'rezonans' (>= K jednocześnie anomalnych
# parametrów). Wydzielony jako stała (zamiast "3" wpisanego wprost w
# analyze()), żeby dało się go skalibrować na realnych danych - patrz
# forecaster/resonance_calibration.py:calibrate_resonance oraz
# TIMDRAnalyzer.from_calibrated() niżej.
DEFAULT_RESONANCE_K = 3


class TIMDRAnalyzer:
    def __init__(self, station="krakow_balice", resonance_k: int = DEFAULT_RESONANCE_K):
        """
        resonance_k: próg K sygnału 'rezonans' (ile parametrów musi być
        anomalnych JEDNOCZEŚNIE, żeby uznać dzień/wiersz za rezonansowy -
        patrz `analyze()` niżej). Domyślnie 3 (zastane zachowanie, sprzed
        wprowadzenia kalibracji). Użyj `from_calibrated()`, żeby zbudować
        instancję z progiem wyliczonym na realnych danych.
        """
        self.thresholds = AdaptiveThresholds(station)
        self.resonance_k = resonance_k

    @classmethod
    def from_calibrated(cls, csv_path: str, station: str = "krakow_balice",
                         min_samples_per_group: int = 8) -> tuple["TIMDRAnalyzer", dict]:
        """
        Buduje TIMDRAnalyzer, którego próg K rezonansu jest skalibrowany na
        realnych danych z `csv_path` (forecaster/resonance_calibration.py:
        calibrate_resonance -> `recommended_k`). Zwraca (instancja,
        wynik_kalibracji); przy `wynik_kalibracji["status"] ==
        "insufficient_data"` instancja i tak dostaje bezpieczny domyślny
        próg DEFAULT_RESONANCE_K (brak zmiany zachowania).

        Import `forecaster.resonance_calibration` jest lokalny (nie na
        szczycie pliku) celowo - TIMDRAnalyzer sam w sobie nie ma twardej
        zależności od pakietu forecaster/pandas-CSV-IO, dopóki nikt
        faktycznie nie prosi o kalibrację.
        """
        from forecaster.resonance_calibration import DEFAULT_K, calibrate_resonance

        result = calibrate_resonance(csv_path, station=None, k=DEFAULT_K,
                                      min_samples_per_group=min_samples_per_group)
        k = result.get("recommended_k", DEFAULT_RESONANCE_K)
        return cls(station=station, resonance_k=k), result

    def analyze(self, df: pd.DataFrame) -> dict:
        results = {
            'skręt': [],
            'anomalia': [],
            'rezonans': [],
            'defekt': []
        }

        # NAPRAWIONE: gdy climatology/cache są puste (normalny stan dla
        # gui_app.py), get_thresholds() liczy statystyki na żywo z
        # fallback_df zamiast bezwarunkowo zwracać {mean:0, std:1, low:-2,
        # high:2} - patrz komentarz w adaptive_thresholds.py __init__.
        # Ustawiamy tu, bo to samo df, które analizujemy, jest jedynymi
        # danymi jakie mamy do dyspozycji jako baza kalibracji.
        self.thresholds.fallback_df = df

        # Dodatkowa analiza wiatru
        wind = WindAnalyzer(df)
        wind_sudden = wind.sudden_direction_change()
        if wind_sudden:
            results['defekt'].append(('wind_dir', 'nagła zmiana kierunku', None))
        
        # DODANE: 'precip' było pominięte - anomalia/defekt/rezonans/skręt
        # liczyły się dla temp/pressure/humidity/wind_speed, ale nigdy dla
        # opadów, mimo że to one najbardziej potrzebują wykrywania anomalii
        # zamiast (nieistniejącego tu i tak) trendu - opad jest zjawiskiem
        # progowym/skokowym, więc is_anomaly()/is_defect() (progi z rozstępu
        # p10-p90, nie z liniowej ekstrapolacji) pasują do niego dobrze,
        # w odróżnieniu od np. SynoptykV4.forecast()/_blend_weight() w
        # gui_app.py, które celowo NIE są stosowane do opadów.
        params = ['temp', 'pressure', 'humidity', 'wind_speed', 'precip']

        # NAPRAWIONE (wydajność - profiler: 1,27s/2,19s analyze() w "skręt"):
        # `diff.iloc[-1]`/`diff.iloc[-2]` używane niżej zależą wyłącznie od
        # 3 ostatnich surowych wartości kolumny, nie od rozmiaru okna - więc
        # liczymy `.diff()` RAZ na cały parametr (5 wywołań), zamiast tworzyć
        # nowy obiekt Series i liczyć .diff() od nowa przy KAŻDYM z ~3585
        # wywołań (5 parametrów x liczba wierszy z idx>=3). Patrz też
        # adaptive_thresholds.py:is_trend_reversal - zmieniony sygnaturowo
        # z (series, dt, param) na (diff_curr, diff_prev, dt, param).
        diffs = {param: df[param].diff().to_numpy() for param in params if param in df.columns}

        for idx, row in df.iterrows():
            dt = pd.to_datetime(row['datetime'])

            anomalies_today = []
            for param in params:
                value = row.get(param)
                if pd.isna(value):
                    continue

                # 1. Anomalia
                if self.thresholds.is_anomaly(value, dt, param):
                    results['anomalia'].append((dt, param, value))
                    anomalies_today.append(param)

                # 2. Defekt (skok)
                if idx > 0:
                    prev_value = df[param].iloc[idx-1]
                    if self.thresholds.is_defect(value, prev_value, dt, param):
                        results['defekt'].append((dt, param, value))

            # 3. Rezonans – zgodność co najmniej K parametrów (domyślnie 3,
            # patrz DEFAULT_RESONANCE_K / self.resonance_k - kalibrowalne,
            # patrz from_calibrated() i forecaster/resonance_calibration.py)
            if len(anomalies_today) >= self.resonance_k:
                results['rezonans'].append((dt, anomalies_today))

            # 4. Skręt trendu (potrzebuje okna) - patrz komentarz przy `diffs` wyżej
            if idx >= 3:
                for param in params:
                    if param not in diffs:
                        continue
                    diff_curr = diffs[param][idx]
                    diff_prev = diffs[param][idx - 1]
                    if self.thresholds.is_trend_reversal(diff_curr, diff_prev, dt, param):
                        results['skręt'].append((dt, param, df[param].iloc[idx]))

        return results
