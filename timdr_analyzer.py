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
        
        # Dodatkowa analiza wiatru
        wind = WindAnalyzer(df)
        wind_sudden = wind.sudden_direction_change()
        if wind_sudden:
            results['defekt'].append(('wind_dir', 'nagła zmiana kierunku', None))
        
        for idx, row in df.iterrows():
            dt = pd.to_datetime(row['datetime'])
            params = ['temp', 'pressure', 'humidity', 'wind_speed']
            
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
