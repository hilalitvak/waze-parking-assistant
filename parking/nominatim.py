"""Geocoding and reverse geocoding via Nominatim (OpenStreetMap). No API key needed."""

from __future__ import annotations

import requests
from typing import Optional, Tuple

_HEADERS = {"User-Agent": "TLV-Parking-Assistant/1.0 (educational project)"}
_BASE = "https://nominatim.openstreetmap.org"


def reverse_geocode(lat: float, lon: float) -> Optional[dict]:
    try:
        r = requests.get(
            f"{_BASE}/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "accept-language": "he"},
            headers=_HEADERS,
            timeout=5,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def geocode(query: str) -> Optional[Tuple[float, float]]:
    try:
        r = requests.get(
            f"{_BASE}/search",
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "il"},
            headers=_HEADERS,
            timeout=5,
        )
        r.raise_for_status()
        results = r.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
        return None
    except Exception:
        return None
