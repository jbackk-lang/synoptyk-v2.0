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

Gdy `weather_cache.db`/klimatologia są puste, "normalność" liczona jest z tego samego okna, które analizuje — front pogodowy obecny przez całe okno (np. 7 dni ciągłego deszczu) **nie zostanie wykryty jako anomalia**, bo sam podniesie średnią (self-baseline blind spot). Dodatkowo `threshold_defekt` (skok między kolejnymi punktami) jest wrażliwy na czysty szum pomiarowy przy krótkich/niegładkich seriach — im bardziej "poszarpane" dane wejściowe, tym więcej fałszywych `defekt`. Realne dane z Open-Meteo (godzinowe, skorelowane w czasie) są znacznie gładsze niż losowy szum, więc w praktyce powinno to być rzadsze niż w syntetycznych testach.
