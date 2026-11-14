"""Approximate road travel from Rautatientori to selected Helsinki-region postal districts."""
from math import asin, ceil, cos, radians, sin, sqrt

# Representative points for the challenge demo, in latitude/longitude.
_DISTRICTS = {
    "00100": (60.169, 24.931), "00120": (60.161, 24.938), "00130": (60.164, 24.949),
    "00200": (60.158, 24.877), "00240": (60.204, 24.920), "00250": (60.190, 24.912),
    "00290": (60.192, 24.898), "00500": (60.188, 24.957), "00520": (60.201, 24.937),
    "00700": (60.250, 25.013), "00930": (60.211, 25.085), "02100": (60.177, 24.801),
    "02150": (60.186, 24.825), "02600": (60.219, 24.810), "02700": (60.211, 24.728),
    "01300": (60.294, 25.039), "01510": (60.303, 24.972),
}
_ORIGIN = (60.1717, 24.9416)


def estimate(postal_code: str) -> dict:
    result = {"origin": "Rautatientori, Helsinki", "postal_code": postal_code,
              "method": "District centroid, road distance factor 1.3, 30 km/h, 10–20 minutes for stops"}
    if postal_code not in _DISTRICTS:
        return {**result, "status": "unsupported_postal_code"}
    lat1, lon1 = map(radians, _ORIGIN)
    lat2, lon2 = map(radians, _DISTRICTS[postal_code])
    arc = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    km = 2 * 6371 * asin(sqrt(arc)) * 1.3
    return {**result, "status": "estimated", "distance_km": round(km, 1),
            "travel_minutes_min": ceil((km * 2 + 10) / 5) * 5,
            "travel_minutes_max": ceil((km * 2 + 20) / 5) * 5}
