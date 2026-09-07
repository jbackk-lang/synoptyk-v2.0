# analyzer/test_weather_trigger.py
"""
test_weather_trigger.py — testy weather_trigger.py (WeatherTrigger).

Ten plik NIE re-weryfikuje matematyki SynoptykV4.twist()/anomalies()/
fronts()/circular_anomalies() (już przetestowane w test_synoptyk_v4.py)
- to nie jest robota dispatchera. Dwa rodzaje testów:

1. test_anomaly_na_realnym_pojedynczym_skoku - JEDEN test integracyjny na
   prawdziwym SynoptykV4 (bez mockowania), z ręcznie wyprowadzonymi
   residuami/z-score (pojedynczy skok 10->20 na jednej próbce wśród 10,
   dokładnie ten przypadek, który "Historia poprawek" pkt 1 w
   synoptyk_v4.py opisuje jako motywację do fallbacku std() gdy MAD=0).
2. Reszta testów wstrzykuje fałszywy `engine` (stub zwracający ustalone
   wyniki fronts()/anomalies()/twist()/circular_anomalies()) - testujemy
   WYŁĄCZNIE logikę priorytetów/mapowania dispatchera.
"""
from .weather_trigger import WeatherTrigger, WeatherTriggerType


# ----------------------------------------------------------------------
# 1) Test integracyjny na realnym SynoptykV4
# ----------------------------------------------------------------------

def test_anomaly_na_realnym_pojedynczym_skoku():
    """
    t=[0..9], temp=[10]*10 z pojedynczym skokiem do 20 w idx=5.

    Ręcznie wyprowadzone (KDTree k=8 z n=10 - w każdym punkcie mediana z
    8 najbliższych czasowo próbek zawiera spike'a co najwyżej raz, więc
    trm()=10 wszędzie): residuals=[0,0,0,0,0,10,0,0,0,0].
    _robust_scale: mediana-MAD residuów=0 (9 z 10 wartości to zero) ->
    fallback std(residuals)=3.0 -> mad=3.0. z=|residuals|/3.0, z[5]=3.333
    > factor=3.0 -> anomalies() zwraca pts=[5].

    twist(): dds (druga pochodna) = [0,0,0,2.5,0,-5,0,2.5,0,0] (dwa
    przeciwstawne piki wokół skoku, nie jeden ostry punkt) -> po
    _robust_scale (fallback std(dds)=1.9365) z_max=5/1.9365=2.582 <
    factor=3.5 domyślny -> twist() zwraca PUSTO. Dlatego fronts()
    (wymaga NIEPUSTYCH obu list) też jest puste -> FRONT nie odpala się,
    trafia do ANOMALY.
    """
    n = 10
    t = list(range(n))
    temp = [10.0] * n
    temp[5] = 20.0

    trigger = WeatherTrigger()
    result = trigger.analyze(t, {"temp": temp})

    assert result.triggered is True
    assert result.trigger_type == WeatherTriggerType.ANOMALY
    assert result.location == 5
    assert result.channel == "temp"


# ----------------------------------------------------------------------
# 2) Testy priorytetów/mapowania z wstrzykniętym engine (stub)
# ----------------------------------------------------------------------

class _FakeEngine:
    """Stub o tym samym kontrakcie co SynoptykV4: fronts()/anomalies()/
    twist()/circular_anomalies() zwracają ustalone wyniki niezależnie od
    danych wejściowych, sterowane słownikami {kanał: [indeksy]}."""

    def __init__(self, front=None, anomaly=None, twist=None, circular=None):
        self._front = front or {}
        self._anomaly = anomaly or {}
        self._twist = twist or {}
        self._circular = circular or {}

    def fronts(self, t, s, **kwargs):
        # s to lista wartości - identyfikujemy kanał po jego zawartości
        # przekazanej przez test (patrz _dummy_channels poniżej: każdy
        # kanał to lista jednoelementowa z jego nazwą zakodowaną jako
        # wartość liczbowa umowna) - dla uproszczenia testy same
        # wywołują .analyze() z channels={"nazwa": "nazwa"} i ta klasa
        # rozpoznaje kanał po `s` przekazanym 1:1.
        idx = self._front.get(s, [])
        return (idx, [], [])

    def anomalies(self, t, s, **kwargs):
        idx = self._anomaly.get(s, [])
        return (idx, [], [])

    def twist(self, t, s, **kwargs):
        idx = self._twist.get(s, [])
        return (idx, [])

    def circular_anomalies(self, t, s, **kwargs):
        idx = self._circular.get(s, [])
        return (idx, [])


