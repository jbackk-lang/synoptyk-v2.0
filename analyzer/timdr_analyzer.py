# analyzer/timdr_analyzer.py
import pandas as pd
from .adaptive_thresholds import AdaptiveThresholds
from .wind_analyzer import WindAnalyzer

class TIMDRAnalyzer:
    def __init__(self, station="krakow_balice"):
        self.thresholds = AdaptiveThresholds(station)
    
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
        for idx, row in df.iterrows():
            dt = pd.to_datetime(row['datetime'])
            params = ['temp', 'pressure', 'humidity', 'wind_speed', 'precip']
            
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
            
            # 3. Rezonans – zgodność co najmniej 3 parametrów
            if len(anomalies_today) >= 3:
                results['rezonans'].append((dt, anomalies_today))
            
            # 4. Skręt trendu (potrzebuje okna)
            if idx >= 3:
                for param in params:
                    series = df[param].iloc[max(0, idx-5):idx+1]
                    if len(series) >= 3 and self.thresholds.is_trend_reversal(series, dt, param):
                        results['skręt'].append((dt, param, series.iloc[-1]))
        
        return results
