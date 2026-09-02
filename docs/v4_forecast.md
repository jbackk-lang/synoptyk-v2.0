# SynoptykV4.forecast() i wiatr — szczegóły

Zobacz [`engines.md`](engines.md) po ogólną tabelę silników. Ten plik to rozwinięcie samego `SynoptykV4.forecast()` (i pochodnych dla wiatru) — heurystyki trendowej równoległej do głównej prognozy Open-Meteo, oraz mechanizmu mieszania jej z główną prognozą na dalekim horyzoncie.

## `forecast()` — tłumiona ekstrapolacja trendu

`analyzer/synoptyk_v4.py::forecast(t, s, steps_ahead, damping, clip_nonnegative)` — tłumiona ekstrapolacja trendu dla dowolnej zmiennej skalarnej (temperatura, ciśnienie, opady z `clip_nonnegative=True`). Krótki horyzont ≈ ekstrapolacja lokalnego nachylenia (`flow`); długi horyzont tłumiony w stronę lokalnej średniej (`trm`) zamiast ekstrapolować nachylenie w nieskończoność. Pasmo niepewności rośnie jak `sqrt(krok)`, szersze po niedawnej anomalii.

**To prosta heurystyka, nie model fizyczny NWP** — uzupełnienie sygnałów V4, nie zamiennik prognoz Open-Meteo/ECMWF/ICON używanych w `gui_app.py`/`data_sources/`. Nieprzetestowana jeszcze na rzeczywistych wieloetapowych danych z `krakow_forecast_snapshots.csv`, tylko na danych syntetycznych.

W GUI: pokazywany **równolegle** do głównej prognozy w kolumnie `V4 °C` (czysty, niezmieszany wynik, format `punkt [dolny–górny]`) — do porównania przez kilka dni z rzeczywistymi pomiarami, traktować jako porównanie, nie główną prognozę.

## Wiatr

- `forecast_wind_speed()` — jak `forecast()`, nieujemne.
- `forecast_wind_direction()` — kierunek to dana **kołowa** 0–360° — średnia **wektorowa**, nie arytmetyczna, żeby uniknąć błędu przy wartościach blisko granicy 0/360; `spread_deg` rośnie gdy ostatnie kierunki są rozrzucone.
- `circular_anomalies()` — wykrywa nagłe zmiany kierunku, licząc różnicę kątową "w koło" zamiast zwykłej różnicy — unika fałszywego alarmu przy przejściu 359°→1°.

Kolumna `Kier.` w GUI — kierunek wiatru jako pojedyncza strzałka (↑↗→↘↓↙←↖, 8 kierunków), licząca **dokąd** wiatr wieje (nie skąd). Dzienna wartość to średnia wektorowa (kołowa) godzinowych odczytów — `_circular_mean_deg()` w `gui_app.py` (ten sam mechanizm co `forecast_wind_direction()`).

## Mieszanie z główną prognozą na dalekim horyzoncie (stabilizacja)

Dni 0–2 głównej prognozy (`Min/Śr/Max °C`, `Ciśn hPa`, `Wiatr km/h`) to w całości świeża odpowiedź Open-Meteo Forecast API (+ korekta UHI/lapse/falkowa). Dni +3d i dalej mieszają się z **własną deterministyczną ekstrapolacją trendu** (`forecast()` na dziennie zagregowanej historii, NIE z modelu Open-Meteo) rosnącą wagą: 0% na dniach 0–2, liniowo do 100% przy +10d i dalej — bo Open-Meteo samo przelicza swój model NWP kilka razy dziennie i na dalekim horyzoncie potrafi mocno zmieniać wartość między dwoma pobraniami tego samego dnia. Nie dotyczy `Opad mm` (trend liniowy nie pasuje do zjawiska progowego/skokowego — ta kolumna zostaje czystym przepuszczeniem z API). Zobacz `_blend_weight()`/`_own_trend_points()` w `gui_app.py`.

**Ważne zastrzeżenie**: mieszanie tłumi wahania *między pobraniami*, ale **nie znaczy, że wynik jest trafniejszy** — tylko stabilniejszy. Jeśli Open-Meteo akurat trafnie wychwyciło zbliżający się front, a lokalny trend z ostatnich dni tego nie sugeruje, mieszanie ściągnie prognozę w stronę mniej trafnej wartości. Próg (+3d) i tempo narastania wagi (do +10d) są wybrane heurystycznie, nie strojone na rzeczywistych błędach prognozy.
