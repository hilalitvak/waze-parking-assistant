"""
Deterministic parking rule engine for Tel Aviv.

The LLM / vision model is NEVER called here.
Every decision is traceable to a specific rule and returns a Hebrew explanation.

Decision priority order:
  1. No sign data at all
  2. Absolute no-parking sign
  3. Loading zone
  4. Disabled-only bay
  5. Active no-parking time window
  6. Free-for-everyone period (before free_until)
  7. Resident-only all-day rule
  8. Active resident-only time window
  9. After free_until with no matching resident window → ambiguous
 10. No active restriction → allowed
 11. Complete ambiguity → unknown
"""

from __future__ import annotations

from datetime import datetime, time
from typing import List, Optional, Tuple

from .models import GeoContext, ParkingDecision, ParkingRequest, ParsedParkingSign
from .user_profile import UserProfile, VehicleProfile

# Maps Python weekday() to Hebrew letter (0=Monday…6=Sunday)
_PYTHON_TO_HEB_DAY = {6: "א", 0: "ב", 1: "ג", 2: "ד", 3: "ה", 4: "ו", 5: "ש"}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _parse_time(hhmm: str) -> time:
    h, m = map(int, hhmm.split(":"))
    return time(h, m)


def _time_in_window(current: time, start_str: str, end_str: str) -> bool:
    """Return True if current is inside [start, end], handling overnight ranges."""
    s = _parse_time(start_str)
    e = _parse_time(end_str)
    if s <= e:
        return s <= current <= e
    # Overnight range, e.g. 17:00–09:00
    return current >= s or current <= e


def _day_applies(dt: datetime, days: Optional[List[str]]) -> bool:
    """Return True if the given datetime falls on a day in the days list."""
    if days is None:
        return True
    return _PYTHON_TO_HEB_DAY[dt.weekday()] in days


def _minutes_until(current: time, target_str: str) -> int:
    """Minutes from current until target time (always positive; wraps midnight)."""
    t = _parse_time(target_str)
    diff = (t.hour * 60 + t.minute) - (current.hour * 60 + current.minute)
    if diff <= 0:
        diff += 24 * 60
    return diff


def _fmt(minutes: int) -> str:
    """Format a minute count as a natural Hebrew duration string."""
    if minutes < 60:
        return f"{minutes} דקות"
    h, m = divmod(minutes, 60)
    if m == 0:
        return f"{h} שעות" if h > 1 else "שעה"
    return f"{h} שעות ו-{m} דקות"


# ---------------------------------------------------------------------------
# Permit helpers
# ---------------------------------------------------------------------------

def _has_disabled_permit(request: ParkingRequest) -> bool:
    return bool(
        (request.user_profile and request.user_profile.disabled_parking_permit)
        or (request.vehicle_profile and request.vehicle_profile.disabled_parking_permit)
    )


def _has_any_permit_info(request: ParkingRequest) -> bool:
    """Return True if the caller supplied any permit information at all."""
    return bool(
        request.user_zone is not None
        or request.user_profile is not None
        or request.vehicle_profile is not None
    )


def _check_resident_permit(zone: str, request: ParkingRequest) -> Tuple[bool, str]:
    """
    Return (has_permit, reason_he).

    Checks in order: vehicle permits → user profile zones → legacy user_zone.
    """
    if request.vehicle_profile:
        if zone in request.vehicle_profile.resident_parking_permits:
            return True, f"לרכב יש תו אזורי {zone}"

    if request.user_profile:
        if zone in request.user_profile.resident_parking_zones:
            return True, f"למשתמש יש תו אזורי {zone}"

    if request.user_zone == zone:
        return True, f"תו אזורי {zone} תואם לדרישה"

    return False, ""


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

