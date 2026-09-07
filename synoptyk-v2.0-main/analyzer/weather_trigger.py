# analyzer/weather_trigger.py
# ============================================
# TIMDR Weather Trigger Module
# ============================================
#
# ROLA: czujnik sygnałowy — NIE model, NIE prognoza (do tego służy
# forecast()/forecast_wind_speed()/forecast_wind_direction() w
# synoptyk_v4.py). Dispatcher nad już przetestowanym SynoptykV4
# (test_synoptyk_v4.py) — jedyna jego robota: zapytać fronts()/anomalies()/
# twist()/circular_anomalies() i powiedzieć, KTÓRY typ zdarzenia się
# odpalił, w KTÓRYM kanale (parametrze pogodowym) i GDZIE (indeks próbki).
#
# ZASTANY STAN (powód budowy tego pliku): SynoptykV4.fronts()/twist()/
# anomalies()/circular_anomalies() są w pełni napisane i przetestowane
# (test_synoptyk_v4.py), ale NIE są wywoływane NIGDZIE w działającej
# aplikacji (api/main.py używa innego, niezależnego modułu synoptyk/trend.py;
# gui_app.py woła TYLKO SynoptykV4(...).forecast(), nigdy fronts()/twist()/
# anomalies()/circular_anomalies()) — sprawdzone grepem po całym repo.
# Osobno, TIMDRAnalyzer.analyze() (analyzer/timdr_analyzer.py) robi coś
# podobnego (anomalia/defekt/rezonans/skręt) i JEST wołane w gui_app.py,
# ale nie ma własnych testów (brak test_timdr_analyzer.py w repo) — ten
# dispatcher świadomie budowany jest na SynoptykV4 (mniej dojrzały pod
# względem wiazania z GUI, ale solidnie przetestowany), nie na
# TIMDRAnalyzer, żeby nie stawiać nowego kodu na nieprzetestowanym
# fundamencie (patrz zasada z timdr-signal-framework: dispatcher nigdy
# nie liczy własnej statystyki, tylko woła już zweryfikowane detektory).
#
# Priorytet: FRONT (fronts() — twist ORAZ anomalia się zgadzają w tym
# samym kanale, tolerancja indeksowa — najsilniejszy, potwierdzony
# dwoma niezależnymi detektorami dowód) > ANOMALY (anomalies() albo,
# dla kanału kierunku wiatru, circular_anomalies() — pojedynczy,
# potwierdzony sygnał) > TWIST (twist() samo — z dokumentacji
# "Historia poprawek" pkt 1 w synoptyk_v4.py: najbardziej podatny na
# subtelne, rozłożone w czasie fronty, ale też najszumiący z trzech) >
# NONE. W obrębie tej samej kategorii, gdy kilka kanałów flaguje
# równolegle, wygrywa najmniejszy indeks czasowy (najwcześniejszy sygnał),
# niezależnie od kolejności kanałów w słowniku `channels`.

from enum import Enum

from .synoptyk_v4 import SynoptykV4


class WeatherTriggerType(Enum):
    FRONT = "front"
    ANOMALY = "anomaly"
    TWIST = "twist"
    NONE = "none"


class WeatherTriggerResult:
    def __init__(self, triggered=False, trigger_type=WeatherTriggerType.NONE,
                 location=None, channel=None, message=""):
        self.triggered = triggered
        self.trigger_type = trigger_type
        self.location = location
        self.channel = channel
        self.message = message

    def as_dict(self):
        return {
            "triggered": self.triggered,
            "type": self.trigger_type.value,
            "location": self.location,
            "channel": self.channel,
            "message": self.message,
        }


class WeatherTrigger:
    """
    Dispatcher nad SynoptykV4. `engine` można wstrzyknąć (np. w testach) -
    domyślnie tworzy prawdziwy SynoptykV4(). Progi (twist_factor,
    anomaly_factor, front_tolerance) to te same punkty startowe do
    dostrojenia co w reszcie ekosystemu TIMDR, nie wartości uniwersalne -
    patrz "Historia poprawek" w synoptyk_v4.py.
    """

    def __init__(self, twist_factor=3.5, anomaly_factor=3.0, front_tolerance=3, engine=None):
        self.engine = engine if engine is not None else SynoptykV4()
        self.twist_factor = twist_factor
        self.anomaly_factor = anomaly_factor
        self.front_tolerance = front_tolerance
        self.last_result = WeatherTriggerResult()

    def analyze(self, t, channels, wind_direction_channel=None):
        """
        channels: {nazwa_kanału: wartości} - kanały SKALARNE (temp,
        pressure, wind_speed, ...), wszystkie tej samej długości co `t`.
        wind_direction_channel: opcjonalnie nazwa JEDNEGO z kanałów w
        `channels`, który reprezentuje kierunek wiatru w stopniach
        (0-360) - dla niego liczona jest circular_anomalies() (różnica
        kołowa) zamiast anomalies(), i NIE liczone jest dla niego
        fronts()/twist() (te metody różniczkują wartość, co nie ma
        fizycznego sensu dla kąta bez zawinięcia - patrz
        circular_anomalies() w synoptyk_v4.py).
        """
        front_hits = {}
        anomaly_hits = {}
        twist_hits = {}

        for name, vals in channels.items():
            if name == wind_direction_channel:
                idx, _abs_diffs = self.engine.circular_anomalies(
                    t, vals, factor=self.anomaly_factor,
                )
                if len(idx):
                    anomaly_hits[name] = int(min(idx))
                continue

            front_idx, _twist_z, _anom_z = self.engine.fronts(
                t, vals, index_tolerance=self.front_tolerance,
                twist_factor=self.twist_factor, anomaly_factor=self.anomaly_factor,
            )
            if len(front_idx):
                front_hits[name] = int(min(front_idx))

            anom_idx, _residuals, _z = self.engine.anomalies(t, vals, factor=self.anomaly_factor)
            if len(anom_idx):
                anomaly_hits[name] = int(min(anom_idx))

            twist_idx, _z = self.engine.twist(t, vals, factor=self.twist_factor)
            if len(twist_idx):
                twist_hits[name] = int(min(twist_idx))

        best = self._earliest(front_hits)
        if best is not None:
            loc, channel = best
            return self._set_result(
                True, WeatherTriggerType.FRONT, loc, channel,
                f"Front pogodowy (twist i anomalia się zgadzają) w kanale '{channel}'."
            )

        best = self._earliest(anomaly_hits)
        if best is not None:
            loc, channel = best
            return self._set_result(
                True, WeatherTriggerType.ANOMALY, loc, channel,
                f"Anomalia statystyczna w kanale '{channel}'."
            )

        best = self._earliest(twist_hits)
        if best is not None:
            loc, channel = best
            return self._set_result(
                True, WeatherTriggerType.TWIST, loc, channel,
                f"Nagła zmiana trendu (twist) w kanale '{channel}'."
            )

        return self._set_result(
            False, WeatherTriggerType.NONE, None, None,
            "Brak wykrytego zdarzenia sygnałowego."
        )

    @staticmethod
    def _earliest(hits):
        """hits: {nazwa_kanału: indeks}. Zwraca (indeks, nazwa) dla
        najmniejszego indeksu, albo None jeśli słownik jest pusty."""
        best = None
        for name, idx in hits.items():
            if best is None or idx < best[0]:
                best = (idx, name)
        return best

    def _set_result(self, triggered, trigger_type, location, channel, message):
        self.last_result = WeatherTriggerResult(triggered, trigger_type, location, channel, message)
        return self.last_result

    def get_last(self):
        return self.last_result
