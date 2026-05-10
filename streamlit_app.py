"""
Tel Aviv Parking Intelligence — Streamlit interface (v2).

Features:
  • Interactive Folium map — click to pick location
  • GPS button — uses browser geolocation
  • Address search — free Nominatim geocoding
  • Auto-detected parking rules — no sign photo needed for known streets
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, date, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import folium
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from parking.geo_context import get_geo_context
from parking.models import GeoContext, ParkingDecision, ParkingRequest
from parking.nominatim import geocode as nom_geocode, reverse_geocode
from parking.rule_engine import TLVParkingRuleEngine
from parking.sign_parser import parse_sign_text
from parking.user_profile import UserProfile, VehicleProfile

# ── Page config ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="חניה חכמה – תל אביב",
    page_icon="🚗",
    layout="centered",
)

st.markdown("""
<style>
.rtl { direction: rtl; text-align: right; font-size: 1.1rem; }
</style>
""", unsafe_allow_html=True)

# ── Cached loaders ─────────────────────────────────────────────────────────

_DATA_DIR = Path(__file__).parent / "data"

@st.cache_data
def _load_samples():
    with open(_DATA_DIR / "sample_sign_texts.json", encoding="utf-8") as fh:
        return json.load(fh)["samples"]

@st.cache_data
def _load_zones():
    with open(_DATA_DIR / "mock_parking_zones.json", encoding="utf-8") as fh:
        return json.load(fh)

@st.cache_data(ttl=60)
def _cached_reverse_geocode(lat: float, lon: float):
    return reverse_geocode(lat, lon)

SAMPLES       = _load_samples()
ZONES         = _load_zones()
SAMPLE_LABELS = ["-- בחר שלט לדוגמה --"] + [s["label"] for s in SAMPLES]
SAMPLE_MAP    = {s["label"]: s["text"] for s in SAMPLES}

engine = TLVParkingRuleEngine()

ZONE_COLORS = {"1": "blue", "2": "green", "3": "orange", "4": "purple", "5": "red"}
ZONE_FLAGS  = {"1": "🔵", "2": "🟢", "3": "🟠", "4": "🟣", "5": "🔴"}

# ── Session-state defaults ─────────────────────────────────────────────────

if "lat" not in st.session_state:
    st.session_state.lat = 32.0845      # Dizengoff area
    st.session_state.lon = 34.7714
if "last_map_click" not in st.session_state:
    st.session_state.last_map_click = None
if "time_key" not in st.session_state:
    st.session_state.time_key = 0

# ── Read GPS coordinates injected via URL query params ─────────────────────
# The GPS button (HTML component) redirects with ?lat=…&lon=… after the
# browser resolves the device location.

params = st.query_params
if "lat" in params and "lon" in params:
    try:
        st.session_state.lat = float(params["lat"])
        st.session_state.lon = float(params["lon"])
        st.query_params.clear()
    except (ValueError, TypeError):
        pass

# ── Header ─────────────────────────────────────────────────────────────────

st.title("🚗 חניה חכמה — תל אביב")
st.caption(
    "כלי עזר לנהגים בתל אביב. ההחלטה מבוססת על כללים קבועים בלבד — לא על בינה מלאכותית. "
    "אין להסתמך על תוצאה זו כייעוץ משפטי."
)

# ═══════════════════════════════════════════════════════════════════════════
# Section 1 – Location picker
# ═══════════════════════════════════════════════════════════════════════════

st.subheader("📍 מיקום")

# GPS button — JS inside the iframe triggers browser geolocation then
# redirects the parent Streamlit window with ?lat=…&lon=… query params.
components.html("""
<style>
  .gps-btn {
    background: #27ae60; color: white; border: none;
    padding: 9px 20px; border-radius: 8px; cursor: pointer;
    font-size: 14px; font-family: sans-serif; font-weight: 600;
  }
  .gps-btn:hover { background: #219a52; }
  .gps-btn:disabled { background: #95a5a6; cursor: default; }
</style>
<button class="gps-btn" id="btn" onclick="
  var btn = document.getElementById('btn');
  btn.disabled = true; btn.textContent = '⏳ מאתר מיקום...';
  navigator.geolocation.getCurrentPosition(
    function(pos) {
      var url = new URL(window.parent.location.href);
      url.searchParams.set('lat', pos.coords.latitude.toFixed(6));
      url.searchParams.set('lon', pos.coords.longitude.toFixed(6));
      window.parent.location.href = url.toString();
    },
    function(err) {
      alert('לא ניתן לאתר מיקום: ' + err.message);
      btn.disabled = false; btn.textContent = '📍 השתמש במיקומי הנוכחי';
    },
    {enableHighAccuracy: true, timeout: 10000}
  );
">📍 השתמש במיקומי הנוכחי</button>
""", height=55)

# Address search
addr_col, go_col = st.columns([5, 1])
with addr_col:
    address_input = st.text_input(
        "חיפוש",
        placeholder="חפש כתובת — לדוגמה: דיזנגוף 50 תל אביב",
        label_visibility="collapsed",
    )
with go_col:
    search_clicked = st.button("🔍 חפש", use_container_width=True)

if search_clicked and address_input.strip():
    with st.spinner("מחפש..."):
        coords = nom_geocode(address_input.strip())
    if coords:
        st.session_state.lat, st.session_state.lon = coords
        st.session_state.last_map_click = None
        st.rerun()
    else:
        st.error("לא נמצאה כתובת — נסה לנסח אחרת")

# ── Folium map ─────────────────────────────────────────────────────────────

lat = st.session_state.lat
lon = st.session_state.lon

m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB positron")

for zone in ZONES:
    color = ZONE_COLORS.get(zone["zone_id"], "gray")
    flag  = ZONE_FLAGS.get(zone["zone_id"], "⚪")
    folium.Circle(
        location=[zone["center_lat"], zone["center_lon"]],
        radius=zone["radius_meters"],
        color=color,
        fill=True,
        fill_opacity=0.13,
        weight=2,
        tooltip=f"{flag} {zone['name']}",
        popup=folium.Popup(
            f"<b>{flag} {zone['name']}</b><br><small>{zone['description']}</small>",
            max_width=220,
        ),
    ).add_to(m)

folium.Marker(
    location=[lat, lon],
    icon=folium.Icon(color="red", icon="car", prefix="fa"),
    tooltip="מיקום נבחר — לחץ על המפה לשינוי",
).add_to(m)

map_data = st_folium(
    m,
    height=370,
    width="100%",
    returned_objects=["last_clicked"],
    key="main_map",
)

if map_data and map_data.get("last_clicked"):
    clicked = (
        round(map_data["last_clicked"]["lat"], 6),
        round(map_data["last_clicked"]["lng"], 6),
    )
    if clicked != st.session_state.last_map_click:
        st.session_state.last_map_click = clicked
        st.session_state.lat = clicked[0]
        st.session_state.lon = clicked[1]
        st.rerun()

st.caption(
    f"📌 {lat:.5f}, {lon:.5f}  |  "
    + "  ".join(f"{ZONE_FLAGS[z]} אזור {z}" for z in ZONE_FLAGS)
)

# ── Auto-detect street & rules ─────────────────────────────────────────────

geo_ctx = get_geo_context(lat, lon)

if not geo_ctx.street_name:
    nom_data = _cached_reverse_geocode(round(lat, 4), round(lon, 4))
    if nom_data:
        addr      = nom_data.get("address", {})
        street_he = (
            addr.get("road")
            or addr.get("pedestrian")
            or addr.get("neighbourhood")
            or addr.get("suburb")
        )
        if street_he:
            geo_ctx = GeoContext(
                lat=lat, lon=lon,
                street_name=street_he,
                parking_zone=geo_ctx.parking_zone,
                municipal_restrictions=geo_ctx.municipal_restrictions,
                source="nominatim",
            )

if geo_ctx.street_name:
    zone_badge = f"אזור {geo_ctx.parking_zone}" if geo_ctx.parking_zone else "אזור לא מזוהה"
    st.info(f"📍 **{geo_ctx.street_name}** — {zone_badge}")
else:
    st.warning("הרחוב לא זוהה. נסה לחפש כתובת או לחץ על מיקום ידוע במפה.")

# ═══════════════════════════════════════════════════════════════════════════
# Section 2 – Date & Time
# ═══════════════════════════════════════════════════════════════════════════

st.subheader("🕐 תאריך ושעה")

now = datetime.now()
col_date, col_time, col_now = st.columns([2, 2, 1])

with col_date:
    check_date = st.date_input(
        "תאריך", value=now.date(),
        key=f"date_{st.session_state.time_key}",
    )
with col_time:
    check_time = st.time_input(
        "שעה", value=now.time(),
        key=f"time_{st.session_state.time_key}",
    )
with col_now:
    st.write("")
    if st.button("עכשיו"):
        st.session_state.time_key += 1
        st.rerun()

current_dt = datetime.combine(check_date, check_time)

# ═══════════════════════════════════════════════════════════════════════════
# Section 3 – Parking sign / rules
# ═══════════════════════════════════════════════════════════════════════════

st.subheader("🪧 כלל חניה")

auto_rules = geo_ctx.municipal_restrictions or ""

if auto_rules:
    st.success("✅ כללי חניה זוהו אוטומטית לפי מיקומך — אין צורך בתמונת שלט")
    with st.expander("ערוך את הכלל ידנית אם צריך", expanded=False):
        sign_text = st.text_area("טקסט כלל", value=auto_rules, height=80, key="sign_auto")
else:
    sample_choice = st.selectbox("בחר שלט לדוגמה", SAMPLE_LABELS)
    default_text  = SAMPLE_MAP.get(sample_choice, "") if sample_choice != SAMPLE_LABELS[0] else ""
    sign_text = st.text_area(
        "הדבק טקסט שלט ידנית (עברית)",
        value=default_text,
        height=100,
        placeholder="לדוגמה: החניה מותרת לכולם עד השעה 17:00",
        key="sign_manual",
    )
    st.caption("📷 העלאת תמונה — בעתיד (Gemini / GPT-4o Vision API).")

# ═══════════════════════════════════════════════════════════════════════════
# Section 4 – User & Vehicle profile
# ═══════════════════════════════════════════════════════════════════════════

st.subheader("👤 פרטי משתמש ורכב (אופציונלי)")
st.caption("נתונים אלו אינם נשמרים — משמשים לחישוב בזמן אמת בלבד.")

with st.expander("הזן פרטי תו חניה ורכב", expanded=True):
    col_zone, col_vtype = st.columns(2)
    with col_zone:
        raw_zones  = st.text_input("אזורי חניה שברשותך (הפרד בפסיקים)", placeholder="1 או 1,2")
        user_zones = [z.strip() for z in raw_zones.split(",") if z.strip()]
    with col_vtype:
        vtype_he  = st.selectbox("סוג רכב", ["פרטי", "מסחרי", "אופנוע", "חשמלי"])
        vtype_map = {"פרטי": "private", "מסחרי": "commercial", "אופנוע": "motorcycle", "חשמלי": "electric"}
        vtype     = vtype_map[vtype_he]

    col_d, col_l, col_e = st.columns(3)
    has_disabled = col_d.checkbox("רישיון נכה")
    has_loading  = col_l.checkbox("אישור פריקה/טעינה")
    is_ev        = col_e.checkbox("רכב חשמלי")
    user_name    = st.text_input("שם (אופציונלי)", placeholder="ישראל ישראלי")

user_profile = UserProfile(
    user_id="streamlit_user",
    full_name=user_name or None,
    resident_parking_zones=user_zones,
    disabled_parking_permit=has_disabled,
    electric_vehicle=is_ev,
)
vehicle_profile = VehicleProfile(
    vehicle_id="streamlit_vehicle",
    vehicle_type=vtype,
    resident_parking_permits=user_zones,
    disabled_parking_permit=has_disabled,
    commercial_loading_permit=has_loading,
)

# ═══════════════════════════════════════════════════════════════════════════
# Section 5 – Check & Result
# ═══════════════════════════════════════════════════════════════════════════

st.divider()
run = st.button("✅ בדוק אם מותר לחנות כאן", type="primary", use_container_width=True)

if run:
    parsed_sign = parse_sign_text(sign_text) if sign_text.strip() else None
    request = ParkingRequest(
        lat=lat, lon=lon,
        current_datetime=current_dt,
        user_profile=user_profile,
        vehicle_profile=vehicle_profile,
    )
    decision: ParkingDecision = engine.decide(request, geo_ctx, parsed_sign)

    st.divider()
    st.subheader("📋 תוצאה")

    if decision.can_park is True:
        st.success("✅ מותר לחנות", icon="✅")
    elif decision.can_park is False:
        st.error("🚫 אסור לחנות", icon="🚫")
    else:
        st.warning("⚠️ לא ניתן לקבוע בוודאות", icon="⚠️")

    st.markdown(f'<div class="rtl">{decision.explanation_he}</div>', unsafe_allow_html=True)

    if decision.remaining_time:
        st.info(f"⏱️ {decision.remaining_time}")

    conf_color = {"high": "green", "medium": "orange", "low": "red"}.get(decision.confidence, "grey")
    st.markdown(f"**רמת ביטחון:** :{conf_color}[{decision.confidence}]")

    if decision.warnings:
        st.subheader("⚠️ אזהרות")
        for w in decision.warnings:
            st.markdown(f'<div class="rtl">• {w}</div>', unsafe_allow_html=True)

    st.divider()
    with st.expander("🔍 שלט מנותח (JSON)"):
        st.json(parsed_sign.model_dump() if parsed_sign else {"info": "לא סופק טקסט שלט"})
    with st.expander("🗺️ הקשר גיאוגרפי (JSON)"):
        st.json(geo_ctx.model_dump())
    with st.expander("👤 פרופיל (JSON)"):
        st.json({"user": user_profile.model_dump(), "vehicle": vehicle_profile.model_dump()})

# ── Footer ─────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    "⚠️ כלי זה מיועד לתמיכה בקבלת החלטות בלבד. "
    "אין להסתמך עליו כייעוץ משפטי או הבטחה לאי-קנס. "
    "תמיד בדוק את השלט בפועל."
)
