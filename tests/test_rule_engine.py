"""Tests for the deterministic parking rule engine."""

from datetime import datetime

import pytest

from parking.models import GeoContext, ParkingRequest, ParsedParkingSign, TimeRule
from parking.rule_engine import TLVParkingRuleEngine
from parking.user_profile import UserProfile, VehicleProfile

engine = TLVParkingRuleEngine()


# ── Fixtures ──────────────────────────────────────────────────────────────

def _geo(zone=None) -> GeoContext:
    return GeoContext(lat=32.08, lon=34.77, parking_zone=zone, source="mock")


def _sign_free_then_resident(zone="1") -> ParsedParkingSign:
    """Free until 17:00, resident-only 17:00–09:00."""
    return ParsedParkingSign(
        raw_text="",
        free_until="17:00",
        resident_only_windows=[TimeRule(start_time="17:00", end_time="09:00")],
        resident_zone=zone,
        confidence="high",
    )


def _sign_resident_all_times(zone="1") -> ParsedParkingSign:
    return ParsedParkingSign(
        raw_text="",
        resident_only_all_times=True,
        resident_zone=zone,
        confidence="high",
    )


def _sign_no_parking_window(start="07:00", end="10:00") -> ParsedParkingSign:
    return ParsedParkingSign(
        raw_text="",
        no_parking_windows=[TimeRule(start_time=start, end_time=end)],
        confidence="high",
    )


def _sign_ambiguous_no_zone() -> ParsedParkingSign:
    from parking.models import AmbiguityWarning
    return ParsedParkingSign(
        raw_text="",
        resident_only_all_times=True,
        resident_zone=None,
        confidence="medium",
        ambiguities=[
            AmbiguityWarning(
                field="resident_zone",
                message_he="השלט מציין תו אזורי אך לא צוין מספר האזור.",
            )
        ],
    )


# ── A: Free period & after free-period ───────────────────────────────────

def test_free_period_no_profile():
    """During free period, anyone can park (no profile needed)."""
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 14, 0),  # 14:00 < 17:00
    )
    result = engine.decide(req, _geo(), _sign_free_then_resident())
    assert result.can_park is True
    assert result.confidence == "high"


def test_free_period_remaining_time():
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 16, 0),
    )
    result = engine.decide(req, _geo(), _sign_free_then_resident())
    assert result.can_park is True
    assert result.remaining_time is not None   # "שעה" or similar


# ── B: User profile has matching resident permit ──────────────────────────

def test_user_profile_matching_zone():
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),  # after 17:00
        user_profile=UserProfile(user_id="u1", resident_parking_zones=["1"]),
    )
    result = engine.decide(req, _geo(), _sign_free_then_resident(zone="1"))
    assert result.can_park is True
    assert result.confidence == "high"


# ── B2: Vehicle profile has matching resident permit ──────────────────────

def test_vehicle_profile_matching_zone():
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),
        vehicle_profile=VehicleProfile(
            vehicle_id="v1",
            resident_parking_permits=["1"],
        ),
    )
    result = engine.decide(req, _geo(), _sign_free_then_resident(zone="1"))
    assert result.can_park is True
    assert result.confidence == "high"


# ── C: User has no permit (wrong zone) ───────────────────────────────────

def test_user_profile_wrong_zone():
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),
        user_profile=UserProfile(user_id="u2", resident_parking_zones=["2"]),
    )
    result = engine.decide(req, _geo(), _sign_free_then_resident(zone="1"))
    assert result.can_park is False
    assert result.confidence == "high"


def test_user_profile_empty_zones():
    """User profile provided but with no zones → explicitly no permit."""
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),
        user_profile=UserProfile(user_id="u3", resident_parking_zones=[]),
    )
    result = engine.decide(req, _geo(), _sign_resident_all_times(zone="1"))
    assert result.can_park is False


# ── D: Missing permit information ─────────────────────────────────────────

def test_missing_permit_info_returns_null():
    """No profile provided → engine cannot decide → None."""
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),
        # No user_zone, user_profile, or vehicle_profile
    )
    result = engine.decide(req, _geo(), _sign_resident_all_times(zone="1"))
    assert result.can_park is None


