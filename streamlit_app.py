"""
Tel Aviv Parking Intelligence — Streamlit interface (v3).

Two tabs:
  Tab 1 – 👤 הפרופיל שלי   : User & vehicle profile (persisted in session state)
  Tab 2 – 🅿️ בדיקת חניה   : Location + time → AI-enhanced parking decision

AI mode uses Claude (claude-opus-4-7) when ANTHROPIC_API_KEY is set.
Falls back to deterministic rule engine otherwise.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import folium
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from parking.ai_agent import enhance_with_ai
from parking.geo_context import get_geo_context, get_street_rule
from parking.models import GeoContext, ParkingDecision, ParkingRequest
from parking.nominatim import geocode as nom_geocode, reverse_geocode
from parking.rule_engine import TLVParkingRuleEngine
from parking.sign_parser import parse_sign_text
from parking.user_profile import UserProfile, VehicleProfile

# ── Page config ────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="חניה חכמה – תל אביב",
    page_icon="🚗",
    layout="centered",
)

# ── Harmonious calming palette ─────────────────────────────────────────────────

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background-color: #f5f3ef; }
[data-testid="block-container"]    { background-color: #f5f3ef; }
[data-testid="stSidebar"]          { background-color: #e8f4f0; }
.stTabs [data-baseweb="tab"]       { font-size: 1.05rem; font-weight: 600; color: #3d6b68; }
.stTabs [aria-selected="true"]     { border-bottom: 3px solid #3d9e8c; color: #1a4f4c; }
.rtl { direction: rtl; text-align: right; font-size: 1.05rem; line-height: 1.7; color: #2c3e50; }
.card-ok   { background:#d4edda; border-left:5px solid #28a745; border-radius:8px; padding:14px 18px; margin:8px 0; }
.card-no   { background:#f8d7da; border-left:5px solid #c0392b; border-radius:8px; padding:14px 18px; margin:8px 0; }
.card-warn { background:#fff3cd; border-left:5px solid #f39c12; border-radius:8px; padding:14px 18px; margin:8px 0; }
.card-info { background:#d6eaf8; border-left:5px solid #2e86c1; border-radius:8px; padding:14px 18px; margin:8px 0; }
.stButton > button[kind="primary"] {
    background-color:#3d9e8c; color:white; border:none;
    border-radius:10px; font-size:1.05rem; font-weight:700; padding:0.6rem 1.4rem;
}
.stButton > button[kind="primary"]:hover { background-color:#2e7a6a; }
</style>
""", unsafe_allow_html=True)

# ── Cached loaders ─────────────────────────────────────────────────────────────

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
engine        = TLVParkingRuleEngine()

ZONE_COLORS = {"1": "blue", "2": "green", "3": "orange", "4": "purple", "5": "red"}
ZONE_FLAGS  = {"1": "🔵", "2": "🟢", "3": "🟠", "4": "🟣", "5": "🔴"}

# ── Session-state defaults ─────────────────────────────────────────────────────

