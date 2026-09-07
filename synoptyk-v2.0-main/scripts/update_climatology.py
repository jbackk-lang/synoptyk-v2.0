# scripts/update_climatology.py
import pandas as pd
from data.fetcher import WeatherFetcher
from data.cache import WeatherCache

def update_climatology(station="krakow_balice", lat=50.083, lon=19.917):
    fetcher = WeatherFetcher(lat, lon)
    cache = WeatherCache()
    
    # Pobierz dane z lat 2020-2025
    dfs = []
    for year in range(2020, 2026):
        try:
            df = fetcher.fetch_hourly(f"{year}-01-01", f"{year}-12-31")
            df['month'] = pd.to_datetime(df['datetime']).dt.month
            dfs.append(df)
        except Exception as e:
            print(f"⚠️ Błąd dla roku {year}: {e}")
    
    if not dfs:
        print("❌ Brak danych do aktualizacji norm.")
        return
    
    df_all = pd.concat(dfs, ignore_index=True)
    
    # Oblicz normy
    normy = []
    for param in ['temp', 'pressure', 'humidity', 'wind_speed']:
        for month in range(1, 13):
            subset = df_all[df_all['month'] == month][param].dropna()
            if len(subset) > 0:
                normy.append({
                    'station': station,
                    'month': month,
                    'param': param,
                    'mean': subset.mean(),
                    'std': subset.std(),
                    'p10': subset.quantile(0.1),
                    'p90': subset.quantile(0.9),
                    'updated_at': pd.Timestamp.now().isoformat()
                })
    
    if normy:
        df_norm = pd.DataFrame(normy)
        cache.save_climatology(df_norm)
        print(f"✅ Normy klimatyczne dla {station} zaktualizowane.")
    else:
        print("⚠️ Nie obliczono żadnych norm.")
    
    cache.close()
