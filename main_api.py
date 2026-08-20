"""
Synoptyk-F – API & Dashboard Web Service (Real Data Integration)
Uruchomienie: python -m uvicorn main_api:app --reload --port 8000
Wymagania: pip install fastapi uvicorn pydantic requests
"""

import requests
from typing import List
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# --- 1. MODELE DANYCH ---

class NodeData(BaseModel):
    station: str
    altitude_m: float
    uhi_factor_c: float
    predicted_temp_c: float
    precipitation_mm: float
    wind_speed_kmh: float
    resonance_score: float

class ForecastResponse(BaseModel):
    region: str
    days: int
    grid_resolution_deg: float
    timeline: List[str]
    temperature_trend: List[float]
    precipitation_trend: List[float]
    wind_trend: List[float]
    nodes: List[NodeData]

# --- 2. BAZA WĘZŁÓW Z KOORDYNATAMI GEOGRAFICZNYMI ---

TOPOGRAPHY_DB = {
    "malopolska": [
        {"station": "Kraków Centrum", "lat": 50.0614, "lon": 19.9366, "alt": 220, "uhi": 2.1},
        {"station": "Kraków Balice",  "lat": 50.0777, "lon": 19.7848, "alt": 241, "uhi": 0.3},
        {"station": "Tarnów",         "lat": 50.0138, "lon": 20.9869, "alt": 209, "uhi": 1.4},
        {"station": "Zakopane",       "lat": 49.2990, "lon": 19.9496, "alt": 838, "uhi": -0.5},
    ],
    "poland": [
        {"station": "Warszawa", "lat": 52.2297, "lon": 21.0122, "alt": 110, "uhi": 2.5},
        {"station": "Gdańsk",   "lat": 54.3520, "lon": 18.6466, "alt": 12,  "uhi": 0.8},
        {"station": "Wrocław",  "lat": 51.1079, "lon": 17.0385, "alt": 120, "uhi": 1.9},
        {"station": "Poznań",   "lat": 52.4064, "lon": 16.9252, "alt": 80,  "uhi": 1.5},
    ],
    "europe": [
        {"station": "Berlin", "lat": 52.5200, "lon": 13.4050, "alt": 34,  "uhi": 1.8},
        {"station": "Paryż",  "lat": 48.8566, "lon": 2.3522,  "alt": 35,  "uhi": 2.2},
        {"station": "Madryt", "lat": 40.4168, "lon": -3.7038, "alt": 667, "uhi": 2.0},
        {"station": "Rzym",   "lat": 41.9028, "lon": 12.4964, "alt": 20,  "uhi": 1.6},
    ]
}

# --- 3. SILNIK POBIERANIA I PRZETWARZANIA DANYCH ---

def fetch_open_meteo_data(lat: float, lon: float, days: int):
    """Pobiera rzeczywiste dane z Open-Meteo."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_max,precipitation_sum,wind_speed_10m_max"
        f"&timezone=auto&forecast_days={days}"
    )
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Błąd pobierania danych z Open-Meteo: {e}")
        return None

def calculate_forecast(region: str, days: int, grid: float) -> ForecastResponse:
    reg_key = region.lower()
    if reg_key not in TOPOGRAPHY_DB:
        reg_key = "malopolska"

    nodes_data = []
    base_timeline = []
    base_temp_trend = []
    base_precip_trend = []
    base_wind_trend = []

    for index, item in enumerate(TOPOGRAPHY_DB[reg_key]):
        # Pobieranie danych dla każdej stacji
        weather = fetch_open_meteo_data(item["lat"], item["lon"], days)
        
        if not weather or "daily" not in weather:
            raise HTTPException(status_code=503, detail="Błąd połączenia z API pogodowym")

        daily = weather["daily"]
        
        # Aplikacja korekty mikroklimatycznej Synoptyk-F (UHI) dla pierwszego dnia
        raw_temp = daily["temperature_2m_max"][0]
        adjusted_temp = round(raw_temp + item["uhi"], 1)
        precip = daily["precipitation_sum"][0]
        wind = daily["wind_speed_10m_max"][0]
        
        # Prosty wskaźnik rezonansu (wysoki wiatr + opady + orografia)
        res_score = round(min(1.0, (precip * 0.1) + (wind * 0.01) + (item["alt"] / 2000.0)), 2)

        nodes_data.append(NodeData(
            station=item["station"],
            altitude_m=item["alt"],
            uhi_factor_c=item["uhi"],
            predicted_temp_c=adjusted_temp,
            precipitation_mm=precip,
            wind_speed_kmh=wind,
            resonance_score=res_score,
        ))

        # Zapisanie trendu tylko dla Głównej Stacji (indeks 0) do wykresu
        if index == 0:
            base_timeline = daily["time"]
            # Korekta całego trendu o UHI głównej stacji
            base_temp_trend = [round(t + item["uhi"], 1) for t in daily["temperature_2m_max"]]
            base_precip_trend = daily["precipitation_sum"]
            base_wind_trend = daily["wind_speed_10m_max"]

    return ForecastResponse(
        region=region.upper(),
        days=days,
        grid_resolution_deg=grid,
        timeline=base_timeline,
        temperature_trend=base_temp_trend,
        precipitation_trend=base_precip_trend,
        wind_trend=base_wind_trend,
        nodes=nodes_data,
    )

# --- 4. APLIKACJA FASTAPI ---

app = FastAPI(title="SYNOPTYK-F API")

@app.get("/api/v1/forecast", response_model=ForecastResponse)
def get_forecast(
    region: str = Query("malopolska", description="Region: malopolska, poland, europe"),
    days: int = Query(7, ge=1, le=14, description="Horyzont czasowy (1-14)"),
    grid: float = Query(0.125, ge=0.01, le=1.0, description="Krok siatki w stopniach"),
):
    return calculate_forecast(region, days, grid)

@app.get("/", response_class=HTMLResponse)
def index_page():
    return """
