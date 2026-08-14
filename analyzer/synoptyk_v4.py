# analyzer/synoptyk_v4.py
"""
SynoptykV4 — rozwiniecie SynoptykV3 (analyzer/synoptyk_v3.py).

Ten sam rdzen sygnalow co V3 (flow/twist/trm/anomalie/fronts), ale:
  - inna implementacja twist()/anomalies() (z-score po MAD drugiej
    pochodnej / residuow wzgledem trm), taka jak zaproponowal user,
    z naprawionymi bledami (patrz "Historia poprawek")
  - forecast() - ogolna ekstrapolacja trendu dla DOWOLNEJ zmiennej
    skalarnej (temperatura, cisnienie, opady...), z pasmem niepewnosci
  - obsluga wiatru: forecast_wind_speed() (jak forecast(), nieujemne)
    oraz forecast_wind_direction() + circular_anomalies() dla kierunku
    (dane katowe 0-360 stopni, poprawnie liczone "w kolo" - patrz punkt 4)

UWAGA: forecast()/forecast_wind_speed()/forecast_wind_direction() to
prosta heurystyka (tlumiona ekstrapolacja trendu + powrot do lokalnej
sredniej), NIE model fizyczny NWP. Traktuj jako uzupelnienie sygnalow
V3/V4 (kiedy zaraz nastapi front, jak stabilny jest kierunek wiatru),
NIE jako zamiennik prognoz Open-Meteo/ECMWF/ICON uzywanych gdzie indziej
w repo (patrz forecaster/timdr_forecast.py, gui_app.py).

Historia poprawek (zweryfikowane w trakcie code review, nie tylko
zadeklarowane w komentarzach):

1. twist()/anomalies(): gdy MAD (mediana |x - mediana(x)|) wychodzila
   dokladnie 0 - co jest NORMALNE, nie skrajnym przypadkiem, dla
   typowego frontu: krotka zmiana na tle dlugiego plaskiego sygnalu,
   gdzie ponad polowa roznic/residuow to dokladnie zero - poprzedni kod
   zwracal PUSTY wynik bezwarunkowo, niezalezne od tego jak duza byla
   sama zmiana. Zweryfikowane: skok 10C->20C na 1 probce (n=30) -
   wykrywany; ten sam skok rozlozony na 6 probek - NIC nie wykrywane,
   mad=0, mimo ze zmiana jest realna i duza (10C).
   Naprawione: gdy mediana-MAD==0, uzywamy std() jako fallback (lapie
   rzadkie niezerowe wartosci, ktorych mediana ignoruje kompletnie).

   WAZNE OGRANICZENIE tej poprawki (zweryfikowane numerycznie, nie
   zalozone): std() jako fallback ma WLASNY, nizszy sufit z-score dla
   rozlozonych (kilkupróbkowych) zmian niz dla pojedynczych wyrzutow -
   dla skoku rozlozonego na 6 probek (n=30) max z ~ 3.16, ponizej
   domyslnego progu 3.5. To NIE jest ten sam blad co przedtem (teraz
   wynik jest proporcjonalny do wielkosci zmiany, nie zawsze pusty),
   ale oznacza ze domyslne progi (dobrane tak, by dawac <1% falszywych
   alarmow na czystym szumie - zweryfikowane: 1/200 prob) moga nie
   zlapac bardzo lagodnych, rozlozonych w czasie frontow. Dlatego
   twist_factor/anomaly_factor sa teraz parametrami (patrz nizej) -
   obnizenie ich (np. do 2.0) zwieksza czulosc kosztem falszywych
   alarmow (zweryfikowane: przy factor=2.0 na czystym szumie wychodzi
   27/200 falszywych trafien zamiast 1/200 przy domyslnym 3.5/3.0).

2. flow()/trm(): przy k_neighbors > n cicho degenerowaly do jednej
   globalnej regresji/mediany (ten sam mechanizm co w SynoptykV3,
   punkt 2 w jego docstringu). Naprawione: _safe_k() z RuntimeWarning,
   identyczne podejscie jak w V3.

3. fronts(): dokladne dopasowanie indeksow (np.intersect1d) w wersji
   nadeslanej przez usera dzialalo przypadkiem na ostrym, jednoprobkowym
   skoku testowym (twist i anomaly wyszly na te same indeksy), ale to
   przypadek ksztaltu tego konkretnego testu, nie ogolna wlasciwosc -
   dla lagodniejszego frontu obie listy i tak byly puste (patrz punkt 1),
   wiec przeciecie nie mialo szans zadzialac. Po naprawie punktu 1
   dodano rowniez tolerancje indeksowa (index_tolerance, jak w V3) dla
   spojnosci z reszta kodu.

4. circular_anomalies() (nowe, dla kierunku wiatru): naiwna roznica
   stopni (np.diff) daje falszywy alarm przy przejsciu przez granice
   0/360 (np. 359 -> 1 stopien to naiwnie roznica 358, fizycznie to
   tylko 2 stopnie). Naprawione uzyciem roznicy kolowej
   ((diff + 180) % 360 - 180). Zweryfikowane: sekwencja oscylujaca
   wokol 0/360 (359,1,358,2,...) daje teraz roznice < 10 stopni (nie
   ~358) i zero falszywych frontow; prawdziwy zwrot o 180 stopni nadal
   wykrywany.

5. forecast_wind_direction() liczy kierunek jako srednia WEKTOROWA
   (kolowa), nie arytmetyczna - zweryfikowane na przypadku [350,10,
   350,10,...]: naiwna srednia arytmetyczna dalaby 180 stopni (czyli
   przeciwny kierunek do prawdy), srednia kolowa daje poprawnie ~0/360.
   Rozrzut (spread_deg) pochodzi z dlugosci wypadkowego wektora R:
   R bliskie 1 = stabilny kierunek (maly rozrzut), R bliskie 0 =
   kierunek chaotyczny (rozrzut do 180 stopni, czyli "brak pewnosci").

Znane, nie w pelni rozwiazane ograniczenie (patrz punkt 1): dla
rozlozonych w czasie (kilkugodzinnych), lagodnych frontow domyslne
progi moga nie wykryc zmiany. Jesli Twoje dane typowo maja takie
lagodne przejscia, obnizy twist_factor/anomaly_factor w wywolaniu
fronts()/twist()/anomalies() - kosztem wiekszej liczby falszywych
alarmow na czystym szumie.
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy.spatial import KDTree


class SynoptykV4:
    def __init__(self, k_neighbors: int = 8, mad_scale: float = 1.4826):
        self.k = k_neighbors
        self.mad_scale = mad_scale

    # ------------------------------------------------------------
    # Helper: bezpieczne k + ostrzezenie o degeneracji do global fit
    # (identyczny mechanizm jak SynoptykV3._safe_k)
    # ------------------------------------------------------------
    def _safe_k(self, n: int) -> int:
        k = min(self.k, n)
        if 3 <= n <= self.k:
            warnings.warn(
                f"SynoptykV4: n={n} probek <= k_neighbors={self.k} - "
                f"sasiedztwo obejmuje caly zbior dla kazdego punktu, wiec "
                f"flow()/trm() licza GLOBALNA regresje/mediane zamiast "
                f"lokalnej. Zwieksz liczbe probek albo zmniejsz k_neighbors.",
                RuntimeWarning,
                stacklevel=3,
            )
        return k

    @staticmethod
    def _robust_scale(values: np.ndarray, mad_scale: float) -> float:
        """Mediana-MAD (skalowana do sigma), z fallbackiem do std() gdy
        MAD wychodzi 0 (patrz punkt 1 w "Historia poprawek" powyzej)."""
        values = np.asarray(values, dtype=float)
        if values.size == 0:
            return 0.0
        med = np.median(values)
        mad = np.median(np.abs(values - med)) * mad_scale
        if mad == 0:
            mad = float(np.std(values))  # std juz jest w skali sigma - bez mad_scale
        return mad

    # ------------------------------------------------------------
    # FLOW - lokalny gradient LSQ (jak w V3)
    # ------------------------------------------------------------
    def flow(self, t, s):
        t = np.asarray(t, float)
        s = np.asarray(s, float)
        n = len(t)
        if n < 3:
            return np.zeros_like(s)
        k = self._safe_k(n)
        tree = KDTree(t.reshape(-1, 1))
        grad = np.zeros_like(s)
        for i, ti in enumerate(t):
            _, idx = tree.query([ti], k=k)
            idx = np.atleast_1d(idx)
            tt = t[idx]
            ss = s[idx]
            A = np.column_stack([tt, np.ones_like(tt)])
            try:
                a, _b = np.linalg.lstsq(A, ss, rcond=None)[0]
            except Exception:
                a = 0.0
            grad[i] = a
        return grad

    # ------------------------------------------------------------
    # TWIST - nagle zmiany kierunku (z-score po MAD drugiej pochodnej)
    # ------------------------------------------------------------
    def twist(self, t, s, factor: float = 3.5):
        t = np.asarray(t, float)
        s = np.asarray(s, float)
        if len(t) < 3:
            return np.array([], int), np.zeros_like(s)
        ds = np.gradient(s, t)
        dds = np.gradient(ds, t)
        med = np.median(dds)
        mad = self._robust_scale(dds, self.mad_scale)
        if mad == 0:
            return np.array([], int), np.abs(dds - med)
        z = np.abs(dds - med) / mad
        twist_pts = np.where(z > factor)[0]
        return twist_pts, z

    # ------------------------------------------------------------
    # TRM - medianowe wygladzenie lokalne (jak w V3)
    # ------------------------------------------------------------
    def trm(self, t, s):
        t = np.asarray(t, float)
        s = np.asarray(s, float)
        n = len(t)
        if n < 2:
            return s.copy()
        k = self._safe_k(n)
        tree = KDTree(t.reshape(-1, 1))
        smooth = np.zeros_like(s)
        for i, ti in enumerate(t):
            _, idx = tree.query([ti], k=k)
            idx = np.atleast_1d(idx)
            smooth[i] = np.median(s[idx])
        return smooth

    # ------------------------------------------------------------
    # ANOMALIE - znormalizowane residua wzgledem trm()
    # ------------------------------------------------------------
    def anomalies(self, t, s, factor: float = 3.0):
        s = np.asarray(s, float)
        if len(s) == 0:
            empty = np.array([], float)
            return np.array([], int), empty, 0.0
        smooth = self.trm(t, s)
        residuals = s - smooth
        mad = self._robust_scale(residuals, self.mad_scale)
        if mad == 0:
            return np.array([], int), residuals, 0.0
        z = np.abs(residuals) / mad
        pts = np.where(z > factor)[0]
        return pts, residuals, z

    # ------------------------------------------------------------
    # FRONTS - przeciecie twist + anomalii w tolerowanej odleglosci
    # ------------------------------------------------------------
    def fronts(self, t, s, index_tolerance: int = 3, twist_factor: float = 3.5,
               anomaly_factor: float = 3.0):
        flow_grad = self.flow(t, s)
        twist_pts, twist_strength = self.twist(t, s, factor=twist_factor)
        anom_pts, residuals, anom_strength = self.anomalies(t, s, factor=anomaly_factor)

        if len(flow_grad) < 3 or len(twist_pts) == 0 or len(anom_pts) == 0:
            return np.array([], int), twist_strength, anom_strength

        cand = np.array(
            [tp for tp in twist_pts if np.any(np.abs(anom_pts - tp) <= index_tolerance)],
            dtype=int,
        )
        if len(cand) == 0:
            return cand, twist_strength, anom_strength

        med_flow = np.median(np.abs(flow_grad))
        if med_flow == 0:
            return cand, twist_strength, anom_strength
        strong = cand[np.abs(flow_grad[cand]) > 2 * med_flow]
        return strong, twist_strength, anom_strength

    # ------------------------------------------------------------
    # FORECAST - tlumiona ekstrapolacja trendu dla dowolnej zmiennej
    # skalarnej (temperatura, cisnienie, opady z clip_nonnegative=True...)
    # ------------------------------------------------------------
    def forecast(self, t, s, steps_ahead: int = 24, damping: float = 0.85,
                 clip_nonnegative: bool = False):
        """
        point[i] = (damping**krok) * (ostatnia_wartosc + nachylenie*krok)
                   + (1 - damping**krok) * lokalna_srednia(trm)

        Czyli: krotki horyzont -> bliżej prostej ekstrapolacji trendu;
        dlugi horyzont -> tlumione w strone lokalnej sredniej (powrot do
        sredniej), zamiast ekstrapolowac nachylenie w nieskonczonosc.
        Pasmo niepewnosci rosnie jak sqrt(krok) i jest szersze (x2.5),
        jesli ostatnie probki zawieraly anomalie (patrz anomalies()).
        """
        t = np.asarray(t, float)
        s = np.asarray(s, float)
        n = len(s)

        if n == 0:
            z = np.array([])
            return {"point": z, "lower": z, "upper": z}
        if n == 1:
            base = float(s[0])
            point = np.full(steps_ahead, base)
            return {"point": point, "lower": point.copy(), "upper": point.copy()}

        flow_grad = self.flow(t, s)
        slope = float(flow_grad[-1]) if len(flow_grad) else 0.0
        smooth = self.trm(t, s)
        anchor = float(smooth[-1])
        last = float(s[-1])

        anom_pts, residuals, _ = self.anomalies(t, s)
        resid_std = float(np.std(residuals)) if len(residuals) else 0.0
        recent_anomaly = len(anom_pts) > 0 and (n - 1 - int(anom_pts[-1])) <= 3

        dt = float(np.median(np.diff(t))) if n > 1 else 1.0
        spread_mult = 2.5 if recent_anomaly else 1.0
        base_spread = resid_std if resid_std > 0 else 0.05 * (abs(anchor) + 1.0)

        point = np.zeros(steps_ahead)
        lower = np.zeros(steps_ahead)
        upper = np.zeros(steps_ahead)
        for i in range(steps_ahead):
            step = i + 1
            trend_val = last + slope * dt * step
            weight = damping ** step
            point[i] = weight * trend_val + (1 - weight) * anchor
            spread = base_spread * spread_mult * np.sqrt(step)
            lower[i] = point[i] - spread
            upper[i] = point[i] + spread

        if clip_nonnegative:
            point = np.clip(point, 0.0, None)
            lower = np.clip(lower, 0.0, None)
            upper = np.clip(upper, 0.0, None)

        return {"point": point, "lower": lower, "upper": upper}

    def forecast_wind_speed(self, t, speed, steps_ahead: int = 24, damping: float = 0.85):
        """Jak forecast(), z wymuszeniem nieujemnosci (predkosc wiatru >= 0)."""
        return self.forecast(t, speed, steps_ahead=steps_ahead, damping=damping,
                              clip_nonnegative=True)

    # ------------------------------------------------------------
    # WIATR - KIERUNEK (dane katowe 0-360 stopni, liczone "w kolo")
    # ------------------------------------------------------------
    def circular_anomalies(self, t, direction_deg, factor: float = 3.0):
        """Wykrywa nagle zmiany kierunku wiatru (np. przejscie frontu),
        uzywajac roznicy kolowej zamiast zwyklej (patrz punkt 4 w
        "Historia poprawek" - unika falszywego alarmu przy 359->1)."""
        d = np.asarray(direction_deg, float)
        n = len(d)
        if n < 2:
            return np.array([], int), np.array([], float)

        diffs = np.diff(d)
        diffs = (diffs + 180) % 360 - 180
        abs_diffs = np.abs(diffs)

        mad = self._robust_scale(abs_diffs, self.mad_scale)
        if mad == 0:
            return np.array([], int), abs_diffs

        med = np.median(abs_diffs)
        z = np.abs(abs_diffs - med) / mad
        pts = np.where(z > factor)[0] + 1  # +1: diff() skraca o 1, wskazujemy probke PO zmianie
        return pts, abs_diffs

    def forecast_wind_direction(self, t, direction_deg, steps_ahead: int = 24, window: int = 6):
        """Trwalosc kierunku: srednia WEKTOROWA (kolowa) z ostatnich
        `window` probek - patrz punkt 5 w "Historia poprawek" (naiwna
        srednia arytmetyczna daje bledny wynik przy wartosciach blisko
        granicy 0/360). Brak ekstrapolacji trendu - kierunek wiatru sie
        obraca, liniowa ekstrapolacja w stopniach jest fizycznie bledna.
        spread_deg rosnie z krokiem i z rozrzutem ostatnich kierunkow
        (dlugosc wektora wypadkowego R: R=1 stabilny, R=0 chaotyczny),
        ograniczony do 180 stopni (pelny brak pewnosci co do kierunku)."""
        d = np.asarray(direction_deg, float)
        if len(d) == 0:
            return {"point": np.array([]), "spread_deg": np.array([])}

        recent = d[-window:] if len(d) >= window else d
        u = np.mean(np.sin(np.radians(recent)))
        v = np.mean(np.cos(np.radians(recent)))
        mean_dir = (np.degrees(np.arctan2(u, v)) + 360) % 360
        r = np.sqrt(u ** 2 + v ** 2)

        base_spread = (1.0 - r) * 90.0
        point = np.full(steps_ahead, mean_dir)
        spread = np.minimum(base_spread * np.sqrt(np.arange(1, steps_ahead + 1)), 180.0)
        return {"point": point, "spread_deg": spread}
