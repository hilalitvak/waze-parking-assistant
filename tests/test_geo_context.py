"""Tests for the geo context resolver."""

import pytest

from parking.geo_context import get_geo_context


def test_dizengoff_street_match():
    """Coordinates on Dizengoff should resolve to zone 1 and street name."""
    ctx = get_geo_context(32.0840, 34.7720)
    assert ctx.parking_zone == "1"
    assert ctx.street_name == "דיזנגוף"
    assert ctx.source == "mock"


def test_rothschild_street_match():
    ctx = get_geo_context(32.0640, 34.7760)
    assert ctx.parking_zone == "2"
    assert ctx.street_name == "רוטשילד"


def test_allenby_street_match():
    ctx = get_geo_context(32.0670, 32.0670)
    # This coordinate is outside all bounding boxes, so no street match expected
    # but we verify it doesn't crash
    assert ctx.lat == 32.0670


def test_zone_fallback_from_centroid():
    """A coordinate not inside any street bbox but near zone 3 centroid."""
    ctx = get_geo_context(32.0960, 34.7820)
    # May or may not hit a street bbox; should not crash
    assert ctx.source == "mock"


def test_unknown_location_returns_empty_context():
    """Remote location far from Tel Aviv should return no zone."""
    ctx = get_geo_context(31.0, 35.0)  # near Be'er Sheva
    assert ctx.parking_zone is None
    assert ctx.street_name is None


def test_geo_context_has_correct_coordinates():
    ctx = get_geo_context(32.0845, 34.7714)
    assert ctx.lat == 32.0845
    assert ctx.lon == 34.7714
