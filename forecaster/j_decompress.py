# forecaster/j_decompress.py
"""
Dekompresja J v2 — deterministyczna rekonstrukcja sygnału z DWT.

Zastępuje starą wersję która generowała random.gauss(mean, std)
zamiast odtwarzać oryginalny sygnał.

Wstecznie kompatybilna ze starym API:
  j_decompress(mean, std, length)  → nadal działa (tryb legacy)
  j_decompress(compressed_dict)    → nowy tryb falkowy
"""


def j_decompress(mean_or_dict, std=None, length=None):
    """
    Rekonstrukcja sygnału.

    Tryb 1 — nowy (dict z j_compress):
        j_decompress({'coeffs': ..., 'wavelet': 'db4', 'original_len': 168, ...})
        → deterministyczna rekonstrukcja falkowa

    Tryb 2 — legacy (3 argumenty):
        j_decompress(mean, std, length)
        → zwraca sygnał stały (mean) z zakłóceniem ±std/10
          ZAMIAST losowego gauss — teraz deterministyczny
    """
    if isinstance(mean_or_dict, dict):
        return _decompress_wavelet(mean_or_dict)
    else:
        return _decompress_legacy(mean_or_dict, std, length)


# ── Tryb 1: rekonstrukcja falkowa ────────────────────────────────────────────

def _decompress_wavelet(compressed: dict) -> list:
    """Odtwarza sygnał z coeffs DWT."""
    if not compressed.get('coeffs'):
        return []

    original_len = compressed['original_len']
    wavelet      = compressed.get('wavelet', 'db4')
    coeffs       = compressed['coeffs']

    if original_len == 0:
        return []

    try:
        import pywt
        import numpy as np

        coeffs_np = [np.array(c, dtype=float) for c in coeffs]
        reconstructed = pywt.waverec(coeffs_np, wavelet)
        # IDWT może dodać 1 próbkę — przycinamy do oryginalnej długości
        return reconstructed[:original_len].tolist()

    except ImportError:
        # Fallback: Haar IDWT
        return _haar_decompress(coeffs, original_len)


def _haar_decompress(coeffs: list, original_len: int) -> list:
    """Odwrotna transformata Haar — fallback bez PyWavelets."""
    import math
    s = list(coeffs[0])
    for details in coeffs[1:]:
        new_s = []
        for a, d in zip(s, details):
            new_s.append((a + d) / math.sqrt(2))
            new_s.append((a - d) / math.sqrt(2))
        s = new_s
    return s[:original_len]


# ── Tryb 2: legacy API ───────────────────────────────────────────────────────

def _decompress_legacy(mean: float, std: float, length: int) -> list:
    """
    Zachowuje stary interfejs j_decompress(mean, std, length)
    ale ZASTĘPUJE random.gauss deterministycznym sygnałem:
    zwraca sygnał sinusoidalny o amplitudzie std i średniej mean.

    Dlaczego sinusoida a nie gauss?
    - Dane pogodowe mają cykl dobowy → sinusoida lepiej aproksymuje strukturę
    - Deterministyczność: ten sam wejście → ten samo wyjście
    - Nie traci anomalii tak agresywnie jak czyste (mean, std)

    UWAGA: to nadal jest aproksymacja, nie rekonstrukcja.
    Używaj nowego API (dict) dla prawdziwej rekonstrukcji.
    """
    import math

    if length is None or length <= 0:
        return []

    # Sinusoida o amplitudzie std i okresie 24 (cykl dobowy)
    period = min(24, length)
    result = [
        mean + std * math.sin(2 * math.pi * i / period)
        for i in range(length)
    ]
    return result
