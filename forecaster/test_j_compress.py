"""
test_new_compress.py — stary vs nowy j_compress / j_decompress
"""
import sys, math, importlib.util
sys.path.insert(0, '/home/claude')
sys.path.insert(0, '/mnt/user-data/uploads')

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

old_c = load('/mnt/user-data/uploads/1786234173504_j_compress.py',   'old_c')
old_d = load('/mnt/user-data/uploads/1786234173505_j_decompress.py', 'old_d')
new_c = load('/home/claude/j_compress_new.py',   'new_c')
new_d = load('/home/claude/j_decompress_new.py', 'new_d')

import pytest

# ── sygnał testowy: 7 dni godzinowy z anomalią w godzinie 72 ─────────────────
SIGNAL = [15 + 8 * math.sin(i * 2 * math.pi / 24) for i in range(168)]
SIGNAL[72] = 45.0   # anomalia +30°C


def corr(a, b):
    """Korelacja Pearsona."""
    n  = len(a)
    ma = sum(a) / n;  mb = sum(b) / n
    num = sum((x-ma)*(y-mb) for x,y in zip(a,b))
    da  = math.sqrt(sum((x-ma)**2 for x in a))
    db  = math.sqrt(sum((y-mb)**2 for y in b))
    return num / (da * db) if da * db > 0 else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# PORÓWNANIE ROUNDTRIP
# ══════════════════════════════════════════════════════════════════════════════

class TestOldAPI:
    """Stara wersja — dokumentujemy jej zachowanie."""

    def test_old_roundtrip_correlation_is_zero(self):
        """Stary kod: roundtrip nie zachowuje sygnału."""
        import random; random.seed(42)
        mean, std  = old_c.j_compress(SIGNAL)
        recon      = old_d.j_decompress(mean, std, len(SIGNAL))
        c = corr(SIGNAL, recon)
        print(f"\n  STARY roundtrip korelacja: {c:.4f}  (oczekiwane ~0)")
        assert abs(c) < 0.3, f"Korelacja={c:.4f}"

    def test_old_anomaly_lost(self):
        """Anomalia 45°C znika w kompresji."""
        mean, std = old_c.j_compress(SIGNAL)
        import random; random.seed(0)
        recon = old_d.j_decompress(mean, std, len(SIGNAL))
        assert max(recon) < 35.0, "Anomalia powinna zniknąć w starym kodzie"

    def test_old_nondeterministic(self):
        mean, std = old_c.j_compress(SIGNAL)
        r1 = old_d.j_decompress(mean, std, 50)
        r2 = old_d.j_decompress(mean, std, 50)
        assert r1 != r2, "Stary kod jest niedeterministyczny"


class TestNewAPI:
    """Nowa wersja — weryfikujemy poprawność."""

    def test_new_roundtrip_high_correlation(self):
        """Nowy kod: roundtrip zachowuje strukturę sygnału."""
        compressed = new_c.j_compress(SIGNAL, threshold_ratio=0.0)  # lossless
        recon      = new_d.j_decompress(compressed)
        c = corr(SIGNAL, recon)
        print(f"\n  NOWY roundtrip korelacja (threshold=0): {c:.4f}  (oczekiwane >0.999)")
        assert c > 0.999, f"Korelacja={c:.4f} — lossless roundtrip powinien być ~1.0"

    def test_new_denoised_roundtrip_correlation(self):
        """Odszumianie (threshold=0.04): wysoka korelacja przy redukcji szumu."""
        compressed = new_c.j_compress(SIGNAL, threshold_ratio=0.04)
        recon      = new_d.j_decompress(compressed)
        c = corr(SIGNAL, recon)
        print(f"\n  NOWY roundtrip korelacja (threshold=0.04): {c:.4f}  (oczekiwane >0.97)")
        assert c > 0.97, f"Korelacja={c:.4f}"

    def test_new_anomaly_partially_preserved(self):
        """Anomalia jest częściowo zachowana po odszumianiu."""
        compressed = new_c.j_compress(SIGNAL, threshold_ratio=0.04)
        recon      = new_d.j_decompress(compressed)
        print(f"\n  Anomalia oryginał: {SIGNAL[72]:.1f}°C  po rekonstrukcji: {recon[72]:.1f}°C")
        assert recon[72] > 25.0, f"Anomalia zaniknęła: recon[72]={recon[72]:.1f}"

    def test_new_is_deterministic(self):
        """Ten sam wejście → identyczne wyjście."""
        c1 = new_c.j_compress(SIGNAL)
        c2 = new_c.j_compress(SIGNAL)
        r1 = new_d.j_decompress(c1)
        r2 = new_d.j_decompress(c2)
        assert r1 == r2, "Nowy kod musi być deterministyczny"

    def test_new_length_preserved(self):
        for n in [8, 32, 64, 168, 256]:
            sig  = [math.sin(i * 0.3) for i in range(n)]
            comp = new_c.j_compress(sig)
            rec  = new_d.j_decompress(comp)
            assert len(rec) == n, f"n={n}: długość {len(rec)} != {n}"

    def test_new_legacy_api_deterministic(self):
        """Legacy API j_decompress(mean, std, length) jest teraz deterministyczne."""
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


# ══════════════════════════════════════════════════════════════════════════════
# TABELA PORÓWNAWCZA
# ══════════════════════════════════════════════════════════════════════════════

def test_summary_table(capsys):
    """Wyświetla tabelę porównawczą stary vs nowy."""
    import random; random.seed(42)

    mean_old, std_old = old_c.j_compress(SIGNAL)
    recon_old         = old_d.j_decompress(mean_old, std_old, len(SIGNAL))
    corr_old          = corr(SIGNAL, recon_old)
    mae_old           = sum(abs(a-b) for a,b in zip(SIGNAL, recon_old)) / len(SIGNAL)

    comp_new  = new_c.j_compress(SIGNAL, threshold_ratio=0.04)
    recon_new = new_d.j_decompress(comp_new)
    corr_new  = corr(SIGNAL, recon_new)
    mae_new   = sum(abs(a-b) for a,b in zip(SIGNAL, recon_new)) / len(SIGNAL)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║          STARY vs NOWY j_compress / j_decompress         ║
╠══════════════════════════╦══════════════╦════════════════╣
║ Właściwość               ║    STARY     ║     NOWY       ║
╠══════════════════════════╬══════════════╬════════════════╣
║ Korelacja roundtrip      ║  {corr_old:+.4f}    ║   {corr_new:+.4f}      ║
║ MAE roundtrip [°C]       ║  {mae_old:7.2f}     ║   {mae_new:7.2f}       ║
║ Anomalia po rekonstrukcji║  {max(recon_old):7.2f}°C  ║   {recon_new[72]:7.2f}°C     ║
║ Deterministyczny         ║     NIE      ║     TAK        ║
║ Struktura zachowana      ║     NIE      ║     TAK        ║
║ Zależności zewnętrzne    ║     brak     ║  pywt (opt.)   ║
╚══════════════════════════╩══════════════╩════════════════╝
""")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])
