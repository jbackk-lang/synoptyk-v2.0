# analyzer/test_synoptyk_v4.py
"""
Testy regresyjne dla SynoptykV4 (analyzer/synoptyk_v4.py).

Kazdy test odpowiada konkretnemu bledowi znalezionemu i zweryfikowanemu
w trakcie code review kodu nadeslanego przez usera (patrz docstring
modulu, "Historia poprawek").
Uruchomienie: pytest analyzer/test_synoptyk_v4.py -v
"""
import warnings

import numpy as np
import pytest

from .synoptyk_v4 import SynoptykV4


def make_step(n=30, before=10.0, after=20.0, noise_std=0.05, seed=0):
    t = np.arange(n, dtype=float)
    half = n // 2
    s = np.concatenate([np.full(half, before), np.full(n - half, after)])
    s = s + np.random.default_rng(seed).normal(0, noise_std, n)
    return t, s


def make_gradual_ramp(n=30, before=10.0, after=20.0, ramp_len=6):
    t = np.arange(n, dtype=float)
    flat_each = (n - ramp_len) // 2
    s = np.concatenate([
        np.full(flat_each, before),
        np.linspace(before, after, ramp_len),
        np.full(n - flat_each - ramp_len, after),
    ])
    return t, s


class TestShortSignalsDoNotCrash:
    """Regresja: KDTree.query(k=k_neighbors) z k_neighbors > n rzuca
    IndexError bez guardu (ten sam blad klasy co w SynoptykV3)."""

    @pytest.mark.parametrize("n", [0, 1, 2, 3, 5])
    def test_all_methods_survive_short_signals(self, n):
        syn = SynoptykV4(k_neighbors=8)
        t = np.arange(n, dtype=float)
        s = np.arange(n, dtype=float) * 2.0

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            g = syn.flow(t, s)
            trm = syn.trm(t, s)
            tp, tz = syn.twist(t, s)
            ap, res, z = syn.anomalies(t, s)
            fr, _, _ = syn.fronts(t, s)
            fc = syn.forecast(t, s, steps_ahead=5)

        assert len(g) == n
        assert len(trm) == n
        assert np.all(np.isfinite(g))
        assert np.all(np.isfinite(trm))
        assert len(fc["point"]) == (5 if n > 0 else 0)

    def test_anomalies_on_empty_signal_no_warnings(self):
        syn = SynoptykV4()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            ap, res, z = syn.anomalies(np.array([]), np.array([]))
        assert len(ap) == 0
        assert len(res) == 0
        assert not any(issubclass(x.category, RuntimeWarning) for x in w)

    def test_forecast_single_point_holds_constant(self):
        syn = SynoptykV4()
        fc = syn.forecast(np.array([0.0]), np.array([12.3]), steps_ahead=5)
        assert np.all(fc["point"] == 12.3)
        assert np.all(fc["lower"] == 12.3) and np.all(fc["upper"] == 12.3)


class TestSmallWindowWarns:
    """Gdy n <= k_neighbors, sasiedztwo = caly zbior -> global fit."""

    def test_warns_when_n_within_k_neighbors(self):
        syn = SynoptykV4(k_neighbors=8)
        t = np.array([0., 1., 2., 3., 4.])
        s = np.array([10., 10.2, 15.0, 15.1, 15.3])
        with pytest.warns(RuntimeWarning, match="GLOBALNA"):
            syn.flow(t, s)

    def test_no_warning_when_n_larger_than_k(self):
        syn = SynoptykV4(k_neighbors=8)
        t, s = make_step(n=30)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            syn.flow(t, s)
        assert not any(issubclass(x.category, RuntimeWarning) for x in w)


class TestMadZeroFallback:
    """Regresja: gdy MAD (mediana-bazowana) wychodzi dokladnie 0 - normalne
    dla frontu na tle dlugiego plaskiego sygnalu - poprzedni kod zwracal
    PUSTY wynik bezwarunkowo, niezaleznie od wielkosci zmiany."""

    def test_flat_signal_still_gives_empty_no_false_positive(self):
        syn = SynoptykV4()
        t = np.arange(30, dtype=float)
        s = np.full(30, 15.0)
        twist_pts, _ = syn.twist(t, s)
        anom_pts, _, _ = syn.anomalies(t, s)
        assert len(twist_pts) == 0
        assert len(anom_pts) == 0

    def test_sharp_single_sample_step_detected_with_default_threshold(self):
        syn = SynoptykV4()
        t, s = make_step(n=30)
        fr, _, _ = syn.fronts(t, s)
        assert len(fr) > 0

    def test_gradual_ramp_no_longer_unconditionally_empty(self):
        """Kluczowa regresja: przed poprawka mad=0 -> zawsze pusty wynik,
        bez wzgledu na wielkosc zmiany. Po poprawce mad>0 (fallback do
        std()), wiec wynik jest proporcjonalny - obnizenie progu wykrywa
        front, ktory wczesniej byl NIEWYKRYWALNY przy zadnym rozsadnym
        progu (bo mad byl dokladnie zero)."""
        syn = SynoptykV4()
        t, s = make_gradual_ramp(n=30, ramp_len=6)

        # z domyslnymi progami moze nie wykryc (patrz "Historia poprawek",
        # punkt 1) - ale mad NIE MOZE byc zero (to byla istota buga)
        ds = np.gradient(s, t)
        dds = np.gradient(ds, t)
        assert syn._robust_scale(dds, syn.mad_scale) > 0

        # z obnizonym progiem (tunable, jak udokumentowano) wykrywa
        fr, _, _ = syn.fronts(t, s, twist_factor=2.0, anomaly_factor=2.0)
        assert len(fr) > 0

    def test_lowered_threshold_false_positive_rate_is_bounded(self):
        """Sprawdza, ze obnizenie progu (2.0/2.0) na czystym szumie nie
        eksploduje w liczbie falszywych alarmow (zweryfikowane: ~13%,
        akceptowalne jako opt-in, NIE jako domyslne zachowanie)."""
        syn = SynoptykV4()
        t = np.arange(30, dtype=float)
        rng = np.random.default_rng(42)
        false_pos = 0
        trials = 100
        for _ in range(trials):
            s = 15.0 + rng.normal(0, 0.3, 30)
            fr, _, _ = syn.fronts(t, s, twist_factor=2.0, anomaly_factor=2.0)
            if len(fr) > 0:
                false_pos += 1
        assert false_pos / trials < 0.3

    def test_default_threshold_false_positive_rate_is_very_low(self):
        syn = SynoptykV4()
        t = np.arange(30, dtype=float)
        rng = np.random.default_rng(42)
        false_pos = 0
        trials = 100
        for _ in range(trials):
            s = 15.0 + rng.normal(0, 0.3, 30)
            fr, _, _ = syn.fronts(t, s)
            if len(fr) > 0:
                false_pos += 1
        assert false_pos / trials < 0.05


