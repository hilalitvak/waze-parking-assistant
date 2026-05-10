"""Tests for the Hebrew sign parser."""

import pytest
from parking.sign_parser import parse_sign_text


# ── Helper ────────────────────────────────────────────────────────────────

def _ambiguity_fields(sign):
    return [a.field for a in sign.ambiguities]


# ── Free until + resident after ───────────────────────────────────────────

def test_free_until_parsed():
    sign = parse_sign_text(
        "החניה מותרת לכולם עד השעה 17:00\n"
        "לאחר 17:00 לבעלי תו אזורי 1 בלבד"
    )
    assert sign.free_until == "17:00"
    assert sign.resident_zone == "1"
    assert len(sign.resident_only_windows) == 1
    assert sign.resident_only_windows[0].start_time == "17:00"
    assert sign.confidence == "high"


def test_free_until_resident_window_end_time():
    sign = parse_sign_text(
        "החניה מותרת לכולם עד השעה 17:00\n"
        "לאחר 17:00 לבעלי תו אזורי 1 בלבד"
    )
    # Explicit "after" clause sets end to 23:59
    assert sign.resident_only_windows[0].end_time == "23:59"


# ── Resident-only all times ───────────────────────────────────────────────

def test_resident_only_all_times():
    sign = parse_sign_text("החניה מותרת לכלי רכב בעלי תו אזורי 1 בלבד")
    assert sign.resident_only_all_times is True
    assert sign.resident_zone == "1"
    assert sign.ambiguities == []
    assert sign.confidence == "high"


# ── No-parking time window ────────────────────────────────────────────────

def test_no_parking_window():
    sign = parse_sign_text("אין חניה בין השעות 07:00-10:00")
    assert len(sign.no_parking_windows) == 1
    w = sign.no_parking_windows[0]
    assert w.start_time == "07:00"
    assert w.end_time == "10:00"
    assert sign.resident_only_all_times is False
    assert sign.confidence == "high"


# ── Weekday-restricted overnight resident window ──────────────────────────

def test_weekday_overnight_resident():
    sign = parse_sign_text(
        "בימים א-ה בין השעות 17:00-09:00 החניה מותרת לבעלי תו אזורי 1 בלבד"
    )
    assert sign.resident_zone == "1"
    assert len(sign.resident_only_windows) == 1
    w = sign.resident_only_windows[0]
    assert w.start_time == "17:00"
    assert w.end_time == "09:00"
    assert w.days is not None
    assert "א" in w.days
    assert "ה" in w.days
    assert "ו" not in w.days  # Friday not in range


# ── Ambiguous sign – no zone number ──────────────────────────────────────

def test_ambiguous_missing_zone():
    sign = parse_sign_text("החניה מותרת לבעלי תו אזורי בלבד")
    assert sign.resident_only_all_times is True
    assert sign.resident_zone is None
    assert "resident_zone" in _ambiguity_fields(sign)
    assert sign.confidence == "medium"


# ── Loading zone ──────────────────────────────────────────────────────────

def test_loading_zone():
    sign = parse_sign_text("פריקה וטעינה בלבד")
    assert sign.loading_zone is True
    assert sign.disabled_only is False


# ── Disabled bay ─────────────────────────────────────────────────────────

def test_disabled_only():
    sign = parse_sign_text("חניה לנכים בלבד")
    assert sign.disabled_only is True
    assert sign.loading_zone is False


# ── Inferred overnight resident window from "free until" ─────────────────

def test_inferred_resident_window_overnight():
    sign = parse_sign_text(
        "החניה מותרת לכולם עד 17:00\nלאחר מכן לבעלי תו אזורי 2 בלבד"
    )
    assert sign.free_until == "17:00"
    assert sign.resident_zone == "2"
    assert len(sign.resident_only_windows) >= 1


# ── Absolute no-parking keywords ──────────────────────────────────────────

def test_no_parking_keyword_assur_lichno():
    sign = parse_sign_text("אסור לחנות")
    assert sign.no_parking_at_all is True
    assert sign.confidence == "high"


def test_no_parking_keyword_chaniya_asura():
    sign = parse_sign_text("חניה אסורה")
    assert sign.no_parking_at_all is True
    assert sign.confidence == "high"


def test_no_parking_with_time_range_does_not_set_at_all():
    """'אין חניה' with a time range → window, not absolute prohibition."""
    sign = parse_sign_text("אין חניה בין השעות 08:00-12:00")
    assert sign.no_parking_at_all is False
    assert len(sign.no_parking_windows) == 1


# ── Day-specific restrictions ─────────────────────────────────────────────

def test_friday_only_restriction():
    sign = parse_sign_text("בימי שישי אין חניה בין השעות 08:00-14:00")
    assert len(sign.no_parking_windows) == 1
    assert sign.no_parking_windows[0].days == ["ו"]


def test_saturday_restriction():
    sign = parse_sign_text("בשבת חניה לבעלי תו אזורי 1 בלבד")
    assert sign.resident_only_all_times is True
    assert sign.resident_zone == "1"
    assert sign.day_restrictions == ["ש"]


# ── Zone number via "תו N" format ─────────────────────────────────────────

def test_zone_tav_number_format():
    sign = parse_sign_text("החניה מותרת לבעלי תו 3 בלבד")
    assert sign.resident_zone == "3"
    assert sign.resident_only_all_times is True


# ── Unrecognized text → low confidence with general ambiguity ────────────

def test_unrecognized_text_low_confidence():
    sign = parse_sign_text("טקסט שאינו מכיל כלל חניה")
    assert sign.confidence == "low"
    assert any(a.field == "general" for a in sign.ambiguities)
