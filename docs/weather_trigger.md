# WeatherTrigger — czujnik sygnałowy nad SynoptykV4

`analyzer/weather_trigger.py` — **czujnik** (NIE model, NIE prognoza): `WeatherTrigger`, dispatcher nad `fronts()`/`anomalies()`/`twist()`/`circular_anomalies()` z `SynoptykV4` (patrz [`v4_forecast.md`](v4_forecast.md)), które były dotąd całkowicie osierocone w tej aplikacji (używane tylko we własnych testach — `api/main.py` korzysta z innego modułu, `gui_app.py` woła z `SynoptykV4` tylko `forecast()`).

## Po co jest

WeatherTrigger wykrywa **zdarzenia w danych historycznych** (skręt/anomalia/front). To nie jest prognoza na przyszłość — informuje o zmianie reżimu w historii, nie o przyszłej pogodzie.

## Priorytet zdarzeń

`FRONT` (twist i anomalia się zgadzają) > `ANOMALY` (pojedynczy potwierdzony sygnał, także `circular_anomalies()` dla kierunku wiatru) > `TWIST` (samo, najbardziej szumiące) > `NONE`.

## Gdzie to widać w GUI

Wpięty do `gui_app.py` — zgłasza się do **Dziennika** (nie jako kolejna kolumna tabeli, żeby nie powtórzyć błędu z usuniętej kolumny "typ" TIMDR — kolumna, która przy oryginalnym progu opadu była praktycznie zawsze aktywna i nie odróżniała niczego).

## Jak czytać wynik

`result.trigger_type` — który typ zdarzenia (`FRONT`/`ANOMALY`/`TWIST`/`NONE`). `result.channel` — w którym kanale danych (np. temperatura, ciśnienie, wiatr). `result.location` — indeks/pozycja w historii. `result.message` — czytelny opis.

## Testy

`analyzer/test_weather_trigger.py` (8 testów, 31/31 łącznie z V4).

## Przykład

```python
from analyzer import WeatherTrigger

trigger = WeatherTrigger()
result = trigger.analyze(t, {"temp": temp, "pressure": pressure})
print(result.trigger_type, result.channel, result.location, result.message)
```
