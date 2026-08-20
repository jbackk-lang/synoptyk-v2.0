# topomap_data.py

TOPOGRAPHY_DATABASE = {
    "Warszawa": {"lat": 52.2297, "lon": 21.0122, "altitude": 100, "uhi_factor": 1.8},
    "Krakow_Centrum": {"lat": 50.0647, "lon": 19.9450, "altitude": 220, "uhi_factor": 2.2},
    "Gdansk": {"lat": 54.3520, "lon": 18.6466, "altitude": 10, "uhi_factor": 1.2},
    "Wroclaw": {"lat": 51.1100, "lon": 17.0333, "altitude": 120, "uhi_factor": 1.9},
    "Poznan": {"lat": 52.4064, "lon": 16.9252, "altitude": 80, "uhi_factor": 1.5},
    "Katowice": {"lat": 50.2649, "lon": 19.0238, "altitude": 270, "uhi_factor": 2.0},
    "Zakopane": {"lat": 49.2994, "lon": 19.9496, "altitude": 840, "uhi_factor": 0.5},
}

DEFAULT_METADATA = {
    "lat": 52.0000,
    "lon": 19.0000,
    "altitude": 150,
    "uhi_factor": 1.0,
    "description": "Domyślny węzeł topograficzny"
}

def get_node_metadata(node_name: str) -> dict:
    """Pobiera metadane dla danego węzła. Jeśli brak w bazie – zwraca wartości bezpieczne/domyślne."""
    if node_name in TOPOGRAPHY_DATABASE:
        return TOPOGRAPHY_DATABASE[node_name]
    
    # Próba dopasowania bez wielkości liter
    for key, val in TOPOGRAPHY_DATABASE.items():
        if key.lower() == node_name.lower():
            return val
            
    # Bezpieczny fallback (brak zgłaszania wyjątku)
    meta = DEFAULT_METADATA.copy()
    meta["name"] = node_name
    return meta