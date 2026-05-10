"""
Resolves geographic parking context for a given lat/lon coordinate.

Current implementation uses local mock JSON files.

To replace with live data later, implement the same interface using any of:
  - Tel Aviv Open Data API  (https://opendata.tel-aviv.gov.il)
  - Tel Aviv GIS layers     (WMS / WFS)
  - PostGIS / GeoPandas spatial queries
  - External geocoding APIs (Google Maps, Here, etc.)
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import GeoContext

_DATA_DIR = Path(__file__).parent.parent / "data"


def _load_json(filename: str) -> Any:
    with open(_DATA_DIR / filename, encoding="utf-8") as fh:
        return json.load(fh)


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS-84 points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nearest_zone(lat: float, lon: float, zones: List[Dict]) -> Optional[Dict]:
    best, best_dist = None, float("inf")
    for zone in zones:
        dist = _haversine_meters(lat, lon, zone["center_lat"], zone["center_lon"])
        if dist < best_dist:
            best_dist = dist
            best = zone
    # Only return a zone if we are within its declared radius
    if best and best_dist <= best.get("radius_meters", 999):
        return best
    return None


def _street_rule_at(lat: float, lon: float, street_rules: List[Dict]) -> Optional[Dict]:
    for rule in street_rules:
        lat_ok = rule["lat_range"][0] <= lat <= rule["lat_range"][1]
        lon_ok = rule["lon_range"][0] <= lon <= rule["lon_range"][1]
        if lat_ok and lon_ok:
            return rule
    return None


def get_geo_context(lat: float, lon: float) -> GeoContext:
    """
    Return GeoContext for the given coordinates.

    Resolution priority:
      1. Exact street-rule bounding box (most specific)
      2. Nearest zone centre within declared radius
      3. Empty context (no data for this location)
    """
    zones = _load_json("mock_parking_zones.json")
    street_rules = _load_json("mock_street_rules.json")

    street_rule = _street_rule_at(lat, lon, street_rules)
    nearest_zone = _nearest_zone(lat, lon, zones)

    # Prefer zone from street rule; fall back to nearest zone centroid
    zone_id: Optional[str] = None
    if street_rule:
        zone_id = street_rule.get("zone")
    elif nearest_zone:
        zone_id = nearest_zone["zone_id"]

    return GeoContext(
        lat=lat,
        lon=lon,
        street_name=street_rule["street_name"] if street_rule else None,
        parking_zone=zone_id,
        municipal_restrictions=street_rule["rules"] if street_rule else None,
        source="mock",
    )