def _init_state():
    defaults = {
        "lat": 32.0845,
        "lon": 34.7714,
        "last_map_click": None,
        "time_key": 0,
        "user_zones": [],
        "vtype": "private",
        "has_disabled": False,
        "has_loading": False,
        "is_ev": False,
        "user_name": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# ── GPS query-param injection ──────────────────────────────────────────────────

params = st.query_params
if "lat" in params and "lon" in params:
    try:
        st.session_state.lat = float(params["lat"])
        st.session_state.lon = float(params["lon"])
        st.query_params.clear()
    except (ValueError, TypeError):
        pass

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙️ הגדרות")
    api_key_input = st.text_input(
        "מפתח Anthropic API (אופציונלי)",
        type="password",
        placeholder="sk-ant-...",
        help="הגדר מפתח API לקבלת תוצאות משופרות עם Claude AI.",
    )
    if api_key_input.strip():
        os.environ["ANTHROPIC_API_KEY"] = api_key_input.strip()

    ai_active = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if ai_active:
        st.success("🤖 מצב AI פעיל — Claude Opus 4.7")
    else:
        st.info("⚙️ מצב כללים — ללא AI")

    st.divider()
    st.caption("⚠️ כלי זה מיועד לתמיכה בלבד. אין לסמוך עליו כייעוץ משפטי.")

# ── Header ─────────────────────────────────────────────────────────────────────

st.markdown(
    "<h1 style='text-align:center;color:#1a4f4c;margin-bottom:0'>🚗 חניה חכמה — תל אביב</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='text-align:center;color:#5d7f7c;font-size:0.95rem'>בדוק היכן וכיצד לחנות — בזמן אמת</p>",
    unsafe_allow_html=True,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Tabs
# ═══════════════════════════════════════════════════════════════════════════════

tab_profile, tab_check = st.tabs(["👤 הפרופיל שלי", "🅿️ בדיקת חניה"])

# ── TAB 1 – Profile ────────────────────────────────────────────────────────────

with tab_profile:
    st.markdown("<h3 style='color:#1a4f4c'>הפרופיל שלי</h3>", unsafe_allow_html=True)
    st.caption("הזן את פרטיך פעם אחת — הנתונים נשמרים בסשן הנוכחי ומשמשים לכל הבדיקות.")

    col_name, col_vtype = st.columns(2)
    with col_name:
        name_val = st.text_input("שמך (אופציונלי)", value=st.session_state.user_name, placeholder="ישראל ישראלי")
        st.session_state.user_name = name_val
    with col_vtype:
        vtype_options_he = ["פרטי", "מסחרי", "אופנוע", "חשמלי"]
        vtype_map = {"פרטי": "private", "מסחרי": "commercial", "אופנוע": "motorcycle", "חשמלי": "electric"}
        vtype_map_rev = {v: k for k, v in vtype_map.items()}
        vtype_he_idx = vtype_options_he.index(vtype_map_rev.get(st.session_state.vtype, "פרטי"))
        vtype_he = st.selectbox("סוג רכב", vtype_options_he, index=vtype_he_idx)
        st.session_state.vtype = vtype_map[vtype_he]

    raw_zones = st.text_input(
        "אזורי חניה שברשותך (הפרד בפסיקים)",
        value=", ".join(st.session_state.user_zones),
        placeholder="לדוגמה: 1 או 1,2",
    )
    st.session_state.user_zones = [z.strip() for z in raw_zones.split(",") if z.strip()]

    st.markdown("**הרשאות מיוחדות**")
    col_d, col_l, col_e = st.columns(3)
    st.session_state.has_disabled = col_d.checkbox("♿ תו נכה",             value=st.session_state.has_disabled)
    st.session_state.has_loading  = col_l.checkbox("📦 אישור פריקה/טעינה", value=st.session_state.has_loading)
    st.session_state.is_ev        = col_e.checkbox("⚡ רכב חשמלי",          value=st.session_state.is_ev)

    st.divider()
    zones_str = ", ".join(st.session_state.user_zones) if st.session_state.user_zones else "אין"
    perms = []
    if st.session_state.has_disabled: perms.append("תו נכה")
    if st.session_state.has_loading:  perms.append("פריקה/טעינה")
    if st.session_state.is_ev:        perms.append("חשמלי")
    perms_str = " | ".join(perms) if perms else "אין"
    st.markdown(f"""
    <div class="card-info rtl">
    <b>סיכום פרופיל:</b><br>
    🚗 סוג רכב: {vtype_he} &nbsp;|&nbsp; 🏷️ אזורים: {zones_str}<br>
    🔑 הרשאות: {perms_str}
    </div>
    """, unsafe_allow_html=True)
    st.caption("עבור ללשונית '🅿️ בדיקת חניה' כדי לבדוק חניה לפי מיקום.")

# ── TAB 2 – Parking check ──────────────────────────────────────────────────────

with tab_check:
    st.markdown("<h3 style='color:#1a4f4c'>בדיקת חניה</h3>", unsafe_allow_html=True)

    # Location
    st.markdown("#### 📍 מיקום")

    components.html("""
    <style>
      .gps-btn { background:#3d9e8c;color:white;border:none;padding:9px 20px;
                 border-radius:8px;cursor:pointer;font-size:14px;font-family:sans-serif;font-weight:600; }
      .gps-btn:hover { background:#2e7a6a; }
      .gps-btn:disabled { background:#aac8c3;cursor:default; }
    </style>
    <button class="gps-btn" id="btn" onclick="
      var btn=document.getElementById('btn');
      btn.disabled=true; btn.textContent='⏳ מאתר מיקום...';
      navigator.geolocation.getCurrentPosition(
        function(pos){
          var url=new URL(window.parent.location.href);
          url.searchParams.set('lat',pos.coords.latitude.toFixed(6));
          url.searchParams.set('lon',pos.coords.longitude.toFixed(6));
          window.parent.location.href=url.toString();
        },
        function(err){
          alert('לא ניתן לאתר מיקום: '+err.message);
          btn.disabled=false; btn.textContent='📍 השתמש במיקומי הנוכחי';
        },
        {enableHighAccuracy:true,timeout:10000}
      );
    ">📍 השתמש במיקומי הנוכחי</button>
    """, height=55)

    addr_col, go_col = st.columns([5, 1])
    with addr_col:
        address_input = st.text_input("חיפוש", placeholder="לדוגמה: דיזנגוף 50 תל אביב", label_visibility="collapsed")
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

    lat = st.session_state.lat
    lon = st.session_state.lon

    m = folium.Map(location=[lat, lon], zoom_start=15, tiles="CartoDB positron")
    for zone in ZONES:
        color = ZONE_COLORS.get(zone["zone_id"], "gray")
        flag  = ZONE_FLAGS.get(zone["zone_id"], "⚪")
        folium.Circle(
            location=[zone["center_lat"], zone["center_lon"]],
            radius=zone["radius_meters"],
            color=color, fill=True, fill_opacity=0.12, weight=2,
            tooltip=f"{flag} {zone['name']}",
            popup=folium.Popup(f"<b>{flag} {zone['name']}</b><br><small>{zone['description']}</small>", max_width=220),
        ).add_to(m)
    folium.Marker(
        location=[lat, lon],
        icon=folium.Icon(color="red", icon="car", prefix="fa"),
        tooltip="מיקום נבחר — לחץ על המפה לשינוי",
    ).add_to(m)

    map_data = st_folium(m, height=350, width="100%", returned_objects=["last_clicked"], key="main_map")

    if map_data and map_data.get("last_clicked"):
        clicked = (round(map_data["last_clicked"]["lat"], 6), round(map_data["last_clicked"]["lng"], 6))
        if clicked != st.session_state.last_map_click:
            st.session_state.last_map_click = clicked
            st.session_state.lat, st.session_state.lon = clicked
            st.rerun()

    st.caption(f"📌 {lat:.5f}, {lon:.5f}  |  " + "  ".join(f"{ZONE_FLAGS[z]} אזור {z}" for z in ZONE_FLAGS))

    # Auto-detect street
    geo_ctx = get_geo_context(lat, lon)
    if not geo_ctx.street_name:
        nom_data = _cached_reverse_geocode(round(lat, 4), round(lon, 4))
        if nom_data:
            addr_data = nom_data.get("address", {})
            street_he = addr_data.get("road") or addr_data.get("pedestrian") or addr_data.get("neighbourhood")
            if street_he:
                geo_ctx = GeoContext(
                    lat=lat, lon=lon, street_name=street_he,
                    parking_zone=geo_ctx.parking_zone,
                    municipal_restrictions=geo_ctx.municipal_restrictions,
                    source="nominatim",
                )

    if geo_ctx.street_name:
        zone_badge = f"אזור {geo_ctx.parking_zone}" if geo_ctx.parking_zone else "אזור לא מזוהה"
        st.markdown(f'<div class="card-info rtl">📍 <b>{geo_ctx.street_name}</b> — {zone_badge}</div>', unsafe_allow_html=True)
    else:
        st.warning("הרחוב לא זוהה. נסה לחפש כתובת או לחץ על מיקום ידוע במפה.")

    # Date & Time
    st.markdown("#### 🕐 תאריך ושעה")
    now = datetime.now()
    col_date, col_time, col_now = st.columns([2, 2, 1])
    with col_date:
        check_date = st.date_input("תאריך", value=now.date(), key=f"date_{st.session_state.time_key}")
    with col_time:
        check_time = st.time_input("שעה", value=now.time(), key=f"time_{st.session_state.time_key}")
    with col_now:
        st.write("")
        if st.button("עכשיו ⏱️"):
            st.session_state.time_key += 1
            st.rerun()
    current_dt = datetime.combine(check_date, check_time)

    # Parking sign (optional)
    auto_rules = geo_ctx.municipal_restrictions or ""
    with st.expander("🪧 כלל חניה (אופציונלי)", expanded=not bool(auto_rules)):
        if auto_rules:
            st.success("✅ כללי חניה זוהו אוטומטית לפי מיקומך")
            sign_text = st.text_area("ערוך ידנית אם צריך", value=auto_rules, height=70, key="sign_auto")
        else:
            sample_choice = st.selectbox("בחר שלט לדוגמה", SAMPLE_LABELS)
            default_text  = SAMPLE_MAP.get(sample_choice, "") if sample_choice != SAMPLE_LABELS[0] else ""
            sign_text = st.text_area(
                "הדבק טקסט שלט ידנית (עברית)", value=default_text, height=80,
                placeholder="לדוגמה: החניה מותרת לכולם עד השעה 17:00", key="sign_manual",
            )

    # Check button
    st.divider()
    run = st.button("✅ בדוק אם מותר לחנות כאן", type="primary", use_container_width=True)

    if run:
        user_profile = UserProfile(
            user_id="streamlit_user",
            full_name=st.session_state.user_name or None,
            resident_parking_zones=st.session_state.user_zones,
            disabled_parking_permit=st.session_state.has_disabled,
            electric_vehicle=st.session_state.is_ev,
        )
        vehicle_profile = VehicleProfile(
            vehicle_id="streamlit_vehicle",
            vehicle_type=st.session_state.vtype,
            resident_parking_permits=st.session_state.user_zones,
            disabled_parking_permit=st.session_state.has_disabled,
            commercial_loading_permit=st.session_state.has_loading,
        )

        parsed_sign = parse_sign_text(sign_text) if sign_text.strip() else None
        request = ParkingRequest(lat=lat, lon=lon, current_datetime=current_dt,
                                 user_profile=user_profile, vehicle_profile=vehicle_profile)

        with st.spinner("🤖 מחשב…"):
            deterministic = engine.decide(request, geo_ctx, parsed_sign)
            street_rule   = get_street_rule(lat, lon)
            decision      = enhance_with_ai(request, geo_ctx, deterministic, parsed_sign, street_rule)

        # Result
        st.divider()
        st.markdown("<h3 style='color:#1a4f4c'>📋 תוצאה</h3>", unsafe_allow_html=True)

        if decision.can_park is True:
            st.markdown('<div class="card-ok rtl">✅ <b>מותר לחנות</b></div>', unsafe_allow_html=True)
        elif decision.can_park is False:
            st.markdown('<div class="card-no rtl">🚫 <b>אסור לחנות</b></div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="card-warn rtl">⚠️ <b>לא ניתן לקבוע בוודאות</b></div>', unsafe_allow_html=True)

        st.markdown(f'<div class="rtl" style="margin-top:10px">{decision.explanation_he}</div>', unsafe_allow_html=True)

        details_parts = []
        if decision.side:
            side_labels = {"right": "ימין ←", "left": "→ שמאל", "both": "שני הצדדים ↔"}
            details_parts.append(f"🚗 <b>צד חניה:</b> {side_labels.get(decision.side, decision.side)}")
        if decision.payment_required is True:
            details_parts.append(f"💳 <b>תשלום:</b> {decision.payment_details or 'נדרש תשלום'}")
        elif decision.payment_required is False:
            details_parts.append("💳 <b>תשלום:</b> לא נדרש (חינם)")
        if decision.max_duration_minutes:
            h, m = divmod(decision.max_duration_minutes, 60)
            dur = f"{h} שעות {m} דקות" if h else f"{m} דקות"
            details_parts.append(f"⏱️ <b>מקסימום:</b> {dur}")
        if decision.remaining_time:
            details_parts.append(f"⌛ <b>זמן שנותר:</b> {decision.remaining_time}")

        if details_parts:
            st.markdown('<div class="card-info rtl">' + "<br>".join(details_parts) + "</div>", unsafe_allow_html=True)

        conf_color = {"high": "#27ae60", "medium": "#e67e22", "low": "#c0392b"}.get(decision.confidence, "#7f8c8d")
        mode_badge = "🤖 Claude AI" if decision.ai_enhanced else "⚙️ מנוע כללים"
        st.markdown(
            f"<small style='color:#7f8c8d'>רמת ביטחון: "
            f"<span style='color:{conf_color};font-weight:700'>{decision.confidence}</span>"
            f" &nbsp;|&nbsp; {mode_badge}</small>",
            unsafe_allow_html=True,
        )

        if decision.warnings:
            st.markdown("**⚠️ אזהרות:**")
            for w in decision.warnings:
                st.markdown(f'<div class="rtl">• {w}</div>', unsafe_allow_html=True)

        st.divider()
        with st.expander("🔍 פרטים טכניים"):
            col_a, col_b = st.columns(2)
            with col_a:
                st.caption("שלט מנותח")
                st.json(parsed_sign.model_dump() if parsed_sign else {"info": "לא סופק"})
            with col_b:
                st.caption("הקשר גיאוגרפי")
                st.json(geo_ctx.model_dump())
            if street_rule:
                st.caption("נתוני רחוב")
                st.json(street_rule)

# ── Footer ─────────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    "⚠️ כלי זה מיועד לתמיכה בקבלת החלטות בלבד. "
    "אין להסתמך עליו כייעוץ משפטי או הבטחה לאי-קנס. "
    "תמיד בדוק את השלט בפועל."
)
