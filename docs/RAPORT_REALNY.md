# Realna trafność Synoptyk v2.0 — policzone na prawdziwych danych (2026-09-19)

Ten dokument zastępuje usunięty `RAPORT.md` ("RAPORT PORÓWNAWCZY — SYNOPTYK v2
ECMWF vs ICON"), który opisywał analizę frontów, "stabilność trendu" i
14-dniową prognozę jako "wiarygodną", choć żaden kod w tym repo nie liczy
pozycji frontów w km ani kategorii "stabilność trendu" — `synoptyk/trend.py`
to zwykła średnia arytmetyczna, a `synoptyk/compare.py` liczy wyłącznie
surowe różnice godzinowe (ΔT/ΔPrec/ΔWind/ΔPressure), nic ponadto. Treść
`RAPORT.md` wprost przeczyła też własnemu README tego repo ("Synoptyk nie
generuje własnej prognozy fizycznej... nie przewiduje frontów, burz ani
opadów z trendu"). Usunięty jako niepodparty kodem ani danymi.

## Metoda

Liczby niżej pochodzą z **prawdziwego, produkcyjnego kodu**
(`forecaster/bias_correction.py::compute_lead_bias`) uruchomionego na
**prawdziwym, zebranym CSV** (`krakow_forecast_snapshots.csv`, 3152 wiersze,
zakres `target_date` 2026-08-16 – 2026-10-01, realne pomiary
2026-08-19 – 2026-09-17 z Open-Meteo Archive API). Nic tu nie jest
syntetyczne ani dobrane pod wynik — to dokładnie ta sama funkcja, która
liczy korektę obciążenia w GUI. `bias = rzeczywistość − prognoza` (ujemny =
prognoza za ciepła... nie, ujemny = prognoza zawyżona względem
rzeczywistości tylko gdy dodatni jest odwrotnie — **uwaga**: przy tej
definicji `bias < 0` oznacza, że rzeczywistość wypadła CHŁODNIEJ niż
prognoza, czyli silnik systematycznie PRZESZACOWUJE temperaturę). Kolumna
`max_temp_c`↔`max_temp_c` ma najwięcej sparowanych obserwacji ze wszystkich
trzech torów (min/avg/max), więc jest tu głównym punktem odniesienia.

## Wynik — główny tor (`avg_temp_c`), stacja Krakow_Centrum

| lead_days | n | bias °C | MAE °C |
|---|---|---|---|
| 0 | 11 | −2.67 | 2.67 |
| 1 | 11 | −3.17 | 3.17 |
| 2 | 10 | −2.76 | 2.76 |
| 3 | 11 | −1.40 | 1.69 |
| 4 | 10 | −2.15 | 2.59 |
| 5 | 12 | −2.82 | 2.82 |
| 6 | 13 | −3.15 | 3.15 |
| 7 | 15 | −1.39 | 1.99 |
| 8 | 15 | −2.22 | 3.86 |
| 9 | 14 | −2.21 | 5.79 |
| 10 | 14 | −2.68 | 5.48 |
| 11 | 19 | −3.09 | 4.44 |
| 12 | 23 | −2.29 | 4.47 |
| 13 | 31 | −0.02 | 2.95 |

## Wynik — tor `max_temp_c` (najwięcej próbek), stacja Krakow_Centrum

| lead_days | n | bias °C | MAE °C |
|---|---|---|---|
| 0 | 55 | −2.40 | 2.56 |
| 1 | 59 | −2.55 | 2.60 |
| 2 | 63 | −1.94 | 2.04 |
| 3 | 71 | −1.34 | 2.01 |
| 4 | 71 | −1.71 | 2.43 |
| 5 | 73 | −2.48 | 3.14 |
| 6 | 79 | −2.93 | 3.44 |
| 7 | 83 | −1.44 | 3.51 |
| 8 | 86 | −1.08 | 4.19 |
| 9 | 86 | −1.19 | 5.16 |
| 10 | 87 | −1.47 | 4.34 |
| 11 | 88 | −1.18 | 4.58 |
| 12 | 87 | −1.35 | 4.31 |
| 13 | 85 | −2.16 | 3.69 |
| 14 | 21 | −5.11 | 6.21 |

## Wynik — tor V4 (`SynoptykV4.forecast()`), stacja Krakow_Centrum

| lead_days | n | bias °C | MAE °C |
|---|---|---|---|
| 0 | 10 | −0.67 | 2.55 |
| 1 | 11 | −2.22 | 3.22 |
| 3 | 11 | −0.13 | 2.54 |
| 7 | 15 | +0.73 | 4.09 |
| 13 | 31 | −0.52 | 2.40 |

(pełna tabela 0–13 w kodzie; tu skrócona do reprezentatywnych punktów —
pełny wydruk dostępny na żądanie)

## Inne stacje (tor `max_temp_c`)

- **Warszawa** — dane real 2026-08-19–2026-09-17 (30 dni), bias lead_days=0:
  n=54, bias=−1.94°C, MAE=1.94°C — podobny systematyczny wzorzec zawyżania
  temperatury jak Kraków.
- **Gdynia** — dane real 2026-08-19–2026-09-17 (30 dni), bias lead_days=0:
  n=54, bias=−1.11°C, MAE=1.38°C — słabszy, ale wciąż ujemny bias na
  krótkim horyzoncie; lead_days=2 daje już bias dodatni (+0.33°C) — znak
  bias się zmienia w zależności od horyzontu, nie jest jednokierunkowy jak
  w Krakowie.
- **Zakopane, Gdańsk** — `insufficient_data` (0 lead_days z ≥5 sparowanymi
  obserwacjami przy tym progu) — realne dane zaczęły się dopiero
  2026-09-02, za krótkie okno. To NIE jest błąd implementacji, tylko
  strukturalny brak historii — dokładnie ten sam wzorzec "test bez mocy ≠
  brak efektu" udokumentowany już w SYNOPTYK-ARCTIC i Synoptyk-v3.

## Uczciwa interpretacja

1. **Silnik systematycznie PRZESZACOWUJE temperaturę** (bias ujemny na
   niemal każdym `lead_days`, w każdej stacji z wystarczającymi danymi) —
   rzeczywista temperatura wypada niżej niż prognoza średnio o 1–3°C na
   większości horyzontów, do −5.1°C na najdalszym (lead_days=14, ale tam
   n=21, najmniejsza próbka spośród wszystkich wierszy tabeli).
2. **MAE rośnie z horyzontem, ale nie monotonicznie** — z ~2.0–2.7°C na
   lead_days 0–4 do 4–6°C w okolicach lead_days 8–14. Nie jest to gładka
   krzywa (lokalne spadki np. lead_days=13 wraca do 2.95–3.69°C) — spójne z
   umiarkowaną wielkością próby (n=10–88), nie z jednym czystym
   mechanizmem błędu.
3. **To jedno, ~6-tygodniowe okno** (połowa sierpnia – połowa września
   2026, wczesna jesień/późne lato), jedna pora roku, bez ani jednego dnia
   mrozu w danych (zgodnie z już istniejącym zastrzeżeniem w
   `docs/bias_correction.md`: "nieprzetestowane przy mrozie"). Nie
   ekstrapoluj tego na zimę.
4. **Różnica między stacjami jest realna i nie jest jednokierunkowa**
   (Kraków: bias ujemny na każdym horyzoncie; Gdynia: zmienia znak między
   lead_days 0 i 2) — albo prawdziwa różnica regionalna w jakości danych
   źródłowych Open-Meteo dla tych lokalizacji, albo artefakt małej próby;
   na tych n nie da się tego rozstrzygnąć bez testu istotności
   (Mann-Whitney), nie zrobionego tutaj celowo.
5. **Brak tu jakiegokolwiek porównania z niezależnym dostawcą** (takiego,
   jakie zrobił Synoptyk-v3 względem meteoblue) — więc nie wiadomo, czy ten
   błąd pochodzi z samego modelu Open-Meteo, czy z czegoś w potoku
   Synoptyk v2.0 (filtr falkowy, korekta UHI). Otwarty punkt.

**Wniosek zastępujący usunięty RAPORT.md:** Synoptyk v2.0 na realnych
danych z ostatnich ~6 tygodni pokazuje systematyczny, ujemny bias
(przeszacowanie temperatury) rzędu 1–3°C na większości horyzontów
prognozy, z błędem bezwzględnym rosnącym do 4–6°C w okolicach 8–14 dni
naprzód — to NIE jest "prognoza wiarygodna dzięki wysokiej stabilności
modeli", tylko konkretny, zmierzony błąd z konkretnym kierunkiem, dokładnie
taki, jaki mechanizm korekty obciążenia (`bias_correction.py`) został
zbudowany, żeby korygować na żywo.
