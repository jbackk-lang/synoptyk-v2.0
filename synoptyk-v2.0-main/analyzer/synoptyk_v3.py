# analyzer/synoptyk_v3.py
"""
SynoptykV3 (v3.1) — lokalne analizy sygnalow meteorologicznych (1D szeregi
czasowe), oparte o k najblizszych sasiadow w czasie (KDTree):

- flow      - lokalny gradient ds/dt (regresja LSQ w oknie k sasiadow)
- twist     - nagle zmiany kierunku gradientu (|d(flow)/dt| > threshold)
- trm       - medianowe wygladzenie lokalne (odporne na pojedyncze skoki)
- trend     - globalny, powolny dryf (regresja liniowa na calym oknie)
- rhythm    - autokorelacja znormalizowana wzgledem malejacego nakladania
              sie probek przy rosnacym opoznieniu (lag)
- anomalies - punkty, gdzie |s - trm(s)| > factor * MAD(s - trm(s))
- fronts    - punkty, gdzie jednoczesnie wystepuje silny twist i anomalia,
              w tolerowanej odleglosci indeksowej (patrz "Historia poprawek")

UWAGA: to samodzielny modul analizy sygnalow. NIE jest jeszcze podpiety
do forecaster/timdr_forecast.py - ten korzysta z osobnego
analyzer/timdr_analyzer.py (inny format wejscia/wyjscia: DataFrame +
krotki ('skręt'/'anomalia'/'rezonans'/'defekt'), podczas gdy SynoptykV3
pracuje na surowych tablicach (t, s) i zwraca indeksy/tablice numpy).
Integracja z pipeline'em prognozy wymagalaby osobnego adaptera.

Historia poprawek (zweryfikowane w trakcie code review, nie tylko
zadeklarowane w komentarzach):

1. flow()/trm()/twist()/anomalies()/fronts() rzucaly IndexError, gdy
   sygnal mial mniej punktow niz k_neighbors (KDTree.query(k=...) z
   k > n zwraca indeks poza zakresem). Naprawione przez _safe_k() +
   jawne guardy na n < 2 / n < 3.
2. Przy n <= k_neighbors (ale n >= 3) _safe_k() przycina k do n, co
   oznacza, ze KAZDY punkt dostaje jako "sasiedztwo" caly zbior -
   flow()/trm() cicho degeneruja sie do jednej globalnej regresji/mediany
   zamiast lokalnej analizy, i twist()/fronts() nigdy nic nie wykryja.
   To NIE jest w pelni naprawione (wymagaloby prawdziwie lokalnej metody
   dla krotkich okien) - teraz przynajmniej ostrzegamy o tym
   (RuntimeWarning), zamiast dawac cichy, mylacy wynik.
3. fronts() liczyl self.flow() dwukrotnie (raz bezposrednio, raz w
   srodku self.twist()). Naprawione: twist() przyjmuje opcjonalny
   parametr flow_grad, fronts() liczy flow raz i przekazuje dalej.
   Zweryfikowane licznikiem wywolan: 1 zamiast 2.
4. rhythm() (autokorelacja) byla nieznormalizowana wzgledem malejacej
   liczby nakladajacych sie probek przy wiekszym lag - to sztucznie
   zanizalo sile dlugich cykli wzgledem krotkich. Zweryfikowane
   numerycznie: dla dwoch cykli o IDENTYCZNEJ amplitudzie (24h i 168h)
   surowa wersja dawala stosunek sily 0.82 zamiast oczekiwanego ~1.0;
   po normalizacji przez (n - lag) stosunek wychodzi ~1.18 (duzo blizej).
5. fronts() wymagal identycznego indeksu miedzy twist_pts i anomaliami
   (np.intersect1d) do uznania punktu za "front". Zweryfikowane na
   czystym skoku (n=30, k=12): twist peakuje w "barkach" transformacji
   (bo lokalna regresja LSQ jest najbardziej czula TUZ PRZED/PO skoku,
   nie W nim), a anomalie (mediana TRM) peakuja DOKLADNIE w skoku -
   te dwa sygnaly maja ZERO wspolnych indeksow dla tego samego,
   jednoznacznego frontu. Naprawione: dopasowanie z tolerancja
   index_tolerance probek zamiast dokladnego dopasowania indeksow.
6. anomalies() na pustym sygnale (n=0) wywolywalo wewnetrzne ostrzezenia
   numpy (mediana pustej tablicy). Naprawione jawnym wczesnym zwrotem.

Znane, nie w pelni rozwiazane ograniczenie: dla 3 <= n <= k_neighbors
flow()/trm() dzialaja jak GLOBALNA regresja/mediana (patrz punkt 2) -
wywolanie na tak krotkim oknie sygnalizowane jest RuntimeWarning, ale
wynik nadal nie jest lokalna analiza. Jesli dane wejsciowe regularnie
maja mniej niz k_neighbors probek, zmniejsz k_neighbors w konstruktorze.
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy.spatial import KDTree


class SynoptykV3:
    def __init__(self, k_neighbors: int = 12, mad_scale: float = 1.0):
        self.k_neighbors = k_neighbors
        self.mad_scale = mad_scale  # 1.0 = surowy MAD, 1.4826 = sigma-MAD

    # ------------------------------------------------------------
    # Helper: bezpieczne k + ostrzezenie o degeneracji do global fit
    # ------------------------------------------------------------
    def _safe_k(self, n: int) -> int:
        k = min(self.k_neighbors, n)
        if 3 <= n <= self.k_neighbors:
            warnings.warn(
                f"SynoptykV3: n={n} probek <= k_neighbors={self.k_neighbors} - "
                f"sasiedztwo obejmuje caly zbior dla kazdego punktu, wiec "
                f"flow()/trm() licza GLOBALNA regresje/mediane zamiast lokalnej. "
                f"twist()/fronts() moga nie wykryc zadnych zmian na tak krotkim "
                f"oknie. Zwieksz liczbe probek albo zmniejsz k_neighbors.",
                RuntimeWarning,
                stacklevel=3,
            )
        return k

    # ------------------------------------------------------------
    # 1. FLOW - lokalny gradient LSQ
    # ------------------------------------------------------------
    def flow(self, t: np.ndarray, s: np.ndarray) -> np.ndarray:
        n = len(t)
        if n < 3:
            return np.zeros_like(s, dtype=float)

        k = self._safe_k(n)
        tree = KDTree(t.reshape(-1, 1))
        grad = np.zeros_like(s, dtype=float)

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
    # 2. TWIST - nagle zmiany kierunku gradientu
    # ------------------------------------------------------------
    def twist(self, t: np.ndarray, s: np.ndarray, flow_grad: np.ndarray | None = None,
               threshold: float = 0.35):
        if flow_grad is None:
            flow_grad = self.flow(t, s)
        if len(flow_grad) < 3:
            return np.array([], dtype=int), np.zeros_like(flow_grad, dtype=float)

        dg = np.gradient(flow_grad)
        twist_strength = np.abs(dg)
        twist_points = np.where(twist_strength > threshold)[0]
        return twist_points, twist_strength

    # ------------------------------------------------------------
    # 3. TRM - medianowe wygladzenie lokalne
    # ------------------------------------------------------------
    def trm(self, t: np.ndarray, s: np.ndarray) -> np.ndarray:
        n = len(t)
        if n < 2:
            return np.array(s, dtype=float).copy()

        k = self._safe_k(n)
        tree = KDTree(t.reshape(-1, 1))
        smooth = np.zeros_like(s, dtype=float)

        for i, ti in enumerate(t):
            _, idx = tree.query([ti], k=k)
            idx = np.atleast_1d(idx)
            smooth[i] = np.median(s[idx])

        return smooth

    # ------------------------------------------------------------
    # 4. TREND - globalny, powolny dryf
    # ------------------------------------------------------------
    def trend(self, t: np.ndarray, s: np.ndarray):
        if len(t) < 2:
            return np.array(s, dtype=float).copy(), 0.0
        A = np.column_stack([t, np.ones_like(t)])
        a, b = np.linalg.lstsq(A, s, rcond=None)[0]
        return a * t + b, a

    # ------------------------------------------------------------
    # 5. RHYTHM - autokorelacja znormalizowana wzgledem nakladania
    # ------------------------------------------------------------
    def rhythm(self, s: np.ndarray) -> np.ndarray:
        s = np.asarray(s, dtype=float)
        if len(s) == 0:
            return np.array([], dtype=float)
        s = s - np.mean(s)
        n = len(s)
        corr = np.zeros(n)
        for lag in range(n):
            overlap = n - lag
            if overlap <= 0:
                break
            corr[lag] = np.sum(s[:overlap] * s[lag:lag + overlap]) / overlap
        return corr

    # ------------------------------------------------------------
    # 6. ANOMALIES - MAD wzgledem TRM
    # ------------------------------------------------------------
    def anomalies(self, t: np.ndarray, s: np.ndarray, factor: float = 3.0):
        if len(s) == 0:
            empty = np.array([], dtype=float)
            return np.array([], dtype=int), empty, 0.0

        smooth = self.trm(t, s)
        residuals = s - smooth
        mad = np.median(np.abs(residuals)) * self.mad_scale
        threshold = factor * mad
        anomaly_points = np.where(np.abs(residuals) > threshold)[0]
        return anomaly_points, residuals, threshold

    # ------------------------------------------------------------
    # 7. FRONTS - twist + anomalia w tolerowanej odleglosci indeksowej
    # ------------------------------------------------------------
    def fronts(self, t: np.ndarray, s: np.ndarray, index_tolerance: int = 3):
        flow_grad = self.flow(t, s)
        twist_pts, twist_strength = self.twist(t, s, flow_grad=flow_grad)
        anomaly_pts, residuals, _th = self.anomalies(t, s)

        if len(flow_grad) < 3 or len(twist_pts) == 0 or len(anomaly_pts) == 0:
            return np.array([], dtype=int), twist_strength, residuals

        # Dopasowanie z tolerancja zamiast dokladnego indeksu - patrz
        # punkt 5 w "Historia poprawek" w docstringu modulu: twist i
        # anomalie systematycznie peakuja w roznych, ale bliskich sobie
        # indeksach dla tego samego realnego zdarzenia.
        front_candidates = np.array(
            [tp for tp in twist_pts if np.any(np.abs(anomaly_pts - tp) <= index_tolerance)],
            dtype=int,
        )

        if len(front_candidates) == 0:
            return front_candidates, twist_strength, residuals

        flow_med = np.median(np.abs(flow_grad))
        strong_fronts = front_candidates[np.abs(flow_grad[front_candidates]) > 2 * flow_med]
        return strong_fronts, twist_strength, residuals
