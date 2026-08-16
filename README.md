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

> **Windows:** zamiast ostatniej linii uruchom `run.bat`

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
| Tryb | Cały region lub pojedyncze miasto |
| Region | `cała_polska`, `poland_south`, `poland_north`, `poland_central`, `poland_west`, `poland_east` |
| Miasto | Lista ~40 miast PL (dropwdown) |
| Historia (dni) | Okno danych archiwalnych do filtra falkowego (3–30 dni) |
| Prognoza (dni) | Liczba dni naprzód w tabeli wyników (1–14) |
| Tryb Demo | Dane zastępcze „–" gdy brak dostępu do API |

Tabela wyników zawiera kolumny: `Stacja`, `Data`, `Typ` (Dziś/Jutro/+Nd), `Temp min`, `Temp śr`, `Temp max`, `Opady [mm]`, `Ciśnienie [hPa]`, `Wiatr max [km/h]`, `Kier.`, `Dane hist. do`, `Temp śr V4 [°C]`.

`Kier.` (nowa) — kierunek wiatru jako pojedyncza strzałka (↑↗→↘↓↙←↖, 8 kierunków), licząca **dokąd** wiatr wieje (nie skąd — to odwrotność meteorologicznego kąta 0–360°). Dzienna wartość to średnia wektorowa (kołowa) godzinowych odczytów, nie zwykła średnia arytmetyczna — patrz `_circular_mean_deg()` w `gui_app.py` (ten sam mechanizm co `SynoptykV4.forecast_wind_direction()`).

`Temp śr V4 [°C]` (nowa) — niezależny, eksperymentalny silnik `SynoptykV4.forecast()` (ekstrapolacja trendu z rzeczywistej historii, bez modelu Open-Meteo), pokazany **obok** głównej prognozy do porównania przez kilka dni, zanim ewentualnie zastąpi coś na stałe. Format: `punkt [dolny–górny]`.

Panel sterowania (lewa kolumna) zwężony, a „Dziennik” domyślnie zwinięty w rozwijaną sekcję nad tabelą — więcej miejsca dla prognozy, która teraz i tak ma więcej kolumn.

**NAPRAWIONE**: dni 0–2 głównej prognozy (`Temp min/śr/max`, `Ciśnienie`, `Wiatr max`) to w całości świeża odpowiedź Open-Meteo Forecast API (+ korekta UHI/lapse/falkowa), tak jak wcześniej. Ale dni +3d i dalej okazały się potrafić mocno zmieniać wartość między dwoma pobraniami zrobionymi tego samego dnia — bo Open-Meteo samo przelicza swój model NWP kilka razy dziennie, a im dalszy horyzont, tym większa jego własna niestabilność (zaobserwowane empirycznie w `krakow_forecast_snapshots.csv`: +4d..+9d skoczyło o 2–5°C, jutrzejszy opad 12.1mm→33.3mm, w ciągu tej samej doby, przy tych samych danych historycznych). Od tej wersji te kolumny (poza `Opady` — trend liniowy nie ma sensu dla zjawiska progowego/skokowego) mieszają się z **własną deterministyczną ekstrapolacją trendu** (`SynoptykV4.forecast()` na dziennie zagregowanej historii) rosnącą wagą: 0% na dniach 0–2, liniowo do 100% przy +10d i dalej. Zobacz `_blend_weight()`/`_own_trend_points()` w `gui_app.py` po pełne uzasadnienie i wzór. Zweryfikowane syntetycznym testem: dla dwóch pulli różniących się o 6°C na dalekim horyzoncie, po zmieszaniu różnica spada do <0.15°C przy +10d, przy zachowaniu pełnej (niezmienionej) czułości na dniach 0–2.

**NAPRAWIONE**: `Ciśnienie [hPa]` w prognozie wcześniej pochodziło z pola Open-Meteo `surface_pressure` (ciśnienie stacyjne, bez redukcji do poziomu morza), podczas gdy dane historyczne (używane m.in. do filtra falkowego) zawsze pobierały `pressure_msl` (poziom morza) — ta niespójność w jednym pliku dawała ~27–30 hPa systematycznej różnicy względem realnych pomiarów IMGW/AccuWeather (zweryfikowane: 998.7 hPa prognoza vs 1028 hPa pomiar, dla Krakowa ~220 m n.p.m., gdzie korekta stacja→poziom morza wynosi właśnie ~25–30 hPa). Teraz obie ścieżki używają `pressure_msl`.

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

16 testów w `analyzer/test_synoptyk_v3.py` (pytest), każdy odpowiada konkretnemu, zweryfikowanemu błędowi znalezionemu w trakcie code review — pełna historia poprawek w docstringu modułu.

### SynoptykV4 — jak V3, plus forecast() i wiatr

`analyzer/synoptyk_v4.py` ma ten sam rdzeń (`flow`/`twist`/`trm`/`anomalies`/`fronts`, inna implementacja twist/anomalies niż V3 — z-score po MAD drugiej pochodnej / residuów), plus dwie nowe rzeczy:

