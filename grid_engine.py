"""
Grid Engine – Generator przestrzennych siatek geograficznych
"""

from typing import Dict, Tuple
import numpy as np


class SpatialGridEngine:
    def __init__(self, bbox: Tuple[float, float, float, float], resolution: float):
        """
        bbox: (min_lat, max_lat, min_lon, max_lon)
        resolution: krok siatki w stopniach (np. 0.125)
        """
        self.min_lat, self.max_lat, self.min_lon, self.max_lon = bbox
        self.resolution = resolution

    def generate_mesh(self) -> Dict[str, np.ndarray]:
        """Generuje współrzędne siatki geograficznej."""
        lats = np.arange(self.min_lat, self.max_lat + self.resolution, self.resolution)
        lons = np.arange(self.min_lon, self.max_lon + self.resolution, self.resolution)
        grid_lon, grid_lat = np.meshgrid(lons, lats)
        return {
            "latitudes": grid_lat,
            "longitudes": grid_lon,
            "shape": grid_lat.shape,
        }


def get_region_bbox(region_name: str) -> Tuple[float, float, float, float]:
    """Zwraca granice przestrzenne dla wybranego regionu.

    Rzuca ValueError dla nieznanego regionu zamiast po cichu spadać do
    Małopolski — wcześniej zapytanie o dowolny nierozpoznany region (np.
    'ameryka') dawało w wyniku dokładnie tę samą siatkę co dla Krakowa,
    bez żadnego ostrzeżenia."""
    regions = {
        "malopolska": (49.1, 50.5, 19.0, 21.5),
        "poland": (49.0, 54.8, 14.1, 24.1),
        "europe": (35.0, 71.0, -10.0, 40.0),
        "usa_northeast": (38.0, 45.0, -80.0, -66.0),
        "usa_west": (32.0, 49.0, -125.0, -114.0),
        "usa": (24.5, 49.4, -125.0, -66.9),
    }
    key = region_name.lower()
    if key not in regions:
        raise ValueError(
            f"Nieznany region: {region_name!r}. Dostępne regiony: {sorted(regions)}"
        )
    return regions[key]