# 🌪️ Synoptyk v2.0

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Dane: Open-Meteo](https://img.shields.io/badge/dane-Open--Meteo-0ea5e9)](https://open-meteo.com/)

Wielodniowa prognoza pogody dla Polski i wybranych regionów USA, oparta na danych Open-Meteo (ECMWF/ICON), z filtrem falkowym Daubechies i opcjonalną analizą sygnałów TIMDR. Wyniki prezentowane są w GUI Gradio — każdy dzień prognozy jako osobny wiersz z temperaturą, ciśnieniem, opadami i wiatrem.

---

## Co robi

- pobiera dane historyczne (Open-Meteo Archive API) i prognozę (Open-Meteo Forecast API) bez lokalnego cache
- odszumia szereg temperatury filtrem falkowym `db4` (PyWavelets) i stosuje korektę o Miejską Wyspę Ciepła (UHI) oraz gradient termiczny wysokości
- opcjonalnie wykrywa strukturalne sygnały TIMDR (anomalia / defekt / rezonans) w danych historycznych i poszerza pasmo niepewności prognozy
- wyświetla prognozę dzienną (1–14 dni) z datami, min/śr/max temperatury, sumą opadów, średnim ciśnieniem i maksymalnym wiatrem
- ostrzega w dzienniku GUI gdy dane archiwalne są starsze niż 2 doby

---

## Szybki start

```bash
git clone https://github.com/jbackk-lang/synoptyk-v2.0.git
cd synoptyk-v2.0
pip install -r requirements.txt
python gui_app.py
# GUI dostępne pod http://127.0.0.1:7860
```

> **Windows:** zamiast ostatniej linii uruchom `run.bat` — jedno okno konsoli, przeglądarka otwiera się sama pod `http://127.0.0.1:7860` (`app.launch(..., inbrowser=True)`). Osobny serwer API (FastAPI/Uvicorn, `http://127.0.0.1:8010/docs`) GUI nie potrzebuje — jeśli jest potrzebny do czegoś innego, uruchamia się go osobno przez `run_api.bat` (port zmieniony z 8000 na 8010, żeby uniknąć kolizji z innymi lokalnymi serwerami, które często domyślnie siedzą na 8000).

---

## Wymagania

```
gradio>=4.0
numpy
pandas
pywavelets
requests
```

Pełna lista w `requirements.txt`. Nie jest wymagany klucz API — Open-Meteo jest bezpłatne.

---

## Struktura repo

```
synoptyk-v2.0/
├── gui_app.py              # główny GUI (Gradio) — wielodniowa prognoza
├── main.py                 # pipeline CLI: historia → ECMWF/ICON → Δ → trend
├── main_api.py             # REST API (FastAPI)
├── run_synoptyk.py         # CLI dla wybranych regionów
├── synoptyk_f.py           # SynoptykFEngine: filtr falkowy + korekta UHI
├── grid_engine.py          # siatka przestrzenna (opcjonalna)
├── topomap_data.py         # baza współrzędnych i metadanych 7 miast PL
│
├── data/
│   ├── fetcher.py          # WeatherFetcher — Open-Meteo Archive
│   └── cache.py            # SQLite cache (używany tylko przez fetcher.py)
│
├── data_sources/
│   ├── real_weather.py     # dane rzeczywiste godzinowe
│   ├── model_ecmwf.py      # prognoza ECMWF (IFS)
│   └── model_icon.py       # prognoza ICON-EU
│
├── analyzer/
│   ├── timdr_analyzer.py   # detekcja sygnałów TIMDR (skręt/anomalia/rezonans/defekt)
│   ├── synoptyk_v3.py      # SynoptykV3 — flow/twist/trm/trend/rhythm/anomalies/fronts (KDTree)
│   ├── synoptyk_v4.py      # SynoptykV4 — j.w. + forecast() ogólny + wiatr (prędkość/kierunek kołowy)
│   ├── adaptive_thresholds.py
│   └── wind_analyzer.py
│
├── synoptyk/
│   ├── compare.py          # porównanie modeli z rzeczywistością (ΔT, ΔPrec, ΔWind, ΔPressure)
│   └── trend.py            # trend 14-dniowy
│
├── forecaster/
│   ├── timdr_forecast.py   # TIMDRForecast — regresja + sygnały TIMDR
│   ├── synoptic_f.py
│   ├── j_compress.py
│   ├── j_decompress.py
│   └── validator.py        # MAE, RMSE, zgodność trendu
│
├── config/
│   └── config.yaml
├── scripts/
│   └── update_climatology.py
└── examples/
```

> `weather_cache.db` — plik SQLite generowany lokalnie przez `data/fetcher.py`. **Nie powinien być commitowany** (dodaj do `.gitignore`). GUI v2 pobiera dane bezpośrednio z API i nie korzysta z cache.

---

## GUI — opis panelu

| Kontrolka | Opis |
|---|---|
| Tryb | Cały region / pojedyncze miasto / **dowolny wybór miast** |
| Region | `cała_polska`, `poland_south`, `poland_north`, `poland_central`, `poland_west`, `poland_east` |
| Miasto | Lista ~40 miast PL (dropwdown) |
| Historia (dni) | Okno danych archiwalnych do filtra falkowego (3–30 dni) |
| Prognoza (dni) | Liczba dni naprzód w tabeli wyników (1–14) |
| Tryb Demo | Dane zastępcze „–" gdy brak dostępu do API |

Tabela wyników zawiera kolumny: `Stacja` (nazwa miasta, ewentualnie z dopiskiem `⚡EV`), `Data`, `Typ` (Dziś/2d/3d/…/14d), `Min °C`, `Śr °C`, `Max °C`, `Opad mm`, `Ciśn hPa`, `Wiatr km/h`, `Kier.`, `Hist. do`, `V4 °C`.

**Fallback przy padzie Open-Meteo**: jeśli żywe API (prognoza i/lub archiwum historyczne) nie odpowiada, silnik nie pomija stacji — liczy dalej na podstawie tego, co już jest zapisane dla tej stacji w `krakow_forecast_snapshots.csv` (Twoje wcześniej wklejone pulle). Takie wiersze mają w kolumnie `Typ` dopisek `⚠️FB` zamiast zwykłego znaczka korekty/dnia i nie dostają korekty obciążenia ani oznaczeń `▲`/`⚡EV` (nie mają sensownego punktu odniesienia w normalnym pipeline'ie). Jeśli dla danej stacji w CSV jest za mało danych (< 2 dni), stacja jest pomijana z komunikatem w Dzienniku — tak jak wcześniej. To osobny mechanizm od `Tryb Demo` (patrz niżej): Demo zawsze pokazuje same „–", fallback pokazuje realne liczby z historii.

**Automatyczny zapis do CSV**: każde uruchomienie (poza Trybem Demo i wierszami `⚠️FB`) dopisuje własną prognozę stacji do `krakow_forecast_snapshots.csv` samo, bez ręcznego wklejania — te same liczby, co w tabeli GUI, `source = prognoza_blending_bias`, kolejny `pull_seq` per (stacja, dzień). Żeby plik nie rósł bez końca przy wielu uruchomieniach dziennie, po każdym zapisie usuwane są wiersze starsze niż 30 dni (licząc po `target_date`) — poza wierszami `_META_` (znaczniki typu `ENGINE_BASELINE_...`), które zostają na stałe.

**Tryb „Wybór miast”** — dowolna kombinacja miast z listy (`gr.Dropdown(multiselect=True)`), niezależna od sztywnych grup w `REGIONS_MAP` (np. Kraków + Gdańsk + Warszawa naraz, mimo że są w trzech różnych regionach). Pusty wybór daje fallback na `Krakow_Centrum` z ostrzeżeniem w Dzienniku. Domyślny tryb startowy to jednak `Pojedyncze miasto`/`Krakow_Centrum` — przy trybie „Cały Region” (do 7 stacji × 14 dni = do 98 wierszy) trzeba przewijać tabelę, żeby zobaczyć wszystkie stacje.

**Kolumna `Typ`** łączy znaczek korekty obciążenia (🔴/🟠/🟢) i dzień (`Dziś`/`2d`/`3d`/…/`14d`). Skok głównego silnika (`⚡EV`) jest dopisywany do nazwy stacji w kolumnie `Stacja` (np. `Krakow_Centrum ⚡EV`), wyrównanej do prawej strony komórki.

**Korekta obciążenia** (`forecaster/bias_correction.py`, `apply_bias_correction()`): średni zmierzony błąd (rzeczywistość − prognoza) per `lead_days`, liczony na żywo z `krakow_forecast_snapshots.csv` przy każdym uruchomieniu. To NIE jest model ML — nie ma osobnego kroku treningowego, korekta po prostu "uczy się" w miarę przybywania sparowanych obserwacji w CSV.

**Porównanie trafności głównego toru i V4 z rzeczywistością**: `krakow_forecast_snapshots.csv` ma dodatkowe kolumny `v4_point_c`/`v4_lower_c`/`v4_upper_c` (punkt + pasmo `SynoptykV4.forecast()`, zapisywane od danej daty pulla w górę — starsze wiersze mają je puste). `compute_lead_bias()` przyjmuje opcjonalny `forecast_col` (domyślnie `"avg_temp_c"` - główny tor); wywołanie z `forecast_col="v4_point_c"` liczy dokładnie te same statystyki (bias/MAE per `lead_days`) dla samodzielnego toru V4. Dopóki nie ma realnych obserwacji sparowanych z wierszami po dodaniu tych kolumn, zwraca pusty słownik (brak danych, nie zero) — zacznie się wypełniać w miarę przybywania kolejnych `IMGW_real_*`/`web_szukaj_*` w CSV dla dat od 2026-08-17 w górę.

| Znaczek | Znaczenie |
|---|---|
| 🔴 | korekta jeszcze niedostępna dla tego lead_days — za mało sparowanych obserwacji prognoza/rzeczywistość w CSV (próg `min_samples=5`) |
| 🟠 | korekta aktywna, ale na małej próbce (5–14 obserwacji) — traktować orientacyjnie |
| 🟢 | korekta aktywna, solidniejsza próbka (≥15 obserwacji) |

Dziennik dodatkowo informuje o tym samym wprost (`🎯 <stacja>: korekta obciążenia jeszcze nieaktywna...` albo lista aktywnych lead_days z liczbą próbek i wielkością korekty).

**Wykrywanie skoku silnika (`⚡EV`)**: `Typ` dostaje dopisek `⚡EV`, gdy `Śr °C`/`Opad mm`/`Ciśn hPa`/`Wiatr km/h` dla tego samego dnia docelowego zmieniły się między poprzednim a bieżącym uruchomieniem GUI powyżej progu (odpowiednio 2°C / 10mm / 5hPa / 8km/h) — `detect_engine_volatility()` w `gui_app.py`. Pamięć poprzedniego pulla trzymana jest na dysku (`_last_pull_cache.json` obok `gui_app.py`, w `.gitignore`) i wczytywana przy starcie, więc przetrwa restart serwera. Przycisk „🔄 Wyczyść cache (EV)” czyści ją ręcznie (przydatne po nagromadzeniu starych wpisów z innych stacji/trybów) — nie dotyka `krakow_forecast_snapshots.csv` (osobna, celowo trwała historia dla korekty obciążenia). Po wyczyszczeniu pierwszy kolejny pull nie ma z czym się porównać, więc `⚡EV` zacznie znów działać dopiero od pulla PO NASTĘPNYM.

**Oznaczenie zmienionych wartości**: `Min/Śr/Max °C`, `Opad mm`, `Ciśn hPa`, `Wiatr km/h` — wartość, która różni się od poprzedniego pulla dla tego samego dnia/stacji, dostaje prefiks `▲` (np. `▲16.9`); niezmieniona zostaje zwykłym tekstem bez prefiksu. Pierwszy pull dla danego dnia (brak wpisu w `_last_pull_cache.json`) liczy się jako "zmienione". Pozwala na pierwszy rzut oka odróżnić świeży wynik od powtórki (np. gdy Open-Meteo jeszcze nie zaktualizowało modelu między dwoma uruchomieniami) bez wklejania tabeli do sprawdzenia.

**Sygnały TIMDR** (`anomalia`/`defekt`/`rezonans`): liczone przez `analyzer/timdr_analyzer.py` z danych historycznych pobranych przez `_fetch_historical()` (adaptowane do oczekiwanego formatu przez `_adapt_for_timdr()` w `gui_app.py`), ale nie są już pokazywane w tabeli GUI — przez czułość progu opadu sygnał praktycznie zawsze wychodzi aktywny (patrz „Znane ograniczenia”), więc nie odróżniał w praktyce nic od niczego. Progi kalibrowane na żywo z tego samego okna danych, gdy `weather_cache.db`/klimatologia są puste (patrz `AdaptiveThresholds.fallback_df`). `AdaptiveThresholds.get_thresholds()` cache'uje wynik per `(miesiąc, parametr)`/`param` na czas życia obiektu, więc te same statystyki nie są przeliczane od nowa przy każdym z wielu wywołań na wiersz.

`Kier.` — kierunek wiatru jako pojedyncza strzałka (↑↗→↘↓↙←↖, 8 kierunków), licząca **dokąd** wiatr wieje (nie skąd). Dzienna wartość to średnia wektorowa (kołowa) godzinowych odczytów — `_circular_mean_deg()` w `gui_app.py` (ten sam mechanizm co `SynoptykV4.forecast_wind_direction()`).

`V4 °C` — niezależny, eksperymentalny silnik `SynoptykV4.forecast()` (ekstrapolacja trendu z rzeczywistej historii, bez modelu Open-Meteo), pokazany **obok** głównej prognozy do porównania. Format: `punkt [dolny–górny]`.

**Stabilizacja dalekiego horyzontu**: dni 0–2 głównej prognozy (`Min/Śr/Max °C`, `Ciśn hPa`, `Wiatr km/h`) to w całości świeża odpowiedź Open-Meteo Forecast API (+ korekta UHI/lapse/falkowa). Dni +3d i dalej mieszają się z **własną deterministyczną ekstrapolacją trendu** (`SynoptykV4.forecast()` na dziennie zagregowanej historii, NIE z modelu Open-Meteo) rosnącą wagą: 0% na dniach 0–2, liniowo do 100% przy +10d i dalej — bo Open-Meteo samo przelicza swój model NWP kilka razy dziennie i na dalekim horyzoncie potrafi mocno zmieniać wartość między dwoma pobraniami tego samego dnia. Nie dotyczy `Opad mm` (trend liniowy nie pasuje do zjawiska progowego/skokowego — ta kolumna zostaje czystym przepuszczeniem z API). Zobacz `_blend_weight()`/`_own_trend_points()` w `gui_app.py`.

Ciśnienie w całym pliku (prognoza i historia) to `pressure_msl` (poziom morza), nie `surface_pressure` (stacyjne) — spójne z filtrem falkowym i porównaniami z pomiarami IMGW/AccuWeather.

---

## Obsługiwane regiony (CLI)

| Klucz | Stacje |
|---|---|
| `cała_polska` | 14 głównych miast PL |
| `poland_south` | Kraków, Tarnów, Nowy Sącz, Zakopane, Katowice, Rzeszów, Bielsko-Biała |
| `poland_north` | Gdańsk, Gdynia, Suwałki, Olsztyn, Elbląg, Koszalin, Szczecin |
| `poland_central` | Warszawa, Łódź, Radom, Płock, Częstochowa, Kielce |
| `poland_west` | Poznań, Wrocław, Szczecin, Zielona Góra, Gorzów Wlkp. |
| `poland_east` | Lublin, Białystok, Zamość, Przemyśl, Siedlce |
| `usa_northeast` | New York City, Boston, Philadelphia, Baltimore, Hartford |
| `usa_west` | Los Angeles, San Francisco, Seattle, Portland OR, Las Vegas |

---

## Silniki prognozy

| Silnik | Plik | Dane wejściowe | Metoda | Wynik |
|---|---|---|---|---|
| `TIMDRForecast` | `forecaster/timdr_forecast.py` | pełen szereg godzinowy | regresja + sygnały TIMDR | forecast + pasmo [lower, upper] |
| `SynoptykFEngine` | `synoptyk_f.py` | temperatura + wilgotność | filtr falkowy db4 + korekta UHI | point + pasmo |
| `synoptyk_v2` | `synoptyk/compare.py` + `trend.py` | dane rzeczywiste + ECMWF + ICON | analiza Δ + trend | ΔT, ΔPrec, ΔWind, ΔPressure |
| `SynoptykV3` | `analyzer/synoptyk_v3.py` | dowolny szereg 1D (t, s) | lokalna regresja LSQ (KDTree) + mediana + autokorelacja | gradient, twist, wygładzenie, cykle, anomalie, fronty |
| `SynoptykV4` | `analyzer/synoptyk_v4.py` | dowolny szereg 1D (t, s); wiatr: prędkość (t, s) + kierunek (t, stopnie 0–360) | j.w. + tłumiona ekstrapolacja trendu (mean reversion) | gradient, twist, wygładzenie, anomalie, fronty, `forecast()` (point/lower/upper) dla dowolnej zmiennej, `forecast_wind_speed()`, `forecast_wind_direction()` (kołowa, spread w stopniach), `circular_anomalies()` |

Domyślny silnik GUI to `SynoptykFEngine` (filtr falkowy) z prognozą z Open-Meteo Forecast API. `SynoptykV4.forecast()` jest liczony **równolegle** i pokazywany obok w osobnej kolumnie `Temp śr V4 [°C]` (czysty, niezmieszany wynik — do porównania przez kilka dni z rzeczywistymi pomiarami), a jednocześnie **ten sam** `forecast()` (na temperaturze, ciśnieniu i wietrze) miesza się z głównymi kolumnami na dalekim horyzoncie (+3d i dalej), żeby stłumić niestabilność samego modelu Open-Meteo między pobraniami — patrz sekcja „GUI — opis panelu” wyżej.

### SynoptykV3 — analiza sygnałów (samodzielny moduł)

`analyzer/synoptyk_v3.py` to zestaw lokalnych analiz szeregu czasowego oparty o k najbliższych sąsiadów w czasie (KDTree): `flow` (lokalny gradient LSQ), `twist` (nagłe zmiany kierunku), `trm` (medianowe wygładzenie), `trend` (globalny dryf), `rhythm` (autokorelacja znormalizowana względem malejącego nakładania się próbek przy rosnącym opóźnieniu), `anomalies` (MAD względem TRM) i `fronts` (punkty, gdzie jednocześnie występuje silny twist i anomalia, dopasowane z tolerancją indeksową — patrz "Znane ograniczenia").

**Nie jest jeszcze podpięty do `forecaster/timdr_forecast.py`** — ten korzysta z osobnego `analyzer/timdr_analyzer.py` (inny format: DataFrame + krotki `'skręt'/'anomalia'/'rezonans'/'defekt'`), podczas gdy `SynoptykV3` pracuje na surowych tablicach `(t, s)` i zwraca indeksy/tablice numpy. Integracja wymagałaby osobnego adaptera.

16 testów w `analyzer/test_synoptyk_v3.py` (pytest).

### SynoptykV4 — jak V3, plus forecast() i wiatr

`analyzer/synoptyk_v4.py` ma ten sam rdzeń (`flow`/`twist`/`trm`/`anomalies`/`fronts`, inna implementacja twist/anomalies niż V3 — z-score po MAD drugiej pochodnej / residuów), plus dwie nowe rzeczy:

- **`forecast(t, s, steps_ahead, damping, clip_nonnegative)`** — tłumiona ekstrapolacja trendu dla dowolnej zmiennej skalarnej (temperatura, ciśnienie, opady z `clip_nonnegative=True`). Krótki horyzont ≈ ekstrapolacja lokalnego nachylenia (`flow`); długi horyzont tłumiony w stronę lokalnej średniej (`trm`) zamiast ekstrapolować nachylenie w nieskończoność. Pasmo niepewności rośnie jak `sqrt(krok)`, szersze po niedawnej anomalii. **To prosta heurystyka, nie model fizyczny NWP** — uzupełnienie sygnałów V4, nie zamiennik prognoz Open-Meteo/ECMWF/ICON używanych w `gui_app.py`/`data_sources/`.
- **Wiatr**: `forecast_wind_speed()` (jak `forecast()`, nieujemne), `forecast_wind_direction()` (kierunek to dana kołowa 0–360° — średnia **wektorowa**, nie arytmetyczna, żeby uniknąć błędu przy wartościach blisko granicy 0/360; `spread_deg` rośnie gdy ostatnie kierunki są rozrzucone), `circular_anomalies()` (wykrywa nagłe zmiany kierunku, licząc różnicę kątową "w koło" zamiast zwykłej różnicy — unika fałszywego alarmu przy przejściu 359°→1°).

23 testy w `analyzer/test_synoptyk_v4.py` (pytest). Gdy MAD wychodzi dokładnie 0 (płaski sygnał — normalny przypadek, nie skrajny), progi spadają na fallback `std()` zamiast zwracać pusty wynik. Domyślne progi (`twist_factor=3.5`, `anomaly_factor=3.0`) mogą nie wykryć bardzo łagodnych, rozłożonych w czasie frontów — są parametrami, można je obniżyć kosztem większej liczby fałszywych alarmów na czystym szumie (zmierzone: ~1% przy domyślnych progach, ~13–27% przy obniżonych do 2.0).

### WeatherTrigger — czujnik sygnałowy nad SynoptykV4 (NOWE)

`analyzer/weather_trigger.py` — **czujnik** (NIE model, NIE prognoza):
`WeatherTrigger`, dispatcher nad `fronts()`/`anomalies()`/`twist()`/
`circular_anomalies()`, które były dotąd całkowicie osierocone w tej
aplikacji (używane tylko we własnych testach — `api/main.py` korzysta z
innego modułu, `gui_app.py` woła z `SynoptykV4` tylko `forecast()`).
Mówi który typ zdarzenia się odpalił, w którym kanale i gdzie: `FRONT`
(twist i anomalia się zgadzają) > `ANOMALY` (pojedynczy potwierdzony
sygnał, także `circular_anomalies()` dla kierunku wiatru) > `TWIST`
(samo, najbardziej szumiące) > `NONE`. Wpięty do `gui_app.py` — zgłasza
się do Dziennika (nie jako kolejna kolumna tabeli, żeby nie powtórzyć
błędu z usuniętej kolumny "typ" TIMDR opisanego wyżej w kodzie). Testy:
`analyzer/test_weather_trigger.py` (8 testów, 31/31 łącznie z V4).

```python
from analyzer import WeatherTrigger

trigger = WeatherTrigger()
result = trigger.analyze(t, {"temp": temp, "pressure": pressure})
print(result.trigger_type, result.channel, result.location, result.message)
```

---

## Znane ograniczenia

- `topomap_data.py` zawiera pełne metadane tylko dla 7 miast (Warszawa, Kraków, Gdańsk, Wrocław, Poznań, Katowice, Zakopane). Pozostałe miasta używają domyślnych wartości `lat=52.0, lon=19.0` — współrzędne są pobierane z `get_node_metadata()`, które dla nieznanych miast zwraca fallback ze środka Polski.
- Open-Meteo Archive API ma opóźnienie ~1–2 dni — dane „wczorajsze" mogą być ostatnimi dostępnymi.
- `forecaster/validator.py` implementuje MAE i RMSE, ale walidacja out-of-sample nie jest uruchamiana automatycznie.
- `SynoptykV3.flow()`/`trm()` przy liczbie próbek `n` mieszczącej się w `k_neighbors` (domyślnie 12) cicho degenerują lokalną analizę do jednej globalnej regresji/mediany dla całego okna — sąsiedztwo każdego punktu to wtedy cały zbiór. Kod ostrzega o tym `RuntimeWarning`, ale nie naprawia tego automatycznie; dla krótkich okien zmniejsz `k_neighbors` albo zwiększ liczbę próbek. To samo dotyczy `SynoptykV4` (domyślnie `k_neighbors=8`).
- `SynoptykV4.twist()`/`anomalies()`/`fronts()` z domyślnymi progami mogą nie wykryć bardzo łagodnych, rozłożonych na kilka próbek frontów (patrz docstring modułu, "Historia poprawek" punkt 1) — próg jest teraz parametrem (`twist_factor`/`anomaly_factor`), obniżenie go zwiększa czułość kosztem fałszywych alarmów na czystym szumie.
- `SynoptykV4.forecast()`/`forecast_wind_speed()`/`forecast_wind_direction()` to prosta heurystyka (tłumiona ekstrapolacja trendu + powrót do lokalnej średniej), nie model NWP — nieprzetestowana jeszcze na rzeczywistych wieloetapowych danych z `krakow_forecast_snapshots.csv`, tylko na danych syntetycznych.
- Mieszanie głównej prognozy z własną ekstrapolacją trendu (`_blend_weight()` w `gui_app.py`) na dalekim horyzoncie tłumi wahania *między pobraniami*, ale **nie znaczy, że wynik jest trafniejszy** — tylko stabilniejszy. Jeśli Open-Meteo akurat trafnie wychwyciło zbliżający się front, a lokalny trend z ostatnich dni tego nie sugeruje, mieszanie ściągnie prognozę w stronę mniej trafnej wartości. Próg (+3d) i tempo narastania wagi (do +10d) są wybrane heurystycznie, nie strojone na rzeczywistych błędach prognozy — do zweryfikowania po zebraniu kilku-kilkunastu dni danych w `krakow_forecast_snapshots.csv`.
- `AdaptiveThresholds.fallback_df` (kalibracja na żywo, gdy `weather_cache.db` jest puste — patrz sekcja „GUI — opis panelu") liczy "normalność" z tego samego okna, które analizuje — front pogodowy obecny przez całe okno (np. 7 dni ciągłego deszczu) nie zostanie wykryty jako anomalia, bo sam podniesie średnią. Dodatkowo `threshold_defekt` (skok między kolejnymi punktami) jest wrażliwy na czysty szum pomiarowy przy krótkich/niegładkich seriach — im bardziej "poszarpane" dane wejściowe, tym więcej fałszywych `defekt`. Realne dane z Open-Meteo (godzinowe, skorelowane w czasie) są znacznie gładsze niż losowy szum, więc w praktyce powinno to być rzadsze niż w syntetycznych testach.
- `forecaster/bias_correction.py`: porównuje wiersz rzeczywisty (`IMGW_real_*`/`web_szukaj_*`) z pojedynczym punktem w czasie, a prognozę reprezentuje `avg_temp_c` (średnia dobowa) — to niedoskonałe porównanie (punkt vs średnia), zwłaszcza dla popołudniowych odczytów blisko dobowego maksimum, które systematycznie zawyżają zmierzone obciążenie. Przy różnorodniejszych porach odczytu w CSV powinno się to uśrednić; na razie traktować wyliczone `bias` jako orientacyjne, nie precyzyjne.

---

## .gitignore (zalecane uzupełnienie)

```gitignore
weather_cache.db
data/*.db
*.db
__pycache__/
*.pyc
.env
_last_pull_cache.json
```

---

## Licencja

MIT — szczegóły w pliku [LICENSE](LICENSE).
