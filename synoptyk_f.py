"""
SYNOPTYK-F Engine – Filtrowanie falkowe i analiza strukturalna,
zintegrowana z sygnałami TIMDR (skręt/anomalia/rezonans/defekt).
"""

import numpy as np
import pywt


class SynoptykFEngine:
    def __init__(self, wavelet: str = "db4", mode: str = "symmetric"):
        self.wavelet = wavelet
        self.mode = mode

    def filter_signal(self, data: np.ndarray, level: int = 2) -> np.ndarray:
        """Usuwa szum z szeregu czasowego za pomocą falki Daubechies."""
        data = np.array(data, dtype=float, copy=True)  # pywt wymaga zapisywalnego bufora
        coeffs = pywt.wavedec(data, self.wavelet, mode=self.mode, level=level)
        # Tłumienie wysokich częstotliwości (szumu)
        threshold = np.std(coeffs[-1]) * np.sqrt(2 * np.log(len(data)))
        coeffs[1:] = [pywt.threshold(c, threshold, mode="soft") for c in coeffs[1:]]
        reconstructed = pywt.waverec(coeffs, self.wavelet, mode=self.mode)
        return reconstructed[: len(data)]

    def calculate_resonance(
        self, temp_field: np.ndarray, humidity_field: np.ndarray
    ) -> np.ndarray:
        """Oblicza wskaźnik rezonansu opadowego/konwekcyjnego."""
        gradient_t = np.gradient(temp_field)
        gradient_h = np.gradient(humidity_field)
        resonance = np.sqrt(gradient_t**2 + gradient_h**2) * (humidity_field / 100.0)
        return np.round(resonance, 3)

    def predict_temperature_step(
        self, base_temp: float, uhi_factor: float, topo_alt: float
    ) -> float:
        """Korekta temperatury o Miejską Wyspę Ciepła (UHI) oraz wysokość n.p.m.
        UWAGA: to jest statyczna korekta punktowa, NIE prognoza — użyj
        predict_temperature_timdr(), żeby uwzględnić realne dane i sygnały TIMDR."""
        lapse_rate = (topo_alt / 100.0) * 0.65
        predicted = base_temp + uhi_factor - lapse_rate
        return round(predicted, 2)

    def predict_temperature_timdr(
        self,
        df,
        uhi_factor: float,
        topo_alt: float,
        timdr_results: dict | None = None,
    ) -> dict:
        """
        Prognoza temperatury faktycznie oparta o dane (nie o stałą 28.0) i o
        sygnały TIMDR:
          1. denoisuje szereg temperatury filtrem falkowym (filter_signal),
          2. bierze ostatnią odszumioną wartość jako base_temp,
          3. liczy rezonans opadowo-konwekcyjny (calculate_resonance) z pary
             temperatura/wilgotność,
          4. koryguje o UHI i gradient termiczny wysokości (jak wcześniej),
          5. jeśli TIMDRAnalyzer wykrył anomalię/defekt/rezonans w ostatnich
             odczytach — poszerza podane pasmo niepewności i dodaje ostrzeżenie
             zamiast milcząco zwracać punktową liczbę.
        """
        temp = df["temp"].dropna().to_numpy(dtype=float)
        humidity = df["humidity"].dropna().to_numpy(dtype=float) if "humidity" in df.columns else None

        if len(temp) < 8:
            base_temp = float(temp[-1]) if len(temp) else 0.0
            resonance_now = None
        else:
            denoised = self.filter_signal(temp, level=2)
            base_temp = float(denoised[-1])
            if humidity is not None and len(humidity) == len(temp):
                humidity_denoised = self.filter_signal(humidity, level=2)
                resonance = self.calculate_resonance(denoised, humidity_denoised)
                resonance_now = float(resonance[-1])
            else:
                resonance_now = None

        lapse_rate = (topo_alt / 100.0) * 0.65
        point = round(base_temp + uhi_factor - lapse_rate, 2)

        timdr_results = timdr_results or {}
        signals_active = []
        for kind in ("anomalia", "defekt", "rezonans"):
            if timdr_results.get(kind):
                signals_active.append(kind)

        uncertainty = 0.5 + 0.7 * len(signals_active)  # °C, rośnie z liczbą aktywnych sygnałów
        note = (
            f"aktywne sygnały TIMDR: {', '.join(signals_active)} — podwyższona niepewność"
            if signals_active else "brak aktywnych sygnałów TIMDR w ostatnim oknie"
        )

        return {
            "point": point,
            "lower": round(point - uncertainty, 2),
            "upper": round(point + uncertainty, 2),
            "base_temp_denoised": round(base_temp, 2),
            "resonance": resonance_now,
            "timdr_note": note,
        }


if __name__ == "__main__":
    engine = SynoptykFEngine()
    test_data = np.array([35.0, 34.5, 25.0, 26.0, 27.0, 30.0, 28.0])
    filtered = engine.filter_signal(test_data)
    print("Sygnał po filtrowaniu falkowym:", filtered)