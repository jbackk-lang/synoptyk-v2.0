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

Tabela wyników zawiera kolumny: `Stacja`, `Data`, `Typ` (Dziś/Jutro/+Nd), `Temp min`, `Temp śr`, `Temp max`, `Opady [mm]`, `Ciśnienie [hPa]`, `Wiatr max [km/h]`, `Dane hist. do`.

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

Domyślny silnik GUI to `SynoptykFEngine` (filtr falkowy) z prognozą z Open-Meteo Forecast API.

### SynoptykV3 — analiza sygnałów (samodzielny moduł)

`analyzer/synoptyk_v3.py` to zestaw lokalnych analiz szeregu czasowego oparty o k najbliższych sąsiadów w czasie (KDTree): `flow` (lokalny gradient LSQ), `twist` (nagłe zmiany kierunku), `trm` (medianowe wygładzenie), `trend` (globalny dryf), `rhythm` (autokorelacja znormalizowana względem malejącego nakładania się próbek przy rosnącym opóźnieniu), `anomalies` (MAD względem TRM) i `fronts` (punkty, gdzie jednocześnie występuje silny twist i anomalia, dopasowane z tolerancją indeksową — patrz "Znane ograniczenia").

**Nie jest jeszcze podpięty do `forecaster/timdr_forecast.py`** — ten korzysta z osobnego `analyzer/timdr_analyzer.py` (inny format: DataFrame + krotki `'skręt'/'anomalia'/'rezonans'/'defekt'`), podczas gdy `SynoptykV3` pracuje na surowych tablicach `(t, s)` i zwraca indeksy/tablice numpy. Integracja wymagałaby osobnego adaptera.

16 testów w `analyzer/test_synoptyk_v3.py` (pytest), każdy odpowiada konkretnemu, zweryfikowanemu błędowi znalezionemu w trakcie code review — pełna historia poprawek w docstringu modułu.

---

## Znane ograniczenia

- `topomap_data.py` zawiera pełne metadane tylko dla 7 miast (Warszawa, Kraków, Gdańsk, Wrocław, Poznań, Katowice, Zakopane). Pozostałe miasta używają domyślnych wartości `lat=52.0, lon=19.0` — współrzędne są pobierane z `get_node_metadata()`, które dla nieznanych miast zwraca fallback ze środka Polski.
- Open-Meteo Archive API ma opóźnienie ~1–2 dni — dane „wczorajsze" mogą być ostatnimi dostępnymi.
- `forecaster/validator.py` implementuje MAE i RMSE, ale walidacja out-of-sample nie jest uruchamiana automatycznie.
- `SynoptykV3.flow()`/`trm()` przy liczbie próbek `n` mieszczącej się w `k_neighbors` (domyślnie 12) cicho degenerują lokalną analizę do jednej globalnej regresji/mediany dla całego okna — sąsiedztwo każdego punktu to wtedy cały zbiór. Kod ostrzega o tym `RuntimeWarning`, ale nie naprawia tego automatycznie; dla krótkich okien zmniejsz `k_neighbors` albo zwiększ liczbę próbek.

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
