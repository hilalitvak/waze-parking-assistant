"""
Claude AI agent for enhanced parking decisions.

Wraps the deterministic rule engine output and enriches it with side-of-street,
payment, and duration information using the Claude API (claude-opus-4-7).

Falls back to the deterministic decision gracefully when:
  - ANTHROPIC_API_KEY is not set
  - The API call fails for any reason
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from .models import GeoContext, ParkingDecision, ParkingRequest, ParsedParkingSign

_SYSTEM_PROMPT = """אתה עוזר חניה חכם לתל אביב. קיבלת את תוצאת מנוע הכללים הדטרמיניסטי ואת נתוני הרחוב.
תפקידך להעשיר את ההחלטה עם מידע על:
1. באיזה צד של הרחוב מותר לחנות (ימין / שמאל / שני הצדדים)
2. האם נדרשת תשלום (גרייה)
3. מחיר לשעה ומשך מקסימלי
4. הסבר מלא בעברית לנהג

החזר תמיד JSON תקין בפורמט הכלי parking_decision.
"""


def _build_user_message(
    request: ParkingRequest,
    geo_ctx: GeoContext,
    deterministic: ParkingDecision,
    parsed_sign: Optional[ParsedParkingSign],
    street_rule: Optional[Dict[str, Any]],
) -> str:
    dt = request.current_datetime
    day_names = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]
    day_he = day_names[dt.weekday() % 7]  # Python weekday: Mon=0; adjust for Sun=0
    # Python weekday: Mon=0..Sun=6; Israeli: Sun=0..Sat=6
    iday = (dt.weekday() + 1) % 7
    day_he = day_names[iday]

    parts = [
        f"📅 יום {day_he}, {dt.strftime('%d/%m/%Y %H:%M')}",
        f"📍 רחוב: {geo_ctx.street_name or 'לא זוהה'} | אזור: {geo_ctx.parking_zone or 'לא ידוע'}",
    ]

    if street_rule:
        parts.append(f"🗺️ כלל עירייה: {street_rule.get('rules', '')}")
        side = street_rule.get("parking_side")
        if side:
            side_map = {"right": "ימין", "left": "שמאל", "both": "שני הצדדים"}
            parts.append(f"🚗 צד חניה: {side_map.get(side, side)}")
        if street_rule.get("payment_required_daytime"):
            rate = street_rule.get("payment_rate_ils_per_hour", 0)
            max_min = street_rule.get("max_free_minutes")
            parts.append(f"💳 תשלום: ₪{rate}/שעה" + (f" | מקסימום {max_min} דקות" if max_min else ""))
        else:
            parts.append("💳 תשלום: לא נדרש")

    if request.user_profile:
        up = request.user_profile
        zones = ", ".join(up.resident_parking_zones) if up.resident_parking_zones else "אין"
        parts.append(f"👤 תו אזורי: {zones} | נכה: {'כן' if up.disabled_parking_permit else 'לא'}")

    parts.append(f"\n⚙️ החלטה דטרמיניסטית: {'מותר' if deterministic.can_park else 'אסור' if deterministic.can_park is False else 'לא ידוע'}")
    parts.append(f"   הסבר: {deterministic.explanation_he}")

    if parsed_sign:
        parts.append(f"\n🪧 שלט מנותח: {parsed_sign.raw_text}")

    parts.append("\nבהתבסס על כל המידע לעיל, החזר החלטת חניה מלאה בפורמט הכלי.")
    return "\n".join(parts)


_TOOL_SCHEMA = {
    "name": "parking_decision",
    "description": "מחזיר החלטת חניה מלאה עם כל השדות הנדרשים",
    "input_schema": {
        "type": "object",
        "properties": {
            "can_park": {
                "type": ["boolean", "null"],
                "description": "האם מותר לחנות (true/false/null אם לא ניתן לקבוע)"
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "רמת ביטחון בהחלטה"
            },
            "explanation_he": {
                "type": "string",
                "description": "הסבר מלא בעברית לנהג, כולל צד החניה ומידע על תשלום"
            },
            "remaining_time": {
                "type": ["string", "null"],
                "description": "כמה זמן נותר לחניה חוקית (בעברית), אם רלוונטי"
            },
            "side": {
                "type": ["string", "null"],
                "enum": ["right", "left", "both", None],
                "description": "באיזה צד של הרחוב מותר לחנות"
            },
            "payment_required": {
                "type": ["boolean", "null"],
                "description": "האם נדרש תשלום לחניה"
            },
            "max_duration_minutes": {
                "type": ["integer", "null"],
                "description": "משך חניה מקסימלי בדקות, אם מוגבל"
            },
            "payment_details": {
                "type": ["string", "null"],
                "description": "פרטי תשלום בעברית, לדוגמה: ₪8/שעה"
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "אזהרות נוספות בעברית"
            }
        },
        "required": ["can_park", "confidence", "explanation_he"]
    }
}


def enhance_with_ai(
    request: ParkingRequest,
    geo_ctx: GeoContext,
    deterministic: ParkingDecision,
    parsed_sign: Optional[ParsedParkingSign] = None,
    street_rule: Optional[Dict[str, Any]] = None,
) -> ParkingDecision:
    """
    Call Claude to enrich the deterministic decision.
    Returns the deterministic decision unchanged on any error.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return deterministic

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        user_msg = _build_user_message(request, geo_ctx, deterministic, parsed_sign, street_rule)

        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "parking_decision"},
            messages=[{"role": "user", "content": user_msg}],
        )

        tool_use_block = next(
            (b for b in response.content if b.type == "tool_use"),
            None,
        )
        if not tool_use_block:
            return deterministic

        data: Dict = tool_use_block.input

        return ParkingDecision(
            can_park=data.get("can_park", deterministic.can_park),
            confidence=data.get("confidence", deterministic.confidence),
            explanation_he=data.get("explanation_he", deterministic.explanation_he),
            remaining_time=data.get("remaining_time", deterministic.remaining_time),
            geo_context=deterministic.geo_context,
            parsed_sign=deterministic.parsed_sign,
            warnings=data.get("warnings", deterministic.warnings),
            side=data.get("side"),
            payment_required=data.get("payment_required"),
            max_duration_minutes=data.get("max_duration_minutes"),
            payment_details=data.get("payment_details"),
            ai_enhanced=True,
        )

    except Exception:
        return deterministic
