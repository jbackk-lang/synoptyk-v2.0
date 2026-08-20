# analyzer/test_synoptyk_v3.py
"""
Testy regresyjne dla SynoptykV3 (analyzer/synoptyk_v3.py).

Kazdy test odpowiada konkretnemu bledowi znalezionemu i zweryfikowanemu
w trakcie code review (patrz docstring modulu, "Historia poprawek").
Uruchomienie: pytest analyzer/test_synoptyk_v3.py -v
"""
import warnings

import numpy as np
import pytest

from .synoptyk_v3 import SynoptykV3


def make_step(n=30, before=10.0, after=40.0, noise_std=0.1, seed=2):
    t = np.arange(n, dtype=float)
    half = n // 2
    s = np.concatenate([np.full(half, before), np.full(n - half, after)])
    s = s + np.random.default_rng(seed).normal(0, noise_std, n)
    return t, s


def make_cycle(n=500, period=24, amp=1.0, noise_std=0.0, seed=1):
    t = np.arange(n, dtype=float)
    s = amp * np.sin(2 * np.pi * t / period)
    if noise_std:
        s = s + np.random.default_rng(seed).normal(0, noise_std, n)
    return t, s


class TestShortSignalsDoNotCrash:
    """Regresja dla oryginalnego IndexError: KDTree.query(k=k_neighbors)
    z k_neighbors > n zwracalo indeks poza zakresem."""

    @pytest.mark.parametrize("n", [0, 1, 2, 3, 5])
    def test_all_methods_survive_short_signals(self, n):
        syn = SynoptykV3(k_neighbors=12)
        t = np.arange(n, dtype=float)
        s = np.arange(n, dtype=float) * 2.0

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            g = syn.flow(t, s)
            trm = syn.trm(t, s)
            trend, slope = syn.trend(t, s)
            tp, ts = syn.twist(t, s)
            ap, res, th = syn.anomalies(t, s)
            fr, _, _ = syn.fronts(t, s)

        assert len(g) == n
        assert len(trm) == n
        assert len(trend) == n
        assert np.all(np.isfinite(g))
        assert np.all(np.isfinite(trm))

    def test_anomalies_on_empty_signal_no_warnings(self):
        syn = SynoptykV3()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ap, res, th = syn.anomalies(np.array([]), np.array([]))
        assert len(ap) == 0
        assert len(res) == 0
        # regresja: mediana pustej tablicy w numpy generuje RuntimeWarning
        assert not any(issubclass(x.category, RuntimeWarning) for x in w)


class TestSmallWindowWarns:
    """Gdy n <= k_neighbors, sasiedztwo = caly zbior -> global fit zamiast
    lokalnego. To nie jest w pelni naprawialne bez zmiany metody, wiec
    sprawdzamy, ze przynajmniej ostrzegamy zamiast cicho myllic wynik."""

    def test_warns_when_n_within_k_neighbors(self):
        syn = SynoptykV3(k_neighbors=12)
        t = np.array([0., 1., 2., 3., 4.])
        s = np.array([10., 11., 12., 40., 41.])
        with pytest.warns(RuntimeWarning, match="GLOBALNA"):
            syn.flow(t, s)

    def test_no_warning_when_n_larger_than_k(self):
        syn = SynoptykV3(k_neighbors=12)
        t, s = make_step(n=30)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            syn.flow(t, s)
        assert not any(issubclass(x.category, RuntimeWarning) for x in w)


class TestFlowRedundantComputationFixed:
    """Regresja: fronts() liczylo self.flow() dwukrotnie (raz bezposrednio,
    raz wewnatrz self.twist())."""

    def test_flow_called_once_inside_fronts(self, monkeypatch):
        syn = SynoptykV3(k_neighbors=12)
        t, s = make_step(n=30)

        call_count = {"n": 0}
        orig_flow = SynoptykV3.flow

        def counting_flow(self, t, s):
            call_count["n"] += 1
            return orig_flow(self, t, s)

        monkeypatch.setattr(SynoptykV3, "flow", counting_flow)
        syn.fronts(t, s)
        assert call_count["n"] == 1


class TestRhythmNormalization:
    """Regresja: surowa (nieznormalizowana) autokorelacja zanizala sile
    dlugich cykli wzgledem krotkich, bo mniej probek nakladalo sie przy
    wiekszym lag."""

    def test_equal_amplitude_cycles_get_comparable_strength(self):
        syn = SynoptykV3()
        n = 500
        t = np.arange(n, dtype=float)
        daily = np.sin(2 * np.pi * t / 24)
        weekly = np.sin(2 * np.pi * t / 168)
        s = daily + weekly + np.random.default_rng(1).normal(0, 0.3, n)

        corr = syn.rhythm(s)
        corr_norm = corr / corr[0]
        ratio = corr_norm[168] / corr_norm[24]

        # przed poprawka wychodzilo ~0.82 (cykl 168h wygladal na wyraznie
        # slabszy, mimo identycznej amplitudy wejsciowej) - po poprawce
        # powinno byc bliżej 1.0
        assert 0.9 < ratio < 1.5

    def test_peak_at_correct_period_noise_free(self):
        syn = SynoptykV3()
        t, s = make_cycle(n=500, period=24, noise_std=0.0)
        corr = syn.rhythm(s)
        # pierwszy lokalny maksimum (poza lag=0) powinien byc przy lag=24
        peak = None
        for i in range(5, len(corr) - 1):
            if corr[i] > corr[i - 1] and corr[i] > corr[i + 1]:
                peak = i
                break
        assert peak == 24


class TestFrontsToleranceMatch:
    """Regresja: fronts() wymagal identycznego indeksu miedzy twist_pts
    i anomaliami (np.intersect1d), a te dwa sygnaly systematycznie
    peakuja w innych (ale bliskich) indeksach dla tego samego frontu."""

    def test_detects_front_on_clean_step(self):
        syn = SynoptykV3(k_neighbors=12)
        t, s = make_step(n=30, before=10.0, after=40.0, noise_std=0.1)
        strong_fronts, twist_strength, residuals = syn.fronts(t, s)
        assert len(strong_fronts) > 0

    def test_detected_fronts_are_near_true_step_location(self):
        syn = SynoptykV3(k_neighbors=12)
        n = 30
        true_step_idx = n // 2
        t, s = make_step(n=n, before=10.0, after=40.0, noise_std=0.1)
        strong_fronts, _, _ = syn.fronts(t, s, index_tolerance=3)
        assert len(strong_fronts) > 0
        for idx in strong_fronts:
            assert abs(idx - true_step_idx) <= 6

    def test_no_false_front_on_flat_signal(self):
        syn = SynoptykV3(k_neighbors=12)
        t = np.arange(30, dtype=float)
        rng = np.random.default_rng(3)
        s = 20.0 + rng.normal(0, 0.05, 30)  # plaski sygnal, tylko szum
        strong_fronts, _, _ = syn.fronts(t, s)
        assert len(strong_fronts) == 0


class TestTrendAndTrm:
    def test_trend_recovers_linear_signal(self):
        syn = SynoptykV3()
        t = np.arange(50, dtype=float)
        s = 2.0 * t + 5.0
        fitted, slope = syn.trend(t, s)
        assert slope == pytest.approx(2.0, abs=1e-6)
        assert np.allclose(fitted, s, atol=1e-6)

    def test_trm_reduces_noise_spike(self):
        syn = SynoptykV3(k_neighbors=12)
        t = np.arange(40, dtype=float)
        s = np.full(40, 10.0)
        s[20] = 500.0  # pojedynczy, ekstremalny wyrzut
        smoothed = syn.trm(t, s)
        assert smoothed[20] < 100.0  # mediana lokalnego sasiedztwa go tlumi