<!DOCTYPE html>
<html lang="pl" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SYNOPTYK-F – Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: { extend: { colors: { brand: { 500: '#3b82f6', 600: '#2563eb' } } } }
        }
    </script>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen flex flex-col font-sans">
    <header class="border-b border-slate-800 bg-slate-950/80 sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-6 py-4 flex justify-between items-center">
            <div class="flex items-center space-x-3">
                <span class="text-3xl">🌀</span>
                <div>
                    <h1 class="text-xl font-bold bg-gradient-to-r from-blue-400 to-teal-400 bg-clip-text text-transparent">SYNOPTYK-F</h1>
                    <p class="text-xs text-slate-400">Live Weather Data Engine</p>
                </div>
            </div>
            <a href="/docs" target="_blank" class="text-xs font-semibold bg-blue-600/20 text-blue-400 border border-blue-500/30 px-3 py-1.5 rounded-lg hover:bg-blue-600/30 transition">API Swagger</a>
        </div>
    </header>

    <main class="max-w-7xl mx-auto px-6 py-8 flex-1 w-full grid grid-cols-1 lg:grid-cols-4 gap-8">
        <!-- Sidebar Controls -->
        <aside class="bg-slate-800/50 border border-slate-700/50 p-6 rounded-2xl h-fit space-y-6">
            <h2 class="text-lg font-semibold border-b border-slate-700 pb-2">⚙️ Parametry</h2>
            <form id="paramForm" class="space-y-4">
                <div>
                    <label class="block text-xs font-medium text-slate-400 mb-1">Region</label>
                    <select id="region" class="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500">
                        <option value="malopolska">Małopolska</option>
                        <option value="poland">Polska</option>
                        <option value="europe">Europa</option>
                    </select>
                </div>
                <div>
                    <label class="block text-xs font-medium text-slate-400 mb-1">Horyzont (dni): <span id="daysVal" class="text-blue-400">7</span></label>
                    <input type="range" id="days" min="1" max="14" value="7" class="w-full accent-blue-500" oninput="document.getElementById('daysVal').innerText = this.value">
                </div>
                <button type="button" onclick="loadForecast()" class="w-full bg-blue-600 hover:bg-blue-500 text-white font-medium py-2.5 rounded-lg transition text-sm shadow-lg shadow-blue-600/20">
                    Pobierz Dane Realne
                </button>
            </form>
        </aside>

        <!-- Main Content -->
        <section class="lg:col-span-3 space-y-8">
            <!-- Chart Box -->
            <div class="bg-slate-800/50 border border-slate-700/50 p-6 rounded-2xl">
                <h2 class="text-lg font-semibold mb-4 flex justify-between items-center">
                    <span>📈 Zestawienie: Temperatura vs Opady (Stacja Główna)</span>
                    <span id="badgeRegion" class="text-xs bg-blue-900/60 text-blue-300 border border-blue-700/50 px-2.5 py-1 rounded-md">MAŁOPOLSKA</span>
                </h2>
                <div class="relative h-64">
                    <canvas id="forecastChart"></canvas>
                </div>
            </div>

            <!-- Nodes Table -->
            <div class="bg-slate-800/50 border border-slate-700/50 p-6 rounded-2xl">
                <h2 class="text-lg font-semibold mb-4">📍 Stacje Węzłowe (Dane na Dzień 1)</h2>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-sm text-slate-300">
                        <thead class="bg-slate-900/80 text-xs uppercase text-slate-400 border-b border-slate-700">
                            <tr>
                                <th class="p-3">Stacja</th>
                                <th class="p-3">UHI</th>
                                <th class="p-3">Temp. Max</th>
                                <th class="p-3">Opady</th>
                                <th class="p-3">Wiatr Max</th>
                                <th class="p-3">Rezonans</th>
                            </tr>
                        </thead>
                        <tbody id="nodesTable" class="divide-y divide-slate-700/50">
                            <!-- Wstrzykiwane przez JS -->
                        </tbody>
                    </table>
                </div>
            </div>
        </section>
    </main>

    <script>
        let chartInstance = null;

        async function loadForecast() {
            const region = document.getElementById('region').value;
            const days = document.getElementById('days').value;
            document.getElementById('badgeRegion').innerText = region.toUpperCase();

            try {
                // Pobieranie danych z endpointu FastAPI
                const res = await fetch(`/api/v1/forecast?region=${region}&days=${days}`);
                if (!res.ok) throw new Error("Błąd pobierania danych API");
                const data = await res.json();

                renderChart(data.timeline, data.temperature_trend, data.precipitation_trend);
                renderTable(data.nodes);
            } catch (err) {
                console.error(err);
                alert("Nie udało się pobrać danych. Sprawdź logi serwera.");
            }
        }

        function renderChart(labels, temp_values, precip_values) {
            const ctx = document.getElementById('forecastChart').getContext('2d');
            if (chartInstance) chartInstance.destroy();

            chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            type: 'line',
                            label: 'Temperatura Max (°C)',
                            data: temp_values,
                            borderColor: '#ef4444',
                            backgroundColor: 'rgba(239, 68, 68, 0.1)',
                            borderWidth: 3,
                            yAxisID: 'y',
                            tension: 0.4
                        },
                        {
                            type: 'bar',
                            label: 'Opady (mm)',
                            data: precip_values,
                            backgroundColor: 'rgba(56, 189, 248, 0.6)',
                            yAxisID: 'y1'
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: { 
                            type: 'linear', 
                            position: 'left',
                            title: { display: true, text: 'Temperatura (°C)', color: '#94a3b8' },
                            grid: { color: 'rgba(255,255,255,0.05)' },
                            ticks: { color: '#94a3b8' }
                        },
                        y1: { 
                            type: 'linear', 
                            position: 'right',
                            title: { display: true, text: 'Opady (mm)', color: '#94a3b8' },
                            grid: { drawOnChartArea: false },
                            ticks: { color: '#94a3b8' }
                        },
                        x: { 
                            grid: { color: 'rgba(255,255,255,0.05)' }, 
                            ticks: { color: '#94a3b8' } 
                        }
                    }
                }
            });
        }

        function renderTable(nodes) {
            const tbody = document.getElementById('nodesTable');
            tbody.innerHTML = nodes.map(n => `
                <tr class="hover:bg-slate-700/30 transition">
                    <td class="p-3 font-medium text-white">${n.station}</td>
                    <td class="p-3 ${n.uhi_factor_c > 0 ? 'text-amber-400' : 'text-blue-400'}">
                        ${n.uhi_factor_c > 0 ? '+' : ''}${n.uhi_factor_c} °C
                    </td>
                    <td class="p-3 font-semibold text-red-400">${n.predicted_temp_c} °C</td>
                    <td class="p-3 text-sky-400 font-medium">${n.precipitation_mm} mm</td>
                    <td class="p-3 text-slate-300">${n.wind_speed_kmh} km/h</td>
                    <td class="p-3">
                        <span class="px-2 py-0.5 rounded text-xs ${n.resonance_score > 0.6 ? 'bg-red-900/50 text-red-300' : 'bg-emerald-900/50 text-emerald-300'}">
                            ${n.resonance_score}
                        </span>
                    </td>
                </tr>
            `).join('');
        }

        // Automatyczne załadowanie przy starcie
        loadForecast();
    </script>
</body>
</html>
    """