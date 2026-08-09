# forecaster/j_compress.py
"""
Kompresja J v2 — falkowa kompresja szeregu czasowego.

Zastępuje starą wersję która redukuje sygnał do (mean, std) i bezpowrotnie
traci całą strukturę (trend, cykl dobowy, anomalie).

Nowe podejście: DWT db4 + hard thresholding → zachowana struktura,
odtwarzalny sygnał, deterministyczny roundtrip.

API wstecznie kompatybilne z j_decompress (nowym).
"""

import math


def j_compress(data, threshold_ratio: float = 0.04, level: int = None):
    """
    Kompresja falkowa szeregu czasowego.

    Parametry
    ---------
    data            : lista lub iterowalny obiekt z wartościami float
    threshold_ratio : próg twardego thresholdingu jako ułamek max|koef|
                      0.04 = 4% → dobre odszumianie przy zachowaniu struktury
                      0.0  = brak kompresji (lossless roundtrip)
    level           : głębokość dekompozycji DWT (None = auto)

    Zwraca
    ------
    dict z kluczami:
        'coeffs'       : lista list współczynników (po thresholdingu)
        'wavelet'      : nazwa falki
        'original_len' : długość oryginalnego sygnału
        'mean'         : średnia (do zachowania zgodności ze starym API)
        'std'          : odchylenie standardowe
        'threshold_ratio': użyty próg
    """
    if data is None or len(data) == 0:
        return {'coeffs': [], 'wavelet': 'db4', 'original_len': 0,
                'mean': 0.0, 'std': 0.0, 'threshold_ratio': threshold_ratio}

    signal = [float(x) for x in data]
    n = len(signal)

    # statystyki (zachowane dla zgodności ze starym API)
    mean = sum(signal) / n
    variance = sum((x - mean) ** 2 for x in signal) / n
    std = variance ** 0.5

    # ── DWT bez zewnętrznych bibliotek (Haar jako fallback) ──────────────────
    # Używamy db4 przez PyWavelets jeśli dostępne, inaczej Haar
    try:
        import pywt
        import numpy as np

        arr = np.array(signal, dtype=float)

        # auto level: max poziom przy którym sygnał jest wystarczająco długi
        if level is None:
            max_level = pywt.dwt_max_level(n, 'db4')
            level = min(max_level, 4)

        coeffs_raw = pywt.wavedec(arr, 'db4', level=level)

        # hard thresholding
        all_vals = []
        for c in coeffs_raw:
            all_vals.extend(c.tolist())
        thr = threshold_ratio * max(abs(v) for v in all_vals) if all_vals else 0

        coeffs_out = []
        for c in coeffs_raw:
            c_thr = [v if abs(v) >= thr else 0.0 for v in c.tolist()]
            coeffs_out.append(c_thr)

        wavelet = 'db4'

    except ImportError:
        # Fallback: Haar DWT (czysta Python, bez zależności)
        coeffs_out, wavelet = _haar_compress(signal, threshold_ratio)
        level = len(coeffs_out) - 1

    return {
        'coeffs':          coeffs_out,
        'wavelet':         wavelet,
        'original_len':    n,
        'level':           level,
        'mean':            mean,
        'std':             std,
        'threshold_ratio': threshold_ratio,
    }


# ── Haar DWT fallback (czysta Python) ────────────────────────────────────────

def _haar_compress(signal, threshold_ratio):
    """Prosta kompresja Haar DWT — fallback gdy PyWavelets niedostępny."""
    s = list(signal)
    coeffs = []
    while len(s) >= 2:
        approx  = [(s[i] + s[i+1]) / math.sqrt(2) for i in range(0, len(s)-1, 2)]
        details = [(s[i] - s[i+1]) / math.sqrt(2) for i in range(0, len(s)-1, 2)]
        coeffs.insert(0, details)
        s = approx
        if len(approx) < 2:
            break
    coeffs.insert(0, s)  # approx na czele

    # thresholding
    all_vals = [v for c in coeffs for v in c]
    thr = threshold_ratio * max(abs(v) for v in all_vals) if all_vals else 0
    coeffs_thr = [[v if abs(v) >= thr else 0.0 for v in c] for c in coeffs]

    return coeffs_thr, 'haar'
