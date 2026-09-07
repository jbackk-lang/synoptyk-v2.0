# 🌪️ Synoptyk v2.0

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Dane: Open-Meteo](https://img.shields.io/badge/dane-Open--Meteo-0ea5e9)](https://open-meteo.com/)

Wielodniowa prognoza pogody dla Polski i wybranych regionów USA, oparta na danych Open-Meteo (ECMWF/ICON), z filtrem falkowym Daubechies i korektą obciążenia liczoną na żywo z realnych pomiarów. Wyniki w GUI Gradio — każdy dzień prognozy jako osobny wiersz.

---

## Co robi

- pobiera dane historyczne (Open-Meteo Archive API) i prognozę (Open-Meteo Forecast API) bez lokalnego cache
- odszumia szereg temperatury filtrem falkowym `db4` (PyWavelets) i stosuje korektę o Miejską Wyspę Ciepła (UHI) oraz gradient termiczny wysokości
- koryguje prognozę na żywo na podstawie tego, jak bardzo się myliła w przeszłości (korekta obciążenia — patrz „Jak czytać tabelę wyników” niżej)
- wyświetla prognozę dzienną (1–14 dni) z datami, min/śr/max temperatury, sumą opadów, średnim ciśnieniem i maksymalnym wiatrem, z wykresem pasmowym per miasto
- ostrzega w dzienniku GUI gdy dane archiwalne są starsze niż 2 doby
- Synoptyk nie generuje własnej prognozy fizycznej — stabilizuje i koryguje prognozę Open‑Meteo, dodając lokalne poprawki i analizę trendu.


## Co NIE jest celem Synoptyk v2.0

Synoptyk **nie zastępuje** modeli NWP (ECMWF/ICON) — korzysta z nich jako źródła danych, nie konkuruje z nimi. Nie przewiduje frontów, burz ani opadów z trendu (`SynoptykV4.forecast()` na opadach jest wyłączony właśnie z tego powodu). To narzędzie do **stabilnej prognozy dziennej z korektą lokalną** — nie do dokładności poziomu IMGW ani do wykrywania nadchodzących zjawisk pogodowych.

---

## Szybki start

```bash
git clone https://github.com/jbackk-lang/synoptyk-v2.0.git
cd synoptyk-v2.0
pip install -r requirements.txt
python gui_app.py
# GUI dostępne pod http://127.0.0.1:7860
```

> **Windows:** zamiast ostatniej linii uruchom `run.bat` — jedno okno konsoli, przeglądarka otwiera się sama. Osobny serwer API (FastAPI/Uvicorn, port 8010) GUI nie potrzebuje — uruchamia się osobno przez `run_api.bat`, jeśli jest potrzebny do czegoś innego.

Wymagania: `gradio>=4.0`, `numpy`, `pandas`, `pywavelets`, `requests` (pełna lista w `requirements.txt`). Nie jest wymagany klucz API — Open-Meteo jest bezpłatne.

## Zalecane ustawienia na start

- **Miasto**: `Krakow_Centrum` — najwięcej zebranych danych, korekta obciążenia najbardziej aktywna.
- **Historia**: 7–14 dni.
- **Prognoza**: 1–7 dni — najbardziej stabilne (dni +8 i dalej mają wyraźnie wyższy błąd, patrz [`docs/bias_correction.md`](docs/bias_correction.md)).
- **Tryb**: `Pojedyncze miasto` na start — `Cały Region`/`Wybór miast` dają więcej wierszy do przewijania.
- **`V4 °C`**: traktować jako porównanie z główną prognozą, nie jako główną prognozę samą w sobie.

---

## Hierarchia silników (co jest główne, co pomocnicze)

1. **GŁÓWNY TOR PROGNOZY GUI** — `SynoptykFEngine` + Open-Meteo (filtr falkowy + korekta UHI).
2. **TOR TRENDOWY** — `SynoptykV4.forecast()` (pokazywany równolegle w `V4 °C`; mieszany z głównym torem od +3d).
3. **TOR REGRESYJNY** — `TIMDRForecast` (samodzielny, **nie używany w GUI** — dostępny przez CLI/API).
4. **ANALIZA SYGNAŁÓW** — `SynoptykV3`/`SynoptykV4` (`flow`/`twist`/`fronts`/`anomalies`) — analiza szeregu czasowego, nie prognoza.
5. **CZUJNIK** — `WeatherTrigger` — zdarzenia w historii (FRONT/ANOMALY/TWIST), nie prognoza na przyszłość.
6. Mieszanie V4 z głównym torem zaczyna się dopiero od +3d, bo krótkoterminowa prognoza Open‑Meteo jest zwykle trafniejsza niż lokalny trend; opady nie są mieszane, bo trend liniowy nie pasuje do zjawisk progowych; TIMDRForecast nie jest w GUI, bo wymaga pełnego szeregu godzinowego i działa wolniej.


Pełne szczegóły każdego toru: [`docs/engines.md`](docs/engines.md).

## Stabilność modułów

| Stabilne | Eksperymentalne |
|---|---|
| GUI, `SynoptykFEngine`, fetcher Open-Meteo, korekta obciążenia (3 tabele: min/śr/max) | `SynoptykV4.forecast()` (trend), mieszanie z trendem na dalekim horyzoncie, `WeatherTrigger`, `SynoptykV3`/`V4` fronty/anomalie |

„Eksperymentalne” nie znaczy niedziałające — znaczy: heurystyka bez formalnej walidacji out-of-sample na rzeczywistych danych, do traktowania z rozsądną dozą nieufności.

---

## TIMDR w Synoptyk v2.0 — co to znaczy?

TIMDR **nie jest modelem pogody**. To czujnik strukturalnych sygnałów w danych historycznych (skręt/anomalia/rezonans/defekt) — mówi, czy dany fragment historii "wygląda inaczej" niż zwykle, nie co będzie jutro. W tej wersji nie jest już pokazywany jako kolumna w tabeli (był praktycznie zawsze aktywny, nie odróżniał niczego) — żywym, wpiętym do GUI czujnikiem tego typu jest teraz `WeatherTrigger` (patrz niżej).

## WeatherTrigger — po co jest?

Wykrywa zdarzenia w danych historycznych: `FRONT` > `ANOMALY` > `TWIST` > `NONE`. To czujnik, nie prognoza — informuje o zmianie reżimu w historii, nie o przyszłej pogodzie. Zgłasza się do **Dziennika** GUI (nie do tabeli). Szczegóły i przykład kodu: [`docs/weather_trigger.md`](docs/weather_trigger.md).

---

## GUI — opis panelu

| Kontrolka | Opis |
|---|---|
| Tryb | Cały region / pojedyncze miasto / dowolny wybór miast |
| Region | `cała_polska`, `poland_south`, `poland_north`, `poland_central`, `poland_west`, `poland_east` |
| Miasto | Lista ~40 miast PL |
| Historia (dni) | Okno danych archiwalnych do filtra falkowego (3–30 dni) |
| Prognoza (dni) | Liczba dni naprzód w tabeli wyników (1–14) |
| Widoczne miasta | Filtr kart tabela+wykres per miasto (nie wysyła nowego zapytania) |
| Tryb Demo | Dane zastępcze „–" gdy brak dostępu do API |

## Jak czytać tabelę wyników

- **▲** — wartość zmieniła się od poprzedniego pulla.
- **⚡EV** — silnik zmienił reżim (skok głównego silnika względem poprzedniego pulla).
- **🔴** — korekta obciążenia jeszcze niedostępna dla tego dnia (za mało danych).
- **🟠** — korekta aktywna, ale na małej próbce (5–14 obserwacji).
- **🟢** — korekta aktywna, solidniejsza próbka (≥15 obserwacji).
- **`V4 °C`** — niezależny tor trendowy (punkt + pasmo), do porównania, nie główna prognoza.
- **⚠️FB** — fallback: brak świeżych danych z API, liczone z historii CSV (patrz „Kiedy pojawia się ⚠️FB” niżej).
- V4 °C może różnić się wyraźnie od głównej prognozy — to normalne: V4 jest czystą ekstrapolacją trendu z historii, bez modelu fizycznego NWP.


Pełne wyjaśnienie korekty obciążenia (i jak dawniej zawyżała błąd): [`docs/bias_correction.md`](docs/bias_correction.md).

## Kiedy pojawia się ⚠️FB?

Gdy Open-Meteo nie odpowiada, Synoptyk używa ostatnich zapisanych danych z `krakow_forecast_snapshots.csv`. Wyniki ⚠️FB nie mają korekty obciążenia, nie mają oznaczeń ▲/⚡EV i mogą być starsze niż bieżące dane — to tylko awaryjne podtrzymanie działania GUI.**To NIE jest demo** — to realne dane z poprzednich uruchowień, tylko bez korekty obciążenia i bez `▲`/`⚡EV` (nie mają punktu odniesienia). Szczegóły i inne fallbacki (np. domyślne współrzędne nieznanych miast): [`docs/fallbacks.md`](docs/fallbacks.md).

## Typowe problemy użytkownika

| Widzę... | To znaczy... |
|---|---|
| `⚠️FB` zamiast zwykłego dnia | brak świeżych danych z Open-Meteo — liczone z historii CSV |
| `🔴` zamiast `🟠`/`🟢` | korekta obciążenia jeszcze nieaktywna — za mało zebranych par prognoza/rzeczywistość |
| żadnej wartości z `▲` | nic się nie zmieniło względem poprzedniego uruchomienia (albo cache `_last_pull_cache.json` wyczyszczony) |
| brak `⚡EV` mimo dużej zmiany | próg skoku (2°C/10mm/5hPa/8km/h) nie został przekroczony — to nie błąd, tylko nieprzekroczony próg |

## Co robić gdy coś wygląda dziwnie?

- brak ▲ — Open‑Meteo nie zaktualizowało modelu od poprzedniego uruchomienia.
- brak ⚡EV — zmiana nie przekroczyła progu (2°C/10mm/5hPa/8km/h).
- 🔴 — korekta obciążenia nie ma jeszcze danych (min. 5 par prognoza/rzeczywistość).
- V4 °C „dziwne” — normalne: to trend, nie model fizyczny.
- opady 0 przez kilka dni — normalne: Open‑Meteo często daje 0 przy braku pewności.
- ⚠️FB — API nie odpowiada; to awaryjne podtrzymanie działania.

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
├── data/fetcher.py         # WeatherFetcher — Open-Meteo Archive
├── data_sources/           # real_weather.py, model_ecmwf.py, model_icon.py
├── analyzer/                # timdr_analyzer.py, synoptyk_v3.py, synoptyk_v4.py, weather_trigger.py
├── synoptyk/                # compare.py, trend.py
├── forecaster/               # timdr_forecast.py, bias_correction.py, validator.py
├── config/, scripts/, examples/
└── docs/                     # engines.md, bias_correction.md, fallbacks.md, v4_forecast.md, weather_trigger.md
```

> `weather_cache.db` — plik SQLite generowany lokalnie przez `data/fetcher.py`. **Nie powinien być commitowany** (dodaj do `.gitignore`). GUI v2 pobiera dane bezpośrednio z API i nie korzysta z cache.

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

## Dokumentacja szczegółowa

- [`docs/engines.md`](docs/engines.md) — pełna tabela silników, SynoptykV3, analiza TIMDR, pozostałe znane ograniczenia.
- [`docs/v4_forecast.md`](docs/v4_forecast.md) — `SynoptykV4.forecast()`, wiatr, mieszanie z główną prognozą na dalekim horyzoncie.
- [`docs/weather_trigger.md`](docs/weather_trigger.md) — czujnik zdarzeń, priorytety, przykład kodu.
- [`docs/bias_correction.md`](docs/bias_correction.md) — korekta obciążenia (3 tabele), naprawiona circularity, porównanie z V4.
- [`docs/fallbacks.md`](docs/fallbacks.md) — `⚠️FB`, opóźnienie Open-Meteo Archive, fallback współrzędnych, `AdaptiveThresholds.fallback_df`.

Ciśnienie w całym pliku (prognoza i historia) to `pressure_msl` (poziom morza), nie `surface_pressure` (stacyjne).

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
