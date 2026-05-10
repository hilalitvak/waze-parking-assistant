"""
Parses raw Hebrew parking sign text into a structured ParsedParkingSign object.

Uses regex and keyword matching only — no LLM involved.
Extend the patterns below to handle additional sign formats.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .models import AmbiguityWarning, ParsedParkingSign, TimeRule

# Weekdays in Israeli order: Sunday (א) through Saturday (ש)
_HEBREW_DAYS: List[str] = ["א", "ב", "ג", "ד", "ה", "ו", "ש"]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _days_in_range(start: str, end: str) -> List[str]:
    try:
        si = _HEBREW_DAYS.index(start)
        ei = _HEBREW_DAYS.index(end)
        return _HEBREW_DAYS[si : ei + 1]
    except ValueError:
        return []


def _extract_time_ranges(text: str) -> List[Tuple[str, str]]:
    return re.findall(r"(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", text)


def _extract_zone(text: str) -> Optional[str]:
    """Return the first zone number found in the text (e.g. 'אזורי 1' → '1')."""
    m = re.search(r"(?:אזורי?\s+(\d+)|תו\s+(\d+))", text)
    if m:
        return m.group(1) or m.group(2)
    return None


def _extract_days(text: str) -> Optional[List[str]]:
    """Return a list of Hebrew weekday letters, or None if all days apply."""
    # "בימים א-ה" or "ימים א-ה"
    m = re.search(r"(?:ב?ימים?\s+)([א-ת])\s*[-–]\s*([א-ת])", text)
    if m:
        return _days_in_range(m.group(1), m.group(2))
    if re.search(r"(?:ב?ימי?\s+)?שישי", text):
        return ["ו"]
    if "שבת" in text:
        return ["ש"]
    return None


def _has_resident_keyword(text: str) -> bool:
    return bool(re.search(r"בעלי\s+תו|תו\s+אזורי|תו\s+חניה", text))


def _has_no_parking_keyword(text: str) -> bool:
    return bool(re.search(r"אין\s+חניה|אסור\s+לחנות|חניה\s+אסורה", text))


def _has_loading_keyword(text: str) -> bool:
    return bool(re.search(r"פריקה\s+וטעינה|פריקה/טעינה|טעינה\s+ופריקה|לטעינה|לפריקה", text))


def _has_disabled_keyword(text: str) -> bool:
    return bool(re.search(r"לנכים|נכ[ה]?\b|כיסא\s+גלגלים", text))


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_sign_text(text: str) -> ParsedParkingSign:
    """
    Convert raw Hebrew parking sign text to a structured ParsedParkingSign.

    Handles:
      • "החניה מותרת לכולם עד השעה 17:00"
      • "לאחר 17:00 לבעלי תו אזורי 1 בלבד"
      • "בימים א-ה בין השעות 17:00-09:00 החניה מותרת לבעלי תו אזורי 1 בלבד"
      • "אין חניה בין השעות 07:00-10:00"
      • "החניה מותרת לכלי רכב בעלי תו אזורי 1 בלבד"
      • "פריקה וטעינה בלבד"
      • "חניה לנכים בלבד"
    """
    text = text.strip()

    no_parking_windows: List[TimeRule] = []
    resident_only_windows: List[TimeRule] = []
    free_parking_windows: List[TimeRule] = []
    resident_only_all_times = False
    free_until: Optional[str] = None
    no_parking_at_all = False
    ambiguities: List[AmbiguityWarning] = []

    # Global extractions (apply to the whole sign)
    resident_zone = _extract_zone(text)
    day_restrictions = _extract_days(text)
    loading_zone = _has_loading_keyword(text)
    disabled_only = _has_disabled_keyword(text)

    # Early return for special zone types
    if loading_zone or disabled_only:
        return ParsedParkingSign(
            raw_text=text,
            loading_zone=loading_zone,
            disabled_only=disabled_only,
            day_restrictions=day_restrictions,
            confidence="high",
        )

    # Process line by line / segment by segment
    segments = re.split(r"[\n,;]", text)

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        # ── No-parking clause ─────────────────────────────────────────────
        if _has_no_parking_keyword(seg):
            ranges = _extract_time_ranges(seg)
            if ranges:
                for start, end in ranges:
                    no_parking_windows.append(
                        TimeRule(start_time=start, end_time=end, days=day_restrictions)
                    )
            else:
                no_parking_at_all = True
            continue

        # ── "Free for everyone until HH:MM" ─────────────────────────────
        free_m = re.search(r"לכולם.*?עד\s+(?:השעה\s+)?(\d{1,2}:\d{2})", seg)
        if free_m:
            free_until = free_m.group(1)
            continue

        # ── "After HH:MM, residents only" ───────────────────────────────
        after_m = re.search(
            r"לאחר\s+(?:מכן\s+)?(?:השעה\s+)?(\d{1,2}:\d{2})", seg
        )
        if after_m and _has_resident_keyword(seg):
            resident_only_windows.append(
                TimeRule(
                    start_time=after_m.group(1),
                    end_time="23:59",
                    days=day_restrictions,
                )
            )
            continue

        # ── Resident keyword with explicit time range ────────────────────
        if _has_resident_keyword(seg):
            ranges = _extract_time_ranges(seg)
            if ranges:
                for start, end in ranges:
                    resident_only_windows.append(
                        TimeRule(start_time=start, end_time=end, days=day_restrictions)
                    )
            else:
                # Resident-only without a time range → applies all day
                resident_only_all_times = True
            continue

    # ── Infer resident window from "free until" + resident keyword ───────
    # When the sign says "free until X" and also mentions a resident permit
    # but gives no explicit time range for the resident restriction,
    # we infer the restriction starts at free_until and apply a standard
    # Tel Aviv overnight end (09:00). An ambiguity warning is added.
    if free_until and _has_resident_keyword(text) and not resident_only_windows:
        resident_only_windows.append(
            TimeRule(start_time=free_until, end_time="09:00", days=day_restrictions)
        )
        ambiguities.append(
            AmbiguityWarning(
                field="resident_end_time",
                message_he=(
                    f"שעת הסיום של החניה האזורית לא צוינה בשלט. "
                    f"הנחנו שמסתיימת בשעה 09:00 (הסטנדרט בתל אביב)."
                ),
            )
        )

    # ── Flag missing zone number when resident rule was detected ─────────
    has_resident_rule = resident_only_all_times or bool(resident_only_windows)
    if has_resident_rule and not resident_zone:
        ambiguities.append(
            AmbiguityWarning(
                field="resident_zone",
                message_he="השלט מציין תו אזורי אך לא צוין מספר האזור.",
            )
        )

    # ── Confidence ───────────────────────────────────────────────────────
    has_rules = bool(
        no_parking_windows
        or resident_only_windows
        or resident_only_all_times
        or free_until
        or no_parking_at_all
    )
    if not has_rules:
        ambiguities.append(
            AmbiguityWarning(
                field="general",
                message_he="לא זוהה כלל חניה ברור מהטקסט שסופק.",
            )
        )

    if not has_rules:
        confidence = "low"
    elif ambiguities:
        confidence = "medium"
    else:
        confidence = "high"

    return ParsedParkingSign(
        raw_text=text,
        no_parking_windows=no_parking_windows,
        resident_only_windows=resident_only_windows,
        free_parking_windows=free_parking_windows,
        resident_only_all_times=resident_only_all_times,
        resident_zone=resident_zone,
        free_until=free_until,
        day_restrictions=day_restrictions,
        no_parking_at_all=no_parking_at_all,
        loading_zone=loading_zone,
        disabled_only=disabled_only,
        ambiguities=ambiguities,
        confidence=confidence,
    )