- **`forecast(t, s, steps_ahead, damping, clip_nonnegative)`** — tłumiona ekstrapolacja trendu dla dowolnej zmiennej skalarnej (temperatura, ciśnienie, opady z `clip_nonnegative=True`). Krótki horyzont ≈ ekstrapolacja lokalnego nachylenia (`flow`); długi horyzont tłumiony w stronę lokalnej średniej (`trm`) zamiast ekstrapolować nachylenie w nieskończoność. Pasmo niepewności rośnie jak `sqrt(krok)`, szersze po niedawnej anomalii. **To prosta heurystyka, nie model fizyczny NWP** — uzupełnienie sygnałów V4, nie zamiennik prognoz Open-Meteo/ECMWF/ICON używanych w `gui_app.py`/`data_sources/`.
- **Wiatr**: `forecast_wind_speed()` (jak `forecast()`, nieujemne), `forecast_wind_direction()` (kierunek to dana kołowa 0–360° — średnia **wektorowa**, nie arytmetyczna, żeby uniknąć błędu przy wartościach blisko granicy 0/360; `spread_deg` rośnie gdy ostatnie kierunki są rozrzucone), `circular_anomalies()` (wykrywa nagłe zmiany kierunku, licząc różnicę kątową "w koło" zamiast zwykłej różnicy — unika fałszywego alarmu przy przejściu 359°→1°).

23 testy w `analyzer/test_synoptyk_v4.py` (pytest). Historia poprawek w docstringu modułu — najważniejsza: kod nadesłany do sprawdzenia zwracał **bezwarunkowo pusty wynik** (`twist`/`anomalies`/`fronts`), gdy MAD wychodził dokładnie 0 — co jest normalnym przypadkiem dla frontu na tle długiego płaskiego sygnału, nie skrajnym. Naprawione fallbackiem do `std()`, z udokumentowanym ograniczeniem: dla łagodnych, rozłożonych w czasie frontów domyślne progi (`twist_factor=3.5`, `anomaly_factor=3.0`) mogą nadal nie wykryć zmiany — są teraz parametrami, można je obniżyć kosztem większej liczby fałszywych alarmów na czystym szumie (zmierzone: ~1% przy domyślnych progach, ~13–27% przy obniżonych do 2.0).

---

## Znane ograniczenia

- `topomap_data.py` zawiera pełne metadane tylko dla 7 miast (Warszawa, Kraków, Gdańsk, Wrocław, Poznań, Katowice, Zakopane). Pozostałe miasta używają domyślnych wartości `lat=52.0, lon=19.0` — współrzędne są pobierane z `get_node_metadata()`, które dla nieznanych miast zwraca fallback ze środka Polski.
- Open-Meteo Archive API ma opóźnienie ~1–2 dni — dane „wczorajsze" mogą być ostatnimi dostępnymi.
- `forecaster/validator.py` implementuje MAE i RMSE, ale walidacja out-of-sample nie jest uruchamiana automatycznie.
- `SynoptykV3.flow()`/`trm()` przy liczbie próbek `n` mieszczącej się w `k_neighbors` (domyślnie 12) cicho degenerują lokalną analizę do jednej globalnej regresji/mediany dla całego okna — sąsiedztwo każdego punktu to wtedy cały zbiór. Kod ostrzega o tym `RuntimeWarning`, ale nie naprawia tego automatycznie; dla krótkich okien zmniejsz `k_neighbors` albo zwiększ liczbę próbek. To samo dotyczy `SynoptykV4` (domyślnie `k_neighbors=8`).
- `SynoptykV4.twist()`/`anomalies()`/`fronts()` z domyślnymi progami mogą nie wykryć bardzo łagodnych, rozłożonych na kilka próbek frontów (patrz docstring modułu, "Historia poprawek" punkt 1) — próg jest teraz parametrem (`twist_factor`/`anomaly_factor`), obniżenie go zwiększa czułość kosztem fałszywych alarmów na czystym szumie.
- `SynoptykV4.forecast()`/`forecast_wind_speed()`/`forecast_wind_direction()` to prosta heurystyka (tłumiona ekstrapolacja trendu + powrót do lokalnej średniej), nie model NWP — nieprzetestowana jeszcze na rzeczywistych wieloetapowych danych z `krakow_forecast_snapshots.csv`, tylko na danych syntetycznych.
- Mieszanie głównej prognozy z własną ekstrapolacją trendu (`_blend_weight()` w `gui_app.py`) na dalekim horyzoncie tłumi wahania *między pobraniami*, ale **nie znaczy, że wynik jest trafniejszy** — tylko stabilniejszy. Jeśli Open-Meteo akurat trafnie wychwyciło zbliżający się front, a lokalny trend z ostatnich dni tego nie sugeruje, mieszanie ściągnie prognozę w stronę mniej trafnej wartości. Próg (+3d) i tempo narastania wagi (do +10d) są wybrane heurystycznie, nie strojone na rzeczywistych błędach prognozy — do zweryfikowania po zebraniu kilku-kilkunastu dni danych w `krakow_forecast_snapshots.csv`.

---

## .gitignore (zalecane uzupełnienie)

```gitignore
weather_cache.db
data/*.db
*.db
__pycache__/
*.pyc
.env
```

---

## Licencja

MIT — szczegóły w pliku [LICENSE](LICENSE).
