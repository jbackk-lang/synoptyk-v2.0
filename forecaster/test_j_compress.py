"""
test_j_compress.py — stary vs nowy j_compress / j_decompress

UWAGA (naprawa): oryginalna wersja tego pliku ładowała "stary" kod z
zewnętrznych ścieżek (/mnt/user-data/uploads/..., /home/claude/...),
które nie są częścią repozytorium — plik nie odpalał się w ogóle.
Zachowanie starej wersji jest w pełni opisane w docstringach
j_compress.py / j_decompress.py ("Zastępuje starą wersję, która..."),
więc odtwarzamy je tutaj lokalnie jako proste funkcje referencyjne
(old_compress / old_decompress), zamiast wczytywać nieistniejące pliki.
Nowy kod importujemy bezpośrednio z pakietu.
"""
import math
import random

import pytest

from . import j_compress as new_c
from . import j_decompress as new_d


# ── Rekonstrukcja starego zachowania (opisanego w docstringach) ──────────────
# Stary j_compress: redukował sygnał do (mean, std) i bezpowrotnie tracił
# strukturę. Stary j_decompress: generował random.gauss(mean, std) zamiast
# odtwarzać oryginalny sygnał (niedeterministyczne, gubi anomalie).

def old_compress(data):
    if not data:
        return 0.0, 0.0
    n = len(data)
    mean = sum(data) / n
    var = sum((x - mean) ** 2 for x in data) / n
    return mean, var ** 0.5


def old_decompress(mean, std, length):
    return [random.gauss(mean, std) for _ in range(length)]


# ── sygnał testowy: 7 dni godzinowy z anomalią w godzinie 72 ─────────────────
SIGNAL = [15 + 8 * math.sin(i * 2 * math.pi / 24) for i in range(168)]
SIGNAL[72] = 45.0  # anomalia +30°C


def corr(a, b):
    """Korelacja Pearsona."""
    n = len(a)
    ma = sum(a) / n
    mb = sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    return num / (da * db) if da * db > 0 else 0.0


# ══════════════════════════════════════════════════════════════════════════
# STARE ZACHOWANIE — udokumentowane referencyjnie
# ══════════════════════════════════════════════════════════════════════════

class TestOldBehaviorReference:
    """Referencyjna rekonstrukcja starego zachowania (nie jest już używana
    w kodzie produkcyjnym — służy tylko jako punkt odniesienia w testach)."""

    def test_old_roundtrip_correlation_is_low(self):
        random.seed(42)
        mean, std = old_compress(SIGNAL)
        recon = old_decompress(mean, std, len(SIGNAL))
        c = corr(SIGNAL, recon)
        assert abs(c) < 0.3, f"Korelacja={c:.4f}"

    def test_old_anomaly_lost(self):
        mean, std = old_compress(SIGNAL)
        random.seed(0)
        recon = old_decompress(mean, std, len(SIGNAL))
        assert max(recon) < 35.0, "Anomalia powinna zniknąć w starym kodzie"

    def test_old_nondeterministic(self):
        mean, std = old_compress(SIGNAL)
        r1 = old_decompress(mean, std, 50)
        r2 = old_decompress(mean, std, 50)
        assert r1 != r2, "Stary kod jest niedeterministyczny"


# ══════════════════════════════════════════════════════════════════════════
# NOWE ZACHOWANIE — j_compress.py / j_decompress.py z repo
# ══════════════════════════════════════════════════════════════════════════

class TestNewAPI:
    def test_new_roundtrip_high_correlation(self):
        compressed = new_c.j_compress(SIGNAL, threshold_ratio=0.0)  # lossless
        recon = new_d.j_decompress(compressed)
        c = corr(SIGNAL, recon)
        assert c > 0.999, f"Korelacja={c:.4f} — lossless roundtrip powinien być ~1.0"

    def test_new_denoised_roundtrip_correlation(self):
        compressed = new_c.j_compress(SIGNAL, threshold_ratio=0.04)
        recon = new_d.j_decompress(compressed)
        c = corr(SIGNAL, recon)
        assert c > 0.97, f"Korelacja={c:.4f}"

    def test_new_anomaly_partially_preserved(self):
        compressed = new_c.j_compress(SIGNAL, threshold_ratio=0.04)
        recon = new_d.j_decompress(compressed)
        assert recon[72] > 25.0, f"Anomalia zaniknęła: recon[72]={recon[72]:.1f}"

    def test_new_is_deterministic(self):
        c1 = new_c.j_compress(SIGNAL)
        c2 = new_c.j_compress(SIGNAL)
        r1 = new_d.j_decompress(c1)
        r2 = new_d.j_decompress(c2)
        assert r1 == r2, "Nowy kod musi być deterministyczny"

    def test_new_length_preserved(self):
        for n in [8, 32, 64, 168, 256]:
            sig = [math.sin(i * 0.3) for i in range(n)]
            comp = new_c.j_compress(sig)
            rec = new_d.j_decompress(comp)
            assert len(rec) == n, f"n={n}: długość {len(rec)} != {n}"

    def test_new_legacy_api_deterministic(self):
        mean, std = 20.0, 5.0
        r1 = new_d.j_decompress(mean, std, 100)
        r2 = new_d.j_decompress(mean, std, 100)
        assert r1 == r2, "Legacy API musi być deterministyczne"

    def test_new_empty_signal(self):
        comp = new_c.j_compress([])
        recon = new_d.j_decompress(comp)
        assert recon == []

    def test_compress_returns_dict(self):
        comp = new_c.j_compress(SIGNAL)
        assert isinstance(comp, dict)
        assert 'coeffs' in comp
        assert 'original_len' in comp
        assert comp['original_len'] == len(SIGNAL)
        # 'mean' i 'std' MUSZĄ zostać w dict — SynopticF i TIMDRForecast
        # rozpakowują je jako compressed['mean'] / compressed['std'].
        assert 'mean' in comp and 'std' in comp


# ══════════════════════════════════════════════════════════════════════════
# REGRESJA: to jest dokładnie ten bug, który uszedł uwadze, bo ten plik
# testowy nie dało się wcześniej uruchomić (zahardkodowane zewnętrzne
# ścieżki). SynopticF i TIMDRForecast robiły `mean, std = j_compress(window)`
# — ale nowy j_compress zwraca dict (7 kluczy), nie krotkę (mean, std),
# więc unpacking rzucał ValueError przy KAŻDYM wywołaniu.
# ══════════════════════════════════════════════════════════════════════════

class TestCallSiteRegression:
    def test_j_compress_result_is_not_a_2tuple(self):
        """Dokumentuje, dlaczego `mean, std = j_compress(window)` jest błędne."""
        comp = new_c.j_compress(SIGNAL[:10])
        with pytest.raises(ValueError):
            mean, std = comp  # to jest dokładnie bug, który wystąpił w SynopticF

    def test_synoptic_f_extract_figure_does_not_crash(self):
        import pandas as pd
        from .synoptic_f import SynopticF

        df = pd.DataFrame({'temp': SIGNAL[:20]})
        sf = SynopticF(figure_window=7)
        fig = sf._extract_figure(df, 'temp')
        assert 'mean' in fig and 'std' in fig
        forecast = sf._generate_forecast(fig, steps=3)
        assert len(forecast) == 3

    def test_timdr_forecast_param_does_not_crash(self):
        import pandas as pd
        from .timdr_forecast import TIMDRForecast

        df = pd.DataFrame({'temp': SIGNAL[:30]})
        tf = TIMDRForecast(figure_window_days=1)
        result = tf._forecast_param(df, 'temp', steps=3, timdr_results={})
        assert len(result['forecast']) == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
