# Korekta obciążenia (bias correction) — szczegóły

`forecaster/bias_correction.py`, `apply_bias_correction()`: średni zmierzony błąd (rzeczywistość − prognoza) per `lead_days`, liczony na żywo z `krakow_forecast_snapshots.csv` przy każdym uruchomieniu. To NIE jest model ML — nie ma osobnego kroku treningowego, korekta po prostu "uczy się" w miarę przybywania sparowanych obserwacji w CSV.

## Trzy tabele, nie jedna (NAPRAWIONE)

Dawniej JEDNA tabela korekty, parująca prognozowaną **średnią** (`avg_temp_c`) z realnym **maksimum** (`max_temp_c` z `_backfill_real_observations()` w `gui_app.py`) — niedopasowanie kolumn (dobowe maksimum jest z definicji ≥ dobowej średniej, w lecie zwykle o kilka stopni) samo w sobie zawyżało zmierzony bias/MAE, niezależnie od jakości modelu.

Teraz **trzy** tabele liczone osobno (`compute_lead_bias(forecast_col=..., real_col=...)` z dopasowaną kolumną po obu stronach: `avg`↔`avg`, `min`↔`min`, `max`↔`max`), stosowane do `Min °C`/`Śr °C`/`Max °C` niezależnie — `_backfill_real_observations()` wypełnia teraz też realne `min_temp_c`/`avg_temp_c` (dobowe minimum/średnia z tego samego godzinowego archiwum), nie tylko `max_temp_c`.

**Pozostała mniejsza niedoskonałość**: STARSZE wiersze rzeczywiste (`IMGW_real_*`/`web_szukaj_*`, sprzed `_backfill_real_observations()`) to wciąż pojedynczy odczyt punktowy w czasie (bez osobnych `min_temp_c`/`avg_temp_c`) — dla par `avg`/`min` te starsze wiersze po prostu nie wejdą do wyniku (puste → `pd.isna`, pomijane), więc dla stacji z głównie starą historią `bias`/`mae` dla `avg`/`min` może mieć mniej próbek (`n`) niż dla `max`, dopóki nie przybędzie nowszych wierszy `OpenMeteo_real_dailymax`.

## Circularity naprawiona

CSV zawsze loguje wartość prognozy **RAW (przed korektą obciążenia)**, nie już-skorygowaną. Bez tego `compute_lead_bias()` uczyłby się z czasem na własnym już poprawionym wyjściu z poprzednich pulli (samoreferencyjne zapętlenie), a zmierzony `bias`/`mae` na całej historii CSV byłby resztkowym błędem PO korekcie, nie surowym błędem modelu — czyli wyglądałby lepiej niż realna trafność surowego silnika, bez odzwierciedlenia tego w tabeli GUI (która nadal pokazuje wartość skorygowaną — najlepsze dostępne oszacowanie).

## Znaczki w kolumnie `Typ`

| Znaczek | Znaczenie |
|---|---|
| 🔴 | korekta jeszcze niedostępna dla tego lead_days — za mało sparowanych obserwacji prognoza/rzeczywistość w CSV (próg `min_samples=5`) |
| 🟠 | korekta aktywna, ale na małej próbce (5–14 obserwacji) — traktować orientacyjnie |
| 🟢 | korekta aktywna, solidniejsza próbka (≥15 obserwacji) |

Dziennik dodatkowo informuje o tym samym wprost (`🎯 <stacja>: korekta obciążenia (Śr °C/Min °C/Max °C) jeszcze nieaktywna...` albo lista aktywnych lead_days z liczbą próbek i wielkością korekty).

## Porównanie trafności głównego toru i V4 z rzeczywistością

`krakow_forecast_snapshots.csv` ma dodatkowe kolumny `v4_point_c`/`v4_lower_c`/`v4_upper_c` (punkt + pasmo `SynoptykV4.forecast()`, zapisywane od danej daty pulla w górę — starsze wiersze mają je puste). `compute_lead_bias()` przyjmuje opcjonalny `forecast_col` (domyślnie `"avg_temp_c"` — główny tor); wywołanie z `forecast_col="v4_point_c"` liczy dokładnie te same statystyki (bias/MAE per `lead_days`) dla samodzielnego toru V4.

## Nieprzetestowane przy mrozie

Korekta obciążenia (wszystkie trzy tory) liczy się WYŁĄCZNIE z danych z bieżącego okresu zbierania — dotąd bez żadnego dnia z temperaturą ujemną w CSV. Jak zachowuje się bias przy mrozie (zima) jest nieprzetestowane na rzeczywistych danych — do zweryfikowania, gdy CSV naturalnie obejmie chłodniejszy sezon.

## Automatyczny zapis do CSV (szczegóły)

Każde uruchomienie (poza Trybem Demo i wierszami `⚠️FB` — patrz [`fallbacks.md`](fallbacks.md)) dopisuje własną prognozę stacji do `krakow_forecast_snapshots.csv` samo, bez ręcznego wklejania — `source = prognoza_blending_bias`, kolejny `pull_seq` per (stacja, dzień). Zapisywane są wartości RAW (patrz „Circularity naprawiona” wyżej). Żeby plik nie rósł bez końca przy wielu uruchomieniach dziennie, po każdym zapisie usuwane są wiersze starsze niż 30 dni (licząc po `target_date`) — poza wierszami `_META_` (znaczniki typu `ENGINE_BASELINE_...`), które zostają na stałe.
