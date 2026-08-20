# analyzer/wind_analyzer.py
import pandas as pd
import numpy as np
from math import atan2, degrees, radians

class WindAnalyzer:
    def __init__(self, df: pd.DataFrame):
        """
        Inicjalizacja analizatora wiatru.
        df – DataFrame z kolumnami: datetime, wind_speed, wind_dir
        """
        self.df = df
    
    def average_direction(self, hours: int = 24) -> float:
        """
        Oblicza średni kierunek wiatru z ostatnich N godzin.
        Zwraca kąt w stopniach (0–360).
        """
        subset = self.df.tail(hours)
        if subset.empty:
            return 0.0
        
        # Średnia wektorowa
        u = np.mean(np.sin(radians(subset['wind_dir'])))
        v = np.mean(np.cos(radians(subset['wind_dir'])))
        return (degrees(atan2(u, v)) + 360) % 360
    
    def average_speed(self, hours: int = 24) -> float:
        """Średnia prędkość wiatru z ostatnich N godzin."""
        subset = self.df.tail(hours)
        return subset['wind_speed'].mean()
    
    def sudden_direction_change(self, threshold: float = 90, window: int = 3) -> bool:
        """
        Wykrywa nagłą zmianę kierunku o >threshold stopni w ciągu window godzin.
        """
        dirs = self.df['wind_dir'].values
        if len(dirs) < window + 1:
            return False
        
        changes = np.abs(np.diff(dirs))
        for i in range(len(changes) - window + 1):
            if np.all(changes[i:i+window] > threshold):
                return True
        return False
    
    def wind_rose_data(self, bins: int = 16) -> pd.DataFrame:
        """
        Generuje dane dla róży wiatrów.
        Dzieli kierunki na przedziały i oblicza średnią prędkość oraz liczbę pomiarów.
        """
        df = self.df.copy()
        # Podział na przedziały kierunkowe
        bin_edges = np.linspace(0, 360, bins + 1)
        labels = [f"{int(bin_edges[i])}-{int(bin_edges[i+1])}" for i in range(bins)]
        df['dir_bin'] = pd.cut(df['wind_dir'], bins=bin_edges, labels=labels, include_lowest=True)
        
        result = df.groupby('dir_bin', observed=False).agg({
            'wind_speed': 'mean',
            'wind_dir': 'count'
        }).rename(columns={'wind_dir': 'count'})
        
        return result
    
    def detect_front(self) -> dict:
        """
        Wykrywa front atmosferyczny na podstawie wiatru i innych parametrów.
        Zwraca słownik z informacją o froncie i jego typem.
        """
        # Prosta heurystyka: nagły wzrost wiatru + zmiana kierunku + spadek ciśnienia
        if len(self.df) < 6:
            return {'front': False, 'type': 'brak danych'}
        
        wind_increase = self.df['wind_speed'].diff().tail(3).mean() > 1.5
        direction_shift = self.sudden_direction_change(threshold=60, window=2)
        pressure_drop = self.df['pressure'].diff().tail(3).mean() < -0.5
        
        if wind_increase and direction_shift and pressure_drop:
            return {'front': True, 'type': 'zimny front'}
        elif wind_increase and direction_shift:
            return {'front': True, 'type': 'front (nieokreślony)'}
        else:
            return {'front': False, 'type': 'brak'}
