"""Approximate travel from Rautatientori to Finnish postcode areas."""
import csv
import re
from math import asin, ceil, cos, radians, sin, sqrt
from pathlib import Path

# Statistics Finland, Paavo 2026 postcode areas, CC BY 4.0. See docs/user-guide.md.
with Path(__file__).with_name("finnish_postcode_areas.csv").open(encoding="utf-8", newline="") as source:
    _DISTRICTS = {
        row["postcode"]: (float(row["latitude"]), float(row["longitude"]))
        for row in csv.DictReader(source)
    }
_ORIGIN = (60.1717, 24.9416)
_POSTAL_CODE = re.compile(r"\b(?:FI-)?([0-9]{5})\b", re.IGNORECASE)


def postal_code_from_address(address: str) -> str | None:
    match = _POSTAL_CODE.search(address)
    return match.group(1) if match else None


def address_without_postcode(address: str) -> str:
    return _POSTAL_CODE.sub("", address).strip(" ,")


def has_street_address_and_postcode(address: str) -> bool:
    """Require a five-digit postcode and some address text."""
    address_text, postcodes = _POSTAL_CODE.subn("", address)
    return postcodes > 0 and any(char.isalnum() for char in address_text)


def estimate(postal_code: str) -> dict:
    result = {"origin": "Rautatientori, Helsinki", "postal_code": postal_code,
              "method": "Postcode area point, distance factor 1.3, 30 km/h, 10–20 minutes for stops"}
    if postal_code not in _DISTRICTS:
        return {**result, "status": "estimate_unavailable", "reason": "postcode_missing_from_geographic_dataset"}
    lat1, lon1 = map(radians, _ORIGIN)
    lat2, lon2 = map(radians, _DISTRICTS[postal_code])
    arc = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    km = 2 * 6371 * asin(sqrt(arc)) * 1.3
    return {**result, "status": "estimated", "distance_km": round(km, 1),
            "travel_minutes_min": ceil((km * 2 + 10) / 5) * 5,
            "travel_minutes_max": ceil((km * 2 + 20) / 5) * 5}
