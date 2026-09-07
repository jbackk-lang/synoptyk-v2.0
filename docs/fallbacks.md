# Fallbacki i tryby zastępcze — szczegóły

## Kiedy pojawia się ⚠️FB?

Jeśli żywe API Open-Meteo (prognoza i/lub archiwum historyczne) nie odpowiada, silnik **nie pomija stacji** — liczy dalej na podstawie tego, co już jest zapisane dla tej stacji w `krakow_forecast_snapshots.csv` (Twoje wcześniej wklejone pulle i/lub automatyczne zapisy). To NIE jest demo — to realne dane z poprzednich uruchomień.

Takie wiersze mają w kolumnie `Typ` dopisek `⚠️FB` zamiast zwykłego znaczka korekty/dnia i **nie dostają** korekty obciążenia ani oznaczeń `▲`/`⚡EV` (nie mają sensownego punktu odniesienia w normalnym pipeline'ie). Jeśli dla danej stacji w CSV jest za mało danych (< 2 dni), stacja jest pomijana z komunikatem w Dzienniku.

To osobny mechanizm od **Trybu Demo**: Demo zawsze pokazuje same „–", fallback pokazuje realne liczby z historii.

## Open-Meteo Archive API — opóźnienie

Ma opóźnienie ~1–2 dni — dane „wczorajsze" mogą być ostatnimi dostępnymi. To jedna z sytuacji, w których warto sprawdzić, czy stacja nie przeszła w tryb `⚠️FB`.

## `topomap_data.py` — fallback współrzędnych

Pełne metadane tylko dla 7 miast (Warszawa, Kraków, Gdańsk, Wrocław, Poznań, Katowice, Zakopane). Pozostałe miasta używają domyślnych wartości `lat=52.0, lon=19.0` — fallback ze środka Polski, z `get_node_metadata()`.

## `AdaptiveThresholds.fallback_df` — kalibracja na żywo

Gdy `weather_cache.db`/klimatologia są puste, "normalność" liczona jest z tego samego okna, które analizuje. Dodatkowo `threshold_defekt` (skok między kolejnymi punktami) jest wrażliwy na czysty szum pomiarowy przy krótkich/niegładkich seriach — im bardziej "poszarpane" dane wejściowe, tym więcej fałszywych `defekt`. Realne dane z Open-Meteo (godzinowe, skorelowane w czasie) są znacznie gładsze niż losowy szum, więc w praktyce powinno to być rzadsze niż w syntetycznych testach.

### NAPRAWIONE: pojedynczy punkt zawyżał własny próg (Pattern B, maskowanie)

Znalezione przy audycie ekosystemu TIMDR pod kątem progów liczonych z tej
samej próbki, którą się testuje (ten sam mechanizm i ta sama naprawa co w
potomnych repo `SYNOPTYK-ARCTIC/arctic_synoptyk/resonance.py`,
`forecaster/resonance_calibration.py:_flag_resonance_days` i
`FLIGHT-TRACKING-TIMDR/timdr_flight.py:twist_3d`). `get_thresholds()`
liczyło RAZ mean/std per (miesiąc, parametr) na całym `fallback_df` i
dzieliło ten sam próg między wszystkie wiersze tego miesiąca — wartość
ocenianego wiersza sama współtworzyła próg, którym była oceniana. Przy
krótkim oknie (mały suwak "Historia (dni)") pojedynczy, genuinny duży
skok mógł zawyżyć własne std na tyle, że nigdy nie przekraczał progu,
niezależnie od tego, jak duży był.

**Naprawa**: gałąź fallback liczy teraz próg PER WIERSZ metodą
leave-one-out — mean/std z pominięciem akurat tego wiersza — wektorowo
(sumy/sumy kwadratów), więc bez powrotu do kosztu O(n) per wywołanie,
który został naprawiony osobno niżej. Zweryfikowane testami w
`analyzer/test_adaptive_thresholds.py` (m.in. skok do 20x amplitudy
bazowej na oknie n=4+1, który stara metoda maskowała bezwarunkowo, nowa
wykrywa zawsze) — pełny zestaw repo: 95/95 przechodzi.

**Uczciwe ograniczenie (świadomie NIE naprawione)**: leave-one-out
usuwa maskowanie PRZEZ JEDEN punkt, ale NIE rozwiązuje opisanego niżej
"self-baseline blind spot" dla frontu pogodowego obecnego przez CAŁE
okno (np. 7 dni ciągłego deszczu) — wykluczenie jednego dnia wciąż
zostawia pozostałe dni tego samego frontu jako większość próbki, więc
one nadal dominują (i przesuwają) obliczaną linię bazową. To jest
fundamentalnie inny, trudniejszy problem niż maskowanie pojedynczego
outliera — wymagałby zewnętrznej klimatologii (danych spoza ocenianego
okna), nie samej zmiany formuły progu. `threshold_defekt` (p10/p90) też
NIE jest tu liczony leave-one-out — patrz komentarz "UCZCIWE
OGRANICZENIE" w `adaptive_thresholds.py:get_thresholds`.

## NAPRAWIONE: `get_thresholds()` odpytywał SQLite przy KAŻDYM wywołaniu — "GUI liczy 10x dłużej po zwiększeniu suwaka Historia (dni)"

Zgłoszone jako: przebieg dla 3 stacji trwał 124s (wcześniej <10s) po zwiększeniu suwaka "Historia (dni)" z domyślnych 7 do 30. Dodane per-etapowe znaczniki czasu w `run_simulation()` (`gui_app.py`, linie logu `⏱ ...`) wskazały dokładnie: `TIMDR (from_calibrated + analyze)` zajmował ~39s na stację, podczas gdy wszystkie pozostałe etapy (2x realne zapytanie sieciowe do Open-Meteo, korekta obciążenia, filtr falkowy, SynoptykV4, WeatherTrigger, autosave, backfill) łącznie zajmowały poniżej 2s.

**Przyczyna**: gałąź "brak climatology" w `get_thresholds()` (patrz sekcja wyżej) robi realne zapytanie SQL do `weather_cache.db` (`self.cache.load_last_n_days(30)` → `pd.read_sql_query(...)`) — a `TIMDRAnalyzer.analyze()` woła `get_thresholds()` raz na (wiersz, parametr) w pętli po całej historii godzinowej. Przy 30 dniach historii (~720 wierszy) × 5 parametrów × kilka sprawdzeń (anomalia/defekt/skręt) to tysiące zapytań SQL — mimo że wynik i tak ZAWSZE ląduje na `fallback_df` w typowym użyciu tego GUI, bo `weather_cache.db` jest pusta (jak opisano wyżej). Koszt rósł wprost proporcjonalnie do liczby wierszy historii, stąd bezpośrednie przełożenie suwaka 7→30 dni na ~10x dłuższy czas.

**Naprawa**: `get_thresholds()` cache'uje teraz wynik per `(miesiąc, parametr)` w obrębie jednej analizy — te dwie zmienne w pełni determinują wynik (przy niezmienionym `fallback_df`), więc dalsze wywołania dla tej samej pary są odczytem ze słownika, nie zapytaniem SQL. `fallback_df` stało się property z setterem, który automatycznie czyści cache przy każdym nowym przypisaniu (`self.thresholds.fallback_df = df` w `timdr_analyzer.py`) — gwarantuje to, że cache nigdy nie przetrwa między różnymi stacjami/przebiegami z nieaktualnymi progami. Zmierzony efekt na identycznych warunkach (30 dni historii): blok TIMDR spadł z ~39s do ~0,4s. Zweryfikowane: 52/52 testów w `analyzer/` przechodzi bez zmian.

Pliki: `analyzer/adaptive_thresholds.py` (cache + property), `gui_app.py` (diagnostyczne znaczniki czasu `⏱`, zostają na stałe w Dzienniku — pomagają wyłapać podobny regres w przyszłości bez zgadywania).
