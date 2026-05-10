"""
Tel Aviv Parking Intelligence — Streamlit demo interface.

Run from the project root:
    streamlit run streamlit_app.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, date, time
from pathlib import Path

# Ensure the project root is on the path when launched with `streamlit run`
sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st

from parking.geo_context import get_geo_context
from parking.models import ParkingDecision, ParkingRequest
from parking.rule_engine import TLVParkingRuleEngine
from parking.sign_parser import parse_sign_text
from parking.sign_vision import extract_sign_text
from parking.user_profile import UserProfile, VehicleProfile

# ── Page config ───────────────────────────────────────────────────────────

st.set_page_config(
    page_title="חניה חכמה – תל אביב",
    page_icon="🚗",
    layout="centered",
)

st.markdown(
    """
    <style>
    /* Right-to-left for Hebrew content */
    .rtl { direction: rtl; text-align: right; font-size: 1.1rem; }
    .result-big { font-size: 1.6rem; font-weight: 700; padding: 12px 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Load sample signs ─────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent / "data"

@st.cache_data
def _load_samples():
    with open(_DATA_DIR / "sample_sign_texts.json", encoding="utf-8") as fh:
        return json.load(fh)["samples"]

SAMPLES = _load_samples()
SAMPLE_LABELS = ["-- בחר שלט לדוגמה --"] + [s["label"] for s in SAMPLES]
SAMPLE_MAP = {s["label"]: s["text"] for s in SAMPLES}

engine = TLVParkingRuleEngine()

# ═════════════════════════════════════════════════════════════════════════
# Header
# ═════════════════════════════════════════════════════════════════════════

st.title("🚗 חניה חכמה — תל אביב")
st.caption(
    "כלי עזר לנהגים בתל אביב. ההחלטה מבוססת על כלל קבועים בלבד — לא על בינה מלאכותית. "
    "אין להסתמך על תוצאה זו כייעוץ משפטי."
)

# ═════════════════════════════════════════════════════════════════════════
# Section 1 – Location
# ═════════════════════════════════════════════════════════════════════════

st.subheader("📍 מיקום")

col_lat, col_lon = st.columns(2)
with col_lat:
    lat = st.number_input("קו רוחב (Latitude)", value=32.0845, format="%.6f")
with col_lon:
    lon = st.number_input("קו אורך (Longitude)", value=34.7714, format="%.6f")

# Quick-fill buttons for known streets
with st.expander("מיקומים לדוגמה"):
    cols = st.columns(3)
    presets = [
        ("דיזנגוף", 32.0840, 34.7720),
        ("רוטשילד", 32.0640, 34.7760),
        ("בן יהודה", 32.0850, 34.7695),
    ]
    for i, (name, plat, plon) in enumerate(presets):
        if cols[i].button(name, key=f"preset_{i}"):
            lat = plat
            lon = plon
            st.rerun()

# ═════════════════════════════════════════════════════════════════════════
# Section 2 – Date & Time
# ═════════════════════════════════════════════════════════════════════════

st.subheader("🕐 תאריך ושעה")

col_date, col_time, col_now = st.columns([2, 2, 1])
with col_date:
    check_date = st.date_input("תאריך", value=date.today())
with col_time:
    check_time = st.time_input("שעה", value=datetime.now().time())
with col_now:
    if st.button("עכשיו", key="now_btn"):
        now = datetime.now()
        check_date = now.date()
        check_time = now.time()
        st.rerun()

current_dt = datetime.combine(check_date, check_time)

# ═════════════════════════════════════════════════════════════════════════
# Section 3 – Parking Sign
# ═════════════════════════════════════════════════════════════════════════

st.subheader("🪧 שלט חניה")

sample_choice = st.selectbox("בחר שלט לדוגמה", SAMPLE_LABELS, index=0)
if sample_choice != SAMPLE_LABELS[0]:
    default_text = SAMPLE_MAP[sample_choice]
else:
    default_text = ""

sign_text = st.text_area(
    "או הדבק טקסט שלט ידנית (עברית)",
    value=default_text,
    height=100,
    placeholder="לדוגמה: החניה מותרת לכולם עד השעה 17:00",
)

st.caption(
    "📷 העלאת תמונה — בעתיד (Gemini / GPT-4o Vision API). "
    "בינתיים ניתן להדביק את טקסט השלט ידנית."
)
uploaded_image = st.file_uploader(
    "העלה תמונת שלט (placeholder)", type=["jpg", "jpeg", "png"], disabled=True
)

# ═════════════════════════════════════════════════════════════════════════
# Section 4 – User & Vehicle Profile
# ═════════════════════════════════════════════════════════════════════════

st.subheader("👤 פרטי משתמש ורכב (אופציונלי)")
st.caption("נתונים אלו אינם נשמרים. הם משמשים אך ורק לחישוב ההחלטה בזמן אמת.")

with st.expander("הזן פרטי תו חניה ורכב", expanded=True):
    col_zone, col_vtype = st.columns(2)

    with col_zone:
        raw_zones = st.text_input(
            "אזורי חניה שברשותך (הפרד בפסיקים)",
            placeholder="לדוגמה: 1 או 1,2",
        )
        user_zones = [z.strip() for z in raw_zones.split(",") if z.strip()]

    with col_vtype:
        vehicle_type_he = st.selectbox(
            "סוג רכב",
            ["פרטי", "מסחרי", "אופנוע", "חשמלי"],
        )
        vtype_map = {"פרטי": "private", "מסחרי": "commercial", "אופנוע": "motorcycle", "חשמלי": "electric"}
        vehicle_type = vtype_map[vehicle_type_he]

    col_disabled, col_loading, col_ev = st.columns(3)
    has_disabled = col_disabled.checkbox("רישיון נכה")
    has_loading = col_loading.checkbox("אישור פריקה/טעינה")
    is_ev = col_ev.checkbox("רכב חשמלי")

    user_name = st.text_input("שם (אופציונלי)", placeholder="ישראל ישראלי")

# Build profile objects (always provided so engine can distinguish "no permit" from "unknown")
user_profile = UserProfile(
    user_id="streamlit_user",
    full_name=user_name if user_name else None,
    resident_parking_zones=user_zones,
    disabled_parking_permit=has_disabled,
    electric_vehicle=is_ev,
)
vehicle_profile = VehicleProfile(
    vehicle_id="streamlit_vehicle",
    vehicle_type=vehicle_type,
    resident_parking_permits=user_zones,
    disabled_parking_permit=has_disabled,
    commercial_loading_permit=has_loading,
)

# ═════════════════════════════════════════════════════════════════════════
# Section 5 – Check button
# ═════════════════════════════════════════════════════════════════════════

st.divider()
run = st.button("✅ בדוק אם מותר לחנות כאן", type="primary", use_container_width=True)

# ═════════════════════════════════════════════════════════════════════════
# Section 6 – Result
# ═════════════════════════════════════════════════════════════════════════

if run:
    with st.spinner("בודק..."):
        geo_ctx = get_geo_context(lat, lon)
        parsed_sign = parse_sign_text(sign_text) if sign_text.strip() else None

        request = ParkingRequest(
            lat=lat,
            lon=lon,
            current_datetime=current_dt,
            user_profile=user_profile,
            vehicle_profile=vehicle_profile,
        )
        decision: ParkingDecision = engine.decide(request, geo_ctx, parsed_sign)

    # ── Main verdict ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("📋 תוצאה")

    if decision.can_park is True:
        st.success(f"✅ מותר לחנות", icon="✅")
    elif decision.can_park is False:
        st.error(f"🚫 אסור לחנות", icon="🚫")
    else:
        st.warning(f"⚠️ לא ניתן לקבוע בוודאות", icon="⚠️")

    # Hebrew explanation (RTL)
    st.markdown(
        f'<div class="rtl">{decision.explanation_he}</div>',
        unsafe_allow_html=True,
    )

    # Remaining time
    if decision.remaining_time:
        st.info(f"⏱️ {decision.remaining_time}", icon="⏱️")

    # Confidence badge
    conf_color = {"high": "green", "medium": "orange", "low": "red"}.get(
        decision.confidence, "grey"
    )
    st.markdown(
        f"**רמת ביטחון:** :{conf_color}[{decision.confidence}]"
    )

    # Warnings
    if decision.warnings:
        st.subheader("⚠️ אזהרות")
        for w in decision.warnings:
            st.markdown(f'<div class="rtl">• {w}</div>', unsafe_allow_html=True)

    # ── Debug expandables ─────────────────────────────────────────────────
    st.divider()

    with st.expander("🔍 שלט מנותח (JSON)"):
        if parsed_sign:
            st.json(parsed_sign.model_dump())
        else:
            st.write("לא סופק טקסט שלט.")

    with st.expander("🗺️ הקשר גיאוגרפי (JSON)"):
        st.json(geo_ctx.model_dump())

    with st.expander("👤 פרופיל משתמש ורכב (JSON)"):
        st.json(
            {
                "user_profile": user_profile.model_dump(),
                "vehicle_profile": vehicle_profile.model_dump(),
            }
        )

    with st.expander("📄 בקשה מלאה (JSON)"):
        st.json(request.model_dump(mode="json"))

# ═════════════════════════════════════════════════════════════════════════
# Footer
# ═════════════════════════════════════════════════════════════════════════

st.divider()
st.caption(
    "⚠️ כלי זה מיועד לתמיכה בקבלת החלטות בלבד. "
    "אין להסתמך עליו כייעוץ משפטי או הבטחה לאי-קנס. "
    "תמיד בדוק את השלט בפועל."
)