class TestForecast:
    def test_constant_signal_forecasts_constant(self):
        syn = SynoptykV4()
        t = np.arange(30, dtype=float)
        s = np.full(30, 18.0)
        fc = syn.forecast(t, s, steps_ahead=10)
        assert np.allclose(fc["point"], 18.0, atol=1e-6)
        assert np.all(fc["upper"] >= fc["point"])
        assert np.all(fc["lower"] <= fc["point"])

    def test_trend_extrapolation_is_damped_not_runaway(self):
        """forecast() tlumi nachylenie w strone lokalnej sredniej zamiast
        ekstrapolowac liniowo w nieskonczonosc (w odroznieniu od naiwnej
        czysto-liniowej ekstrapolacji, ktora - jak juz zweryfikowano w
        forecaster/timdr_forecast.py - jest zrodlem ciepłego obciazenia
        prognoz w GUI)."""
        syn = SynoptykV4()
        t = np.arange(30, dtype=float)
        s = 10.0 + 0.5 * t
        fc = syn.forecast(t, s, steps_ahead=20, damping=0.85)
        naive_linear = float(s[-1]) + 0.5 * 20
        assert fc["point"][-1] < naive_linear

    def test_uncertainty_band_grows_with_horizon(self):
        syn = SynoptykV4()
        t, s = make_step(n=30)
        fc = syn.forecast(t, s, steps_ahead=15)
        width = fc["upper"] - fc["lower"]
        assert np.all(np.diff(width) >= -1e-9)

    def test_wind_speed_forecast_never_negative(self):
        syn = SynoptykV4()
        t = np.arange(30, dtype=float)
        s = np.linspace(5.0, 0.2, 30)  # opadajacy wiatr
        fc = syn.forecast_wind_speed(t, s, steps_ahead=15)
        assert np.all(fc["point"] >= 0)
        assert np.all(fc["lower"] >= 0)


class TestWindDirection:
    """Regresja: kierunek wiatru to dana katowa (0-360), zwykla
    arytmetyka (roznice, srednia) daje bledne wyniki w poblizu granicy
    0/360."""

    def test_circular_mean_correct_near_wraparound(self):
        t = np.arange(6, dtype=float)
        d = np.array([350.0, 10.0, 350.0, 10.0, 350.0, 10.0])
        syn = SynoptykV4()
        fc = syn.forecast_wind_direction(t, d, steps_ahead=5)
        md = fc["point"][0]
        # naiwna srednia arytmetyczna dalaby ~180 (przeciwny kierunek!)
        assert md < 30 or md > 330

    def test_no_false_anomaly_at_wraparound_boundary(self):
        t = np.arange(8, dtype=float)
        d = np.array([359.0, 1.0, 358.0, 2.0, 359.0, 1.0, 358.0, 2.0])
        syn = SynoptykV4()
        pts, abs_diffs = syn.circular_anomalies(t, d)
        assert np.all(abs_diffs < 10)
        assert len(pts) == 0

    def test_real_180_degree_flip_is_detected(self):
        t = np.arange(20, dtype=float)
        d = np.concatenate([np.full(10, 90.0), np.full(10, 270.0)])
        syn = SynoptykV4()
        pts, _ = syn.circular_anomalies(t, d)
        assert len(pts) > 0

    def test_scattered_direction_gives_wider_spread_than_stable(self):
        t = np.arange(10, dtype=float)
        rng = np.random.default_rng(1)
        d_stable = np.full(10, 45.0)
        d_scattered = rng.uniform(0, 360, 10)
        syn = SynoptykV4()
        fc_stable = syn.forecast_wind_direction(t, d_stable, steps_ahead=5)
        fc_scattered = syn.forecast_wind_direction(t, d_scattered, steps_ahead=5)
        assert fc_stable["spread_deg"][0] < fc_scattered["spread_deg"][0]

    def test_circular_anomalies_short_signal_no_crash(self):
        syn = SynoptykV4()
        pts, diffs = syn.circular_anomalies(np.array([0.0]), np.array([180.0]))
        assert len(pts) == 0
        pts, diffs = syn.circular_anomalies(np.array([]), np.array([]))
        assert len(pts) == 0