def _dummy_t():
    return [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_priorytet_front_nad_anomaly_i_twist():
    fake = _FakeEngine(
        front={"a": [5]}, anomaly={"a": [1], "b": [2]}, twist={"a": [3]},
    )
    trigger = WeatherTrigger(engine=fake)
    result = trigger.analyze(_dummy_t(), {"a": "a", "b": "b"})
    assert result.trigger_type == WeatherTriggerType.FRONT
    assert result.location == 5
    assert result.channel == "a"


def test_priorytet_anomaly_nad_twist():
    fake = _FakeEngine(anomaly={"temp": [4]}, twist={"temp": [1], "pressure": [0]})
    trigger = WeatherTrigger(engine=fake)
    result = trigger.analyze(_dummy_t(), {"temp": "temp", "pressure": "pressure"})
    assert result.trigger_type == WeatherTriggerType.ANOMALY
    assert result.location == 4
    assert result.channel == "temp"


def test_twist_gdy_reszta_pusta():
    fake = _FakeEngine(twist={"wind_speed": [7]})
    trigger = WeatherTrigger(engine=fake)
    result = trigger.analyze(_dummy_t(), {"wind_speed": "wind_speed"})
    assert result.triggered is True
    assert result.trigger_type == WeatherTriggerType.TWIST
    assert result.location == 7
    assert result.channel == "wind_speed"


def test_najmniejszy_indeks_wygrywa_miedzy_kanalami_w_tej_samej_kategorii():
    fake = _FakeEngine(anomaly={"pressure": [9], "temp": [2]})
    trigger = WeatherTrigger(engine=fake)
    result = trigger.analyze(_dummy_t(), {"pressure": "pressure", "temp": "temp"})
    assert result.trigger_type == WeatherTriggerType.ANOMALY
    assert result.location == 2
    assert result.channel == "temp"


def test_kanal_kierunku_wiatru_uzywa_circular_anomalies():
    """wind_direction_channel wskazuje kanał, dla którego dispatcher
    woła circular_anomalies() zamiast anomalies()/fronts()/twist()."""
    fake = _FakeEngine(circular={"wind_dir": [6]}, anomaly={"wind_dir": [1]})
    trigger = WeatherTrigger(engine=fake)
    result = trigger.analyze(
        _dummy_t(), {"wind_dir": "wind_dir"}, wind_direction_channel="wind_dir",
    )
    # circular_anomalies() (6), NIE zwykle anomalies() (1) - dowod ze
    # dispatcher faktycznie rozroznia ten kanal
    assert result.trigger_type == WeatherTriggerType.ANOMALY
    assert result.location == 6
    assert result.channel == "wind_dir"


def test_none_gdy_wszystko_puste():
    fake = _FakeEngine()
    trigger = WeatherTrigger(engine=fake)
    result = trigger.analyze(_dummy_t(), {"temp": "temp"})
    assert result.triggered is False
    assert result.trigger_type == WeatherTriggerType.NONE
    assert result.location is None
    assert result.channel is None


def test_get_last_zwraca_ostatni_wynik():
    fake = _FakeEngine(twist={"temp": [3]})
    trigger = WeatherTrigger(engine=fake)
    result = trigger.analyze(_dummy_t(), {"temp": "temp"})
    assert trigger.get_last() is result
