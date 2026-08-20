# data_prep.py
import pandas as pd
import numpy as np

def ensure_synoptic_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Gwarantuje, że DataFrame posiada wszystkie wymagane kolumny 
    oraz poprawny indeks czasowy dla silnika Synoptyk-F / TIMDR.
    """
    if df is None or df.empty:
        # Zwróć pustą ramkę z wymaganymi kolumnami
        return pd.DataFrame(columns=['time', 'temperature', 'humidity', 'pressure', 'month', 'param'])

    df = df.copy()

    # 1. Standaryzacja indeksu czasowego
    if not isinstance(df.index, pd.DatetimeIndex):
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'])
            df.set_index('time', inplace=True)
        elif 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
        else:
            # Tworzenie sztucznego indeksu czasowego jeśli brak
            df.index = pd.date_range(end=pd.Timestamp.now(), periods=len(df), freq='h')

    # 2. Mapowanie nazwy kolumny temperatury
    if 'temperature' not in df.columns:
        for col in ['temperature_2m', 'temp', 't2m', 'temp_c']:
            if col in df.columns:
                df['temperature'] = df[col]
                break
        if 'temperature' not in df.columns:
            # Pobierz pierwszą kolumnę numeryczną jako temperaturę
            num_cols = df.select_dtypes(include=[np.number]).columns
            if len(num_cols) > 0:
                df['temperature'] = df[num_cols[0]]
            else:
                df['temperature'] = 0.0

    # 3. GWARANCJA KLUCZOWYCH KOLUMN ZGLASZAJĄCYCH BŁĄD
    if 'month' not in df.columns:
        df['month'] = df.index.month

    if 'param' not in df.columns:
        df['param'] = 'temperature'

    if 'humidity' not in df.columns:
        df['humidity'] = df.get('relative_humidity_2m', 50.0)

    if 'pressure' not in df.columns:
        df['pressure'] = df.get('surface_pressure', 1013.25)

    return df