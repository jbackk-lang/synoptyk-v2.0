import pandas as pd

def compare(real_df, model_df):
    merged = real_df.merge(model_df, on="time", suffixes=("_real", "_model"))
    merged["ΔT"] = merged["temp_real"] - merged["temp_model"]
    merged["ΔPrec"] = merged["precip_real"] - merged["precip_model"]
    merged["ΔWind"] = merged["wind_real"] - merged["wind_model"]
    merged["ΔPressure"] = merged["pressure_real"] - merged["pressure_model"]
    return merged