# ── E: No-parking during specific hours ──────────────────────────────────

def test_no_parking_during_window():
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 8, 0),  # 08:00 inside 07:00-10:00
    )
    result = engine.decide(req, _geo(), _sign_no_parking_window())
    assert result.can_park is False
    assert result.remaining_time is not None


def test_parking_allowed_outside_no_parking_window():
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 11, 0),  # 11:00 outside 07:00-10:00
    )
    result = engine.decide(req, _geo(), _sign_no_parking_window())
    assert result.can_park is True


# ── F: Ambiguous sign – sign has no zone, GeoContext provides it ──────────

def test_geo_context_fills_missing_zone():
    """Sign missing zone → engine falls back to geo_context.parking_zone."""
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),
        user_profile=UserProfile(user_id="u4", resident_parking_zones=["1"]),
    )
    geo = _geo(zone="1")   # GeoContext knows the zone
    result = engine.decide(req, geo, _sign_ambiguous_no_zone())
    assert result.can_park is True


def test_geo_context_wrong_zone():
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),
        user_profile=UserProfile(user_id="u5", resident_parking_zones=["2"]),
    )
    geo = _geo(zone="1")
    result = engine.decide(req, geo, _sign_ambiguous_no_zone())
    assert result.can_park is False


def test_sign_and_geo_both_missing_zone():
    """Both sign and geo have no zone → cannot decide."""
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),
        user_profile=UserProfile(user_id="u6", resident_parking_zones=["1"]),
    )
    result = engine.decide(req, _geo(zone=None), _sign_ambiguous_no_zone())
    assert result.can_park is None


# ── G: Commercial vehicle – loading zone ──────────────────────────────────

def test_loading_zone_with_permit():
    sign = ParsedParkingSign(raw_text="", loading_zone=True, confidence="high")
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 10, 0),
        vehicle_profile=VehicleProfile(
            vehicle_id="truck1",
            vehicle_type="commercial",
            commercial_loading_permit=True,
        ),
    )
    result = engine.decide(req, _geo(), sign)
    assert result.can_park is True


def test_loading_zone_without_permit():
    sign = ParsedParkingSign(raw_text="", loading_zone=True, confidence="high")
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 10, 0),
        vehicle_profile=VehicleProfile(vehicle_id="car1"),
    )
    result = engine.decide(req, _geo(), sign)
    assert result.can_park is False


# ── H: Disabled permit ────────────────────────────────────────────────────

def test_disabled_permit_overrides_resident_restriction():
    """Disabled permit should allow parking even in a resident-only zone."""
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),
        user_profile=UserProfile(
            user_id="u7",
            resident_parking_zones=[],
            disabled_parking_permit=True,
        ),
    )
    result = engine.decide(req, _geo(), _sign_resident_all_times(zone="1"))
    assert result.can_park is True


def test_disabled_bay_with_permit():
    sign = ParsedParkingSign(raw_text="", disabled_only=True, confidence="high")
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 10, 0),
        vehicle_profile=VehicleProfile(
            vehicle_id="v_disabled",
            disabled_parking_permit=True,
        ),
    )
    result = engine.decide(req, _geo(), sign)
    assert result.can_park is True


def test_disabled_bay_without_permit():
    sign = ParsedParkingSign(raw_text="", disabled_only=True, confidence="high")
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 10, 0),
    )
    result = engine.decide(req, _geo(), sign)
    assert result.can_park is False


# ── I: Weekday restriction – outside restricted days ──────────────────────

def test_resident_window_does_not_apply_on_weekend():
    """Resident window only on weekdays א-ה should not fire on Saturday."""
    sign = ParsedParkingSign(
        raw_text="",
        resident_only_windows=[
            TimeRule(
                start_time="17:00",
                end_time="09:00",
                days=["א", "ב", "ג", "ד", "ה"],
            )
        ],
        resident_zone="1",
        confidence="high",
    )
    # 2026-05-02 is a Saturday
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 2, 20, 0),
        user_profile=UserProfile(user_id="u8", resident_parking_zones=[]),
    )
    result = engine.decide(req, _geo(), sign)
    # Window doesn't apply on Saturday → parking allowed
    assert result.can_park is True


