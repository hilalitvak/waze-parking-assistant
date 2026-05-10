# Tel Aviv Parking Intelligence 🚗

A smart parking assistant for Tel Aviv drivers — powered by a deterministic rule engine and optionally enhanced by **Claude AI (claude-opus-4-7)**.

> **"Can I park here? On which side? Is it pay-to-park? For how long?"**

---

## What it does

| Feature | Detail |
|---|---|
| 📍 Location | GPS, map click, or address search (Nominatim/OSM) |
| 🗺️ Auto-detected rules | 26 streets across 5 parking zones — no sign photo needed |
| 🤖 Claude AI enrichment | Side of street, payment info, duration (when API key is set) |
| ⚙️ Deterministic fallback | Full rule engine — works without any API key |
| 🕐 Time-aware | Checks current or manually set date/time |
| 👤 User profile | Zone permits, vehicle type, disabled/loading/EV privileges |

---

## App structure

The app has **two tabs**:

### Tab 1 — 👤 הפרופיל שלי (My Profile)
Set your driver profile once per session:
- Residential parking zone permits (e.g. Zone 1, Zone 2)
- Vehicle type (private / commercial / motorcycle / electric)
- Special permits: disabled, loading/unloading, electric vehicle

### Tab 2 — 🅿️ בדיקת חניה (Parking Check)
1. **Pick a location** via GPS button, map click, or address search
2. **Set the time** (defaults to now, with a "now" reset button)
3. **Click "בדוק"** — get an instant result showing:
   - ✅ / 🚫 Can you park?
   - 🚗 Which side of the street
   - 💳 Payment required + price per hour
   - ⏱️ Maximum parking duration
   - Full Hebrew explanation

---

## Architecture

```
streamlit_app.py
├── Tab 1: Profile editor  → session state
└── Tab 2: Parking check
    ├── parking/geo_context.py    — lat/lon → GeoContext + raw street data
    ├── parking/rule_engine.py    — 11-rule deterministic decision
    ├── parking/sign_parser.py    — Hebrew sign text parser
    └── parking/ai_agent.py       — Claude API enrichment (optional)
                                     ↳ model: claude-opus-4-7
                                     ↳ tool_use: parking_decision
                                     ↳ prompt caching on system prompt
                                     ↳ graceful fallback if no API key
```

**Decision flow:**
1. Geo context resolves street name, zone, and municipal rules from `data/mock_street_rules.json`
2. Rule engine runs 11-priority chain → `ParkingDecision` (can_park + Hebrew explanation)
3. If `ANTHROPIC_API_KEY` is set, Claude enriches the decision with side/payment/duration fields
4. Result is displayed with color-coded cards in calming teal/cream palette

---

## Setup

```bash
# 1. Clone
git clone https://github.com/hilalitvak/waze-parking-assistant
cd waze-parking-assistant

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Add your Anthropic API key for AI mode
export ANTHROPIC_API_KEY=sk-ant-...   # macOS/Linux
$env:ANTHROPIC_API_KEY="sk-ant-..."   # PowerShell / Windows

# 4. Launch
streamlit run streamlit_app.py
```

The API key can also be entered directly in the app sidebar — no environment variable needed.

---

## Data coverage

**26 streets, 5 zones:**

| Zone | Color | Streets |
|---|---|---|
| 1 | 🔵 | דיזנגוף, בן יהודה, פרישמן, גורדון, הירקון, שדרות בן גוריון, נורדאו |
| 2 | 🟢 | רוטשילד, אלנבי, נחמני, שינקין, יהודה הלוי, ביאליק, לילינבלום, מזא"ה |
| 3 | 🟠 | יהודה המכבי, ארלוזורוב, כצנלסון, ז'בוטינסקי, שאול המלך, אבן גבירול |
| 4 | 🟣 | שבזי, אחד העם |
| 5 | 🔴 | פלורנטין, סלמה, שדרות ירושלים |

---

## Tests

```bash
python -m pytest tests/ -v
```

49 tests covering all 11 rule-engine decision paths, sign parser edge cases, and profile overrides.

---

## Disclaimer

⚠️ This tool is for decision support only. Do not rely on it as legal advice or a guarantee against fines. Always verify the physical sign.
