# Silniki prognozy — szczegóły

Zobacz też sekcję „Hierarchia silników” w [`../README.md`](../README.md) po krótkie zestawienie. Ten plik to rozwinięcie — który silnik robi co, na jakich danych, i jak dokładnie.

## Tabela silników

| Silnik | Plik | Dane wejściowe | Metoda | Wynik |
|---|---|---|---|---|
| `TIMDRForecast` | `forecaster/timdr_forecast.py` | pełen szereg godzinowy | regresja + sygnały TIMDR | forecast + pasmo [lower, upper] |
| `SynoptykFEngine` | `synoptyk_f.py` | temperatura + wilgotność | filtr falkowy db4 + korekta UHI | point + pasmo |
| `synoptyk_v2` | `synoptyk/compare.py` + `trend.py` | dane rzeczywiste + ECMWF + ICON | analiza Δ + trend | ΔT, ΔPrec, ΔWind, ΔPressure |
| `SynoptykV3` | `analyzer/synoptyk_v3.py` | dowolny szereg 1D (t, s) | lokalna regresja LSQ (KDTree) + mediana + autokorelacja | gradient, twist, wygładzenie, cykle, anomalie, fronty |
| `SynoptykV4` | `analyzer/synoptyk_v4.py` | dowolny szereg 1D (t, s); wiatr: prędkość (t, s) + kierunek (t, stopnie 0–360) | j.w. + tłumiona ekstrapolacja trendu (mean reversion) | gradient, twist, wygładzenie, anomalie, fronty, `forecast()`, `forecast_wind_speed()`, `forecast_wind_direction()`, `circular_anomalies()` |

Domyślny silnik GUI to `SynoptykFEngine` (filtr falkowy) z prognozą z Open-Meteo Forecast API. `SynoptykV4.forecast()` jest liczony **równolegle** i pokazywany obok w osobnej kolumnie `V4 °C` (czysty, niezmieszany wynik — do porównania z rzeczywistymi pomiarami), a jednocześnie **ten sam** `forecast()` (na temperaturze, ciśnieniu i wietrze) miesza się z głównymi kolumnami na dalekim horyzoncie (+3d i dalej) — pełne wyjaśnienie mieszania i wiatru w [`v4_forecast.md`](v4_forecast.md).

`TIMDRForecast` i `synoptyk_v2` (`synoptyk/compare.py`/`trend.py`) **nie są używane przez `gui_app.py`** (zero importów) — pozostają jako samodzielne, dostępne przez CLI/API tory, nie przez GUI.

## SynoptykV3 — analiza sygnałów (samodzielny moduł)

`analyzer/synoptyk_v3.py` to zestaw lokalnych analiz szeregu czasowego oparty o k najbliższych sąsiadów w czasie (KDTree): `flow` (lokalny gradient LSQ), `twist` (nagłe zmiany kierunku), `trm` (medianowe wygładzenie), `trend` (globalny dryf), `rhythm` (autokorelacja znormalizowana względem malejącego nakładania się próbek przy rosnącym opóźnieniu), `anomalies` (MAD względem TRM) i `fronts` (punkty, gdzie jednocześnie występuje silny twist i anomalia, dopasowane z tolerancją indeksową).

**Nie jest podpięty do `forecaster/timdr_forecast.py`** — ten korzysta z osobnego `analyzer/timdr_analyzer.py` (inny format: DataFrame + krotki `'skręt'/'anomalia'/'rezonans'/'defekt'`), podczas gdy `SynoptykV3` pracuje na surowych tablicach `(t, s)` i zwraca indeksy/tablice numpy. Integracja wymagałaby osobnego adaptera.

16 testów w `analyzer/test_synoptyk_v3.py` (pytest).

**Znane ograniczenie**: `flow()`/`trm()` przy liczbie próbek `n` mieszczącej się w `k_neighbors` (domyślnie 12) cicho degenerują lokalną analizę do jednej globalnej regresji/mediany dla całego okna — sąsiedztwo każdego punktu to wtedy cały zbiór. Kod ostrzega `RuntimeWarning`, ale nie naprawia tego automatycznie; dla krótkich okien zmniejsz `k_neighbors` albo zwiększ liczbę próbek. To samo dotyczy `SynoptykV4` (domyślnie `k_neighbors=8`).

## SynoptykV4 — jak V3, plus forecast() i wiatr

Ten sam rdzeń co V3 (`flow`/`twist`/`trm`/`anomalies`/`fronts`, inna implementacja twist/anomalies — z-score po MAD drugiej pochodnej/residuów), plus `forecast()`/wiatr — pełne szczegóły w [`v4_forecast.md`](v4_forecast.md).

23 testy w `analyzer/test_synoptyk_v4.py` (pytest). Domyślne progi (`twist_factor=3.5`, `anomaly_factor=3.0`) mogą nie wykryć bardzo łagodnych, rozłożonych w czasie frontów — są parametrami, obniżenie ich zwiększa czułość kosztem fałszywych alarmów na czystym szumie (zmierzone: ~1% przy domyślnych progach, ~13–27% przy obniżonych do 2.0).

## Analiza sygnałów TIMDR (`analyzer/timdr_analyzer.py`)

Liczone z danych historycznych pobranych przez `_fetch_historical()` (adaptowane przez `_adapt_for_timdr()` w `gui_app.py`), ale **nie są pokazywane w tabeli GUI** — przez czułość progu opadu sygnał praktycznie zawsze wychodzi aktywny, więc w praktyce nie odróżniał nic od niczego. Progi kalibrowane na żywo z tego samego okna danych, gdy `weather_cache.db`/klimatologia są puste (`AdaptiveThresholds.fallback_df` — patrz [`fallbacks.md`](fallbacks.md) po znane ograniczenie tego mechanizmu). `AdaptiveThresholds.get_thresholds()` cache'uje wynik per `(miesiąc, parametr)` na czas życia obiektu.

## WeatherTrigger — czujnik nad SynoptykV4

Osobny dokument: [`weather_trigger.md`](weather_trigger.md).

## Inne znane ograniczenia silników

- `topomap_data.py` zawiera pełne metadane tylko dla 7 miast (Warszawa, Kraków, Gdańsk, Wrocław, Poznań, Katowice, Zakopane). Pozostałe miasta używają domyślnych wartości `lat=52.0, lon=19.0` (fallback ze środka Polski) — patrz `get_node_metadata()`.
- `forecaster/validator.py` implementuje MAE i RMSE, ale walidacja out-of-sample nie jest uruchamiana automatycznie.
