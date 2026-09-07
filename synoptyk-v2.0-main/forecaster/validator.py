# forecaster/validator.py
"""
Moduł walidacji prognoz – porównuje prognozę z danymi rzeczywistymi po ich nadejściu.
"""

import pandas as pd
from datetime import datetime, timedelta

class ForecastValidator:
    def __init__(self, forecast_data: dict, actual_data: pd.DataFrame):
        self.forecast = forecast_data
        self.actual = actual_data
    
    def validate(self, param: str, metric: str = "mae") -> dict:
        """
        Waliduje prognozę dla danego parametru.
        metryki: 'mae' (mean absolute error), 'rmse' (root mean squared error)
        """
        if param not in self.forecast:
            return {"error": f"Brak prognozy dla {param}"}
        
        # Dane rzeczywiste dla okresu prognozy
        forecast_dates = self.forecast[param]['dates']
        if not forecast_dates:
            return {"error": "Brak dat w prognozie"}
        
        start_date = forecast_dates[0] - timedelta(days=1)
        end_date = forecast_dates[-1]
        
        actual_subset = self.actual[
            (self.actual['datetime'] >= start_date) &
            (self.actual['datetime'] <= end_date)
        ]
        
        if actual_subset.empty:
            return {"error": "Brak danych rzeczywistych do walidacji"}
        
        # Pobierz prognozę i rzeczywiste w tych samych punktach czasowych
        forecast_values = self.forecast[param]['forecast']
        actual_values = []
        matched_dates = []
        
        for dt in forecast_dates:
            if dt in actual_subset['datetime'].values:
                actual_values.append(actual_subset[actual_subset['datetime'] == dt][param].values[0])
                matched_dates.append(dt)
        
        if not actual_values:
            return {"error": "Brak dopasowanych dat"}
        
        # Obetnij prognozę do liczby dopasowanych dat
        forecast_values = forecast_values[:len(actual_values)]
        
        # Oblicz metryki
        errors = [abs(f - a) for f, a in zip(forecast_values, actual_values)]
        mae = sum(errors) / len(errors)
        
        rmse = (sum((f - a) ** 2 for f, a in zip(forecast_values, actual_values)) / len(errors)) ** 0.5
        
        return {
            'param': param,
            'mae': mae,
            'rmse': rmse,
            'matched_dates': len(matched_dates),
            'actual_values': actual_values,
            'forecast_values': forecast_values,
            'errors': errors
        }