# ── J: No sign → unknown ─────────────────────────────────────────────────

def test_no_sign_no_geo_data():
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 12, 0),
    )
    result = engine.decide(req, _geo(), None)
    assert result.can_park is None
    assert result.confidence == "low"


# ── K: No sign + geo has municipal restrictions ───────────────────────────

def test_no_sign_with_municipal_restrictions():
    """No sign provided but geo carries municipal restriction text → low confidence unknown."""
    geo = GeoContext(lat=32.08, lon=34.77, municipal_restrictions="תו אזורי 1", source="mock")
    req = ParkingRequest(lat=32.08, lon=34.77, current_datetime=datetime(2026, 5, 3, 12, 0))
    result = engine.decide(req, geo, None)
    assert result.can_park is None
    assert result.confidence == "low"
    assert any("עירוני" in w for w in result.warnings)


# ── L: Absolute no-parking sign (rule 2) ─────────────────────────────────

def test_no_parking_at_all_sign():
    """Sign with absolute no-parking flag → always False, high confidence."""
    sign = ParsedParkingSign(raw_text="", no_parking_at_all=True, confidence="high")
    req = ParkingRequest(lat=32.08, lon=34.77, current_datetime=datetime(2026, 5, 3, 12, 0))
    result = engine.decide(req, _geo(), sign)
    assert result.can_park is False
    assert result.confidence == "high"


# ── M: user_zone shorthand (legacy field) ────────────────────────────────

def test_user_zone_shorthand_matching():
    """Legacy user_zone field grants resident access when zone matches."""
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),
        user_zone="1",
    )
    result = engine.decide(req, _geo(), _sign_resident_all_times(zone="1"))
    assert result.can_park is True


def test_user_zone_shorthand_wrong_zone():
    """Legacy user_zone with non-matching zone → denied."""
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 18, 0),
        user_zone="2",
    )
    result = engine.decide(req, _geo(), _sign_resident_all_times(zone="1"))
    assert result.can_park is False


# ── N: free_until expired, no resident window (rule 9) ───────────────────

def test_free_until_expired_no_resident_window():
    """free_until passed and no resident window covers the time → ambiguous."""
    sign = ParsedParkingSign(raw_text="", free_until="17:00", confidence="medium")
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 19, 0),  # 19:00 > 17:00
    )
    result = engine.decide(req, _geo(), sign)
    assert result.can_park is None
    assert "17:00" in result.explanation_he


# ── O: Overnight no-parking window ───────────────────────────────────────

def test_overnight_no_parking_window_active():
    """No-parking 22:00–06:00 should block at 23:30 (inside overnight range)."""
    sign = ParsedParkingSign(
        raw_text="",
        no_parking_windows=[TimeRule(start_time="22:00", end_time="06:00")],
        confidence="high",
    )
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 23, 30),
    )
    result = engine.decide(req, _geo(), sign)
    assert result.can_park is False
    assert result.remaining_time is not None


def test_overnight_no_parking_window_inactive():
    """Same 22:00–06:00 window: at 10:00 the window is inactive → allowed."""
    sign = ParsedParkingSign(
        raw_text="",
        no_parking_windows=[TimeRule(start_time="22:00", end_time="06:00")],
        confidence="high",
    )
    req = ParkingRequest(
        lat=32.08, lon=34.77,
        current_datetime=datetime(2026, 5, 3, 10, 0),
    )
    result = engine.decide(req, _geo(), sign)
    assert result.can_park is True


# ── P: Complete ambiguity – sign exists but has no parseable rules (rule 11) ─

def test_complete_ambiguity_sign_has_no_rules():
    """Sign parsed but carries zero rules → can_park is None (rule 11)."""
    sign = ParsedParkingSign(raw_text="טקסט לא ברור", confidence="low")
    req = ParkingRequest(lat=32.08, lon=34.77, current_datetime=datetime(2026, 5, 3, 12, 0))
    result = engine.decide(req, _geo(), sign)
    assert result.can_park is None
