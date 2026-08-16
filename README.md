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

Tabela wyników zawiera kolumny: `Stacja`, `Data`, `Typ` (Dziś/Jutro/+Nd), `Min °C`, `Śr °C`, `Max °C`, `Opad mm`, `Ciśn hPa`, `Wiatr km/h`, `Kier.`, `Hist. do`, `V4 °C`.

**NAPRAWIONE — nagłówki się ucinały**: pełne nazwy (`Temp min [°C]`, `Ciśnienie [hPa]` itd.) obcinały się do `Temp...`, `Ciśnie...` przy szerokościach kolumn dopasowanych do danych, nie do nagłówka — Gradio nie zawija/skaluje nagłówka automatycznie. Skrócone do jednostki + istotnego słowa (powyżej) i dodatkowo mniejsza czcionka samego nagłówka (`0.78rem` vs `0.92rem` komórek danych) w CSS `#forecast_table`. Kolorowe znaczki (🔴🟠🟢/`⚡EV`) w kolumnie `Typ` wyrównane do lewej (reszta tabeli wyśrodkowana) — inaczej "pływały" w różnych miejscach przy różnej długości `Dziś`/`Jutro`/`+13d`.

**ZMIENIONE — kolejność w `Typ`**: znaczek korekty obciążenia (🔴🟠🟢) jest teraz PIERWSZY, dzień (`Dziś`/`Jutro`/`+Nd`) drugi — np. `🟢 Jutro` zamiast `Jutro 🟢`. Kolumna `Typ` zwężona do 100px (z 140px) — mieści to swobodnie, ale rzadki przypadek pełnej kombinacji `🟢 +13d ⚡ano·def·rez ⚡EV` (korekta + skok silnika + wszystkie sygnały TIMDR naraz) się przy tym utnie. Świadomy kompromis: `wrap=False` + `white-space: nowrap` w CSS ucinają nadmiar tekstu zamiast łamać go do drugiej linii, więc wysokość wierszy zostaje równa nawet w tym skrajnym przypadku.

`Kier.` (nowa) — kierunek wiatru jako pojedyncza strzałka (↑↗→↘↓↙←↖, 8 kierunków), licząca **dokąd** wiatr wieje (nie skąd — to odwrotność meteorologicznego kąta 0–360°). Dzienna wartość to średnia wektorowa (kołowa) godzinowych odczytów, nie zwykła średnia arytmetyczna — patrz `_circular_mean_deg()` w `gui_app.py` (ten sam mechanizm co `SynoptykV4.forecast_wind_direction()`).

`V4 °C` (nowa) — niezależny, eksperymentalny silnik `SynoptykV4.forecast()` (ekstrapolacja trendu z rzeczywistej historii, bez modelu Open-Meteo), pokazany **obok** głównej prognozy do porównania przez kilka dni, zanim ewentualnie zastąpi coś na stałe. Format: `punkt [dolny–górny]`.

**DODANE — korekta obciążenia**: obok `Typ` pojawia się kolorowy znaczek statusu korekty systematycznego błędu (`forecaster/bias_correction.py`, `apply_bias_correction()`, kod: `_bias_badge()` w `gui_app.py`):

| Znaczek | Znaczenie |
|---|---|
| 🔴 | korekta jeszcze niedostępna dla tego lead_days — za mało sparowanych obserwacji prognoza/rzeczywistość w CSV (próg `min_samples=5`) |
| 🟠 | korekta aktywna, ale na małej próbce (5–14 obserwacji) — traktować orientacyjnie |
| 🟢 | korekta aktywna, solidniejsza próbka (≥15 obserwacji) |

To NIE jest model ML — to średni zmierzony błąd (rzeczywistość − prognoza) per lead_days, liczony na żywo z CSV przy każdym uruchomieniu, więc "uczy się" automatycznie w miarę przybywania danych, bez osobnego kroku treningowego. Próg 15 dla 🟢 jest heurystyczny (na oko, nie z testu istotności statystycznej). Kod dodatkowo informuje o tym samym wprost w Dzienniku (`🎯 <stacja>: korekta obciążenia jeszcze nieaktywna...` albo lista aktywnych lead_days z liczbą próbek i wielkością korekty).

**DODANE — wykrywanie skoku silnika (EV)**: `Typ` dostaje dopisek `⚡EV`, gdy `Temp śr`/`Opady`/`Ciśnienie`/`Wiatr max` dla tego samego dnia docelowego zmieniły się między poprzednim a bieżącym uruchomieniem GUI powyżej progu (odpowiednio 2°C / 10mm / 5hPa / 8km/h) — `detect_engine_volatility()` w `gui_app.py`. **NAPRAWIONE**: pierwotnie pamięć poprzedniego pulla żyła tylko w RAM procesu, więc restart serwera lokalnego (Ctrl+C, zamknięcie terminala między sprawdzeniami w ciągu dnia) czyścił ją do zera i `⚡EV` praktycznie nigdy się nie zapalało. Teraz zapisywana na dysk (`_last_pull_cache.json` obok `gui_app.py`, dopisz do `.gitignore`) i wczytywana przy starcie — przetrwa restart. Jeśli plik zniknie/uszkodzi się, kod po cichu zaczyna od pustej pamięci zamiast się wywalić.

Panel sterowania (lewa kolumna) zwężony, a „Dziennik” domyślnie zwinięty w rozwijaną sekcję nad tabelą — więcej miejsca dla prognozy, która teraz i tak ma więcej kolumn.

**NAPRAWIONE — wyrównanie tabeli**: `Stacja`/`Data` zawijały się do dwóch linii przy domyślnych (za wąskich) szerokościach kolumn, co dawało nierówną wysokość kolejnych wierszy. Teraz `wrap=False` + poszerzone kolumny (`Stacja` 150px, `Typ` 140px — mieści nawet `+13d 🔴 ⚡ano·def·rez`) + dodatkowe CSS (`#forecast_table` w `create_app()`): tabularne cyfry, jednakowe wyśrodkowane komórki, stała wysokość wiersza. Panel po lewej dodatkowo zwężony (`min_width` 220→190px), a etykiety suwaków skrócone („Historia (dni) — okno filtra falkowego” → „Historia (dni)”, pełne wyjaśnienie zostało w bloku ℹ️), żeby się nie łamały do 3 linii.

**NAPRAWIONE — CSS znikał na Gradio ≥6.0**: `theme`/`css` przekazywane wyłącznie do konstruktora `gr.Blocks()` są po cichu ignorowane od Gradio 6.0 (tylko `UserWarning`, bez błędu) — trzeba je podać też w `app.launch()`. Ponieważ `requirements.txt` ma `gradio>=4.0.0` bez górnej granicy, świeży `pip install` mógł ściągnąć 6.x i całe stylowanie tabeli (patrz wyżej) znikało bez żadnego widocznego powodu. Teraz `_THEME`/`_CSS` to stałe modułowe, przekazywane w obu miejscach (`create_app()` i `if __name__ == "__main__"`), z fallbackiem `try/except TypeError` dla starszych wersji Gradio, gdzie `launch()` mógłby ich nie przyjmować.

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