class TLVParkingRuleEngine:
    """
    Evaluates whether a driver may park at a location and time.

    All decisions are deterministic and explainable.
    The engine never guesses when data is missing — it returns can_park=None
    and describes exactly what information is needed.
    """

    def decide(
        self,
        request: ParkingRequest,
        geo_context: GeoContext,
        parsed_sign: Optional[ParsedParkingSign],
    ) -> ParkingDecision:

        current_time = request.current_datetime.time()
        warnings: List[str] = []

        # Collect parser ambiguity messages as warnings
        if parsed_sign:
            for a in parsed_sign.ambiguities:
                warnings.append(a.message_he)

        # ── 1. No sign data ───────────────────────────────────────────────
        if parsed_sign is None:
            if geo_context.municipal_restrictions:
                warnings.append("הנתונים מבוססים על מידע עירוני כללי, לא על שלט ספציפי.")
                return ParkingDecision(
                    can_park=None,
                    confidence="low",
                    explanation_he=(
                        "ישנו מידע עירוני לאזור זה אך לא נמסר שלט. "
                        "אנא הוסף תמונת שלט לתשובה מדויקת יותר."
                    ),
                    geo_context=geo_context,
                    warnings=warnings,
                )
            return ParkingDecision(
                can_park=None,
                confidence="low",
                explanation_he=(
                    "אין מידע על חוקי החניה בנקודה זו. "
                    "יש להוסיף תמונת שלט או טקסט לבדיקה."
                ),
                geo_context=geo_context,
                warnings=warnings,
            )

        # ── 2. Absolute no-parking ────────────────────────────────────────
        if parsed_sign.no_parking_at_all:
            return ParkingDecision(
                can_park=False,
                confidence="high",
                explanation_he="אסור לחנות כאן בכל שעה.",
                geo_context=geo_context,
                parsed_sign=parsed_sign,
                warnings=warnings,
            )

        # ── 3. Loading zone ───────────────────────────────────────────────
        if parsed_sign.loading_zone:
            has_loading = bool(
                request.vehicle_profile
                and request.vehicle_profile.commercial_loading_permit
            )
            if has_loading:
                return ParkingDecision(
                    can_park=True,
                    confidence="high",
                    explanation_he=(
                        "מותר לעצור לפריקה/טעינה. לרכב יש אישור פריקה וטעינה."
                    ),
                    geo_context=geo_context,
                    parsed_sign=parsed_sign,
                    warnings=warnings,
                )
            return ParkingDecision(
                can_park=False,
                confidence="high",
                explanation_he="מקום זה מיועד לפריקה/טעינה בלבד. לא ניתן לחנות כאן.",
                geo_context=geo_context,
                parsed_sign=parsed_sign,
                warnings=warnings,
            )

        # ── 4. Disabled-only bay ──────────────────────────────────────────
        if parsed_sign.disabled_only:
            if _has_disabled_permit(request):
                return ParkingDecision(
                    can_park=True,
                    confidence="high",
                    explanation_he="מותר לחנות כאן. מקום מיועד לנכים ויש לך רישיון נכה.",
                    geo_context=geo_context,
                    parsed_sign=parsed_sign,
                    warnings=warnings,
                )
            return ParkingDecision(
                can_park=False,
                confidence="high",
                explanation_he="מקום זה מיועד לנכים בלבד.",
                geo_context=geo_context,
                parsed_sign=parsed_sign,
                warnings=warnings,
            )

        # ── 5. Active no-parking time window ─────────────────────────────
        for window in parsed_sign.no_parking_windows:
            if _day_applies(request.current_datetime, window.days):
                if _time_in_window(current_time, window.start_time, window.end_time):
                    remaining = _fmt(
                        _minutes_until(current_time, window.end_time)
                    )
                    return ParkingDecision(
                        can_park=False,
                        confidence="high",
                        remaining_time=remaining,
                        explanation_he=(
                            f"אסור לחנות כאן בין השעות "
                            f"{window.start_time}–{window.end_time}. "
                            f"ניתן לחנות שוב בעוד {remaining}."
                        ),
                        geo_context=geo_context,
                        parsed_sign=parsed_sign,
                        warnings=warnings,
                    )

        # ── 6. Free-for-everyone period ───────────────────────────────────
        if parsed_sign.free_until:
            free_until_time = _parse_time(parsed_sign.free_until)
            if current_time < free_until_time:
                remaining = _fmt(
                    _minutes_until(current_time, parsed_sign.free_until)
                )
                return ParkingDecision(
                    can_park=True,
                    confidence="high",
                    remaining_time=remaining,
                    explanation_he=(
                        f"מותר לחנות כאן. החניה פתוחה לכולם עד {parsed_sign.free_until}. "
                        f"נותרו {remaining}."
                    ),
                    geo_context=geo_context,
                    parsed_sign=parsed_sign,
                    warnings=warnings,
                )

        # ── 7. Resident-only all times ────────────────────────────────────
        if parsed_sign.resident_only_all_times:
            return self._check_resident(
                zone=parsed_sign.resident_zone,
                time_suffix="בכל שעות היממה",
                time_remaining=None,
                request=request,
                geo_context=geo_context,
                parsed_sign=parsed_sign,
                warnings=warnings,
            )

        # ── 8. Active resident-only time window ───────────────────────────
        for window in parsed_sign.resident_only_windows:
            if _day_applies(request.current_datetime, window.days):
                if _time_in_window(current_time, window.start_time, window.end_time):
                    remaining = _fmt(
                        _minutes_until(current_time, window.end_time)
                    )
                    return self._check_resident(
                        zone=parsed_sign.resident_zone,
                        time_suffix=(
                            f"בין השעות {window.start_time}–{window.end_time}"
                        ),
                        time_remaining=remaining,
                        request=request,
                        geo_context=geo_context,
                        parsed_sign=parsed_sign,
                        warnings=warnings,
                    )

        # ── 9. After free_until with no matching resident window ──────────
        if parsed_sign.free_until:
            free_until_time = _parse_time(parsed_sign.free_until)
            if current_time >= free_until_time:
                return ParkingDecision(
                    can_park=None,
                    confidence="low",
                    explanation_he=(
                        f"החניה החופשית הסתיימה בשעה {parsed_sign.free_until}. "
                        f"לא ברור מה הכלל כעת — אנא בדוק את השלט בעצמך."
                    ),
                    geo_context=geo_context,
                    parsed_sign=parsed_sign,
                    warnings=warnings
                    + [f"חסר מידע על חוקי החניה לאחר {parsed_sign.free_until}"],
                )

        # ── 10. No active restriction → allowed ───────────────────────────
        has_any_rules = bool(
            parsed_sign.no_parking_windows
            or parsed_sign.resident_only_windows
            or parsed_sign.resident_only_all_times
        )
        if has_any_rules:
            return ParkingDecision(
                can_park=True,
                confidence="medium",
                explanation_he=(
                    "מותר לחנות כאן כרגע. אין הגבלות פעילות בשעה זו."
                ),
                geo_context=geo_context,
                parsed_sign=parsed_sign,
                warnings=warnings,
            )

        # ── 11. Complete ambiguity ─────────────────────────────────────────
        return ParkingDecision(
            can_park=None,
            confidence="low",
            explanation_he="לא ניתן לקבוע בוודאות. אנא בדוק את השלט בעצמך.",
            geo_context=geo_context,
            parsed_sign=parsed_sign,
            warnings=warnings + ["מידע לא מספיק לקביעת כלל חניה"],
        )

    # -----------------------------------------------------------------------
    # Internal helper
    # -----------------------------------------------------------------------

    def _check_resident(
        self,
        zone: Optional[str],
        time_suffix: str,
        time_remaining: Optional[str],
        request: ParkingRequest,
        geo_context: GeoContext,
        parsed_sign: ParsedParkingSign,
        warnings: List[str],
    ) -> ParkingDecision:
        """Evaluate whether the requester holds the required resident permit."""

        # Disabled permit overrides resident zone requirements
        if _has_disabled_permit(request):
            return ParkingDecision(
                can_park=True,
                confidence="high",
                remaining_time=time_remaining,
                explanation_he=(
                    f"מותר לחנות כאן {time_suffix}. "
                    f"מחזיק רישיון נכה — פטור מהגבלות תו אזורי."
                ),
                geo_context=geo_context,
                parsed_sign=parsed_sign,
                warnings=warnings,
            )

        # Resolve required zone: sign zone → geo_context zone
        required_zone = zone or (geo_context.parking_zone if geo_context else None)

        if not required_zone:
            return ParkingDecision(
                can_park=None,
                confidence="low",
                explanation_he=(
                    f"החניה {time_suffix} מיועדת לבעלי תו אזורי, "
                    f"אך לא ניתן לזהות את האזור הנדרש."
                ),
                geo_context=geo_context,
                parsed_sign=parsed_sign,
                warnings=warnings + ["מספר האזור לא זוהה בשלט ולא נמצא מידע גיאוגרפי"],
            )

        # If caller provided no permit data at all, we cannot decide
        if not _has_any_permit_info(request):
            return ParkingDecision(
                can_park=None,
                confidence="medium",
                remaining_time=time_remaining,
                explanation_he=(
                    f"החניה {time_suffix} מיועדת לבעלי תו אזורי {required_zone}. "
                    f"יש להזין את פרטי התו שלך כדי לקבל תשובה."
                ),
                geo_context=geo_context,
                parsed_sign=parsed_sign,
                warnings=warnings + [f"נדרש תו אזורי {required_zone} – לא סופק מידע"],
            )

        has_permit, reason = _check_resident_permit(required_zone, request)

        if has_permit:
            return ParkingDecision(
                can_park=True,
                confidence="high",
                remaining_time=time_remaining,
                explanation_he=f"מותר לחנות כאן {time_suffix}. {reason}.",
                geo_context=geo_context,
                parsed_sign=parsed_sign,
                warnings=warnings,
            )

        return ParkingDecision(
            can_park=False,
            confidence="high",
            remaining_time=time_remaining,
            explanation_he=(
                f"אסור לחנות כאן {time_suffix}. "
                f"נדרש תו אזורי {required_zone} בלבד."
            ),
            geo_context=geo_context,
            parsed_sign=parsed_sign,
            warnings=warnings,
        )
