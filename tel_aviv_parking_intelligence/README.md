# Tel Aviv Parking Intelligence

A geospatial parking-rule engine for Tel Aviv that answers:

> **"Can I legally park here right now?"**

Designed as an API-first MVP that can be integrated into navigation apps such as Waze, Google Maps, Moovit, or in-car navigation systems.

---

## Architecture

```
User location + datetime + sign text
        │
        ▼
┌──────────────────┐    ┌──────────────────┐
│  Vision Extractor │    │   Geo Context    │
│  (OCR / mock)    │    │  (PostGIS / mock) │
└────────┬─────────┘    └────────┬─────────┘
         │ raw Hebrew text        │ zone, street, restrictions
         ▼                        ▼
┌──────────────────┐    ┌──────────────────┐
│   Sign Parser    │    │  User / Vehicle  │
│  (regex-based)   │    │     Profiles     │
└────────┬─────────┘    └────────┬─────────┘
         │ ParsedParkingSign      │ permits, vehicle type
         └──────────┬────────────┘
                    ▼
         ┌────────────────────┐
         │  Rule Engine       │  ← deterministic, no LLM
         │  TLVParkingRuleEngine│
         └────────┬───────────┘
                  ▼
         ParkingDecision JSON
         { can_park, confidence,
           remaining_time, explanation_he,
           warnings }
```

### Why the LLM does NOT make the parking decision

LLMs are probabilistic. A parking ticket is a deterministic outcome. The rule engine:

- Is fully auditable — every decision maps to a specific code path
- Can be unit tested exhaustively
- Produces a Hebrew explanation users can understand
- Returns `can_park=null` with a reason instead of guessing when data is missing

The LLM (Gemini / GPT-4o) is only used for **OCR** — extracting Hebrew text from a sign image. The extracted text is then parsed by deterministic regex rules, and the parsed rules are evaluated by the deterministic engine.

---

## Project Structure

```
tel_aviv_parking_intelligence/
├── app/
│   ├── main.py           FastAPI application factory
│   └── config.py         Environment-based configuration
├── parking/
│   ├── models.py         All Pydantic request/response models
│   ├── user_profile.py   UserProfile and VehicleProfile models
│   ├── geo_context.py    Lat/lon → parking zone resolver
│   ├── sign_vision.py    OCR extraction (mock + TODO stubs for Gemini/GPT-4o)
│   ├── sign_parser.py    Hebrew regex sign parser
│   ├── rule_engine.py    Deterministic parking decision engine
│   └── api.py            FastAPI router
├── data/
│   ├── mock_parking_zones.json
│   ├── mock_street_rules.json
│   └── sample_sign_texts.json
├── tests/
│   ├── test_rule_engine.py
│   ├── test_sign_parser.py
│   └── test_geo_context.py
├── streamlit_app.py      Streamlit demo UI
├── requirements.txt
└── README.md
```

---

## Installation

```bash
# 1. Clone / enter the project directory
cd tel_aviv_parking_intelligence

# 2. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Running the FastAPI server

```bash
# From inside tel_aviv_parking_intelligence/
uvicorn app.main:app --reload --port 8000
```

Interactive docs: http://localhost:8000/docs

### Example request

```bash
curl -X POST http://localhost:8000/api/v1/can_i_park_here \
  -H "Content-Type: application/json" \
  -d '{
    "lat": 32.0845,
    "lon": 34.7714,
    "current_datetime": "2026-05-03T18:30:00",
    "sign_text": "החניה מותרת לכולם עד השעה 17:00\nלאחר 17:00 לבעלי תו אזורי 1 בלבד",
    "user_profile": {
      "user_id": "u1",
      "resident_parking_zones": ["1"]
    },
    "vehicle_profile": {
      "vehicle_id": "v1",
      "vehicle_type": "private",
      "resident_parking_permits": ["1"]
    }
  }'
```

---

## Running the Streamlit demo

```bash
# From inside tel_aviv_parking_intelligence/
streamlit run streamlit_app.py
```

The UI lets you:
- Enter a location (lat/lon) or pick a sample street
- Set the current date and time (or use "Now")
- Paste Hebrew sign text or choose a sample sign
- Enter user and vehicle permit details
- See the parking decision in Hebrew with confidence and remaining time
- Inspect the parsed sign and geo context JSON (debug mode)

---

## Running the tests

```bash
# From inside tel_aviv_parking_intelligence/
pytest tests/ -v
```

Key test scenarios covered:

| # | Scenario | Expected |
|---|----------|----------|
| A | Free period (before cutoff) | `can_park=True` |
| B | User profile has matching zone | `can_park=True` |
| B2 | Vehicle profile has matching zone | `can_park=True` |
| C | User has wrong zone | `can_park=False` |
| D | No permit info provided | `can_park=None` |
| E | No-parking window active | `can_park=False` |
| F | Sign missing zone, GeoContext provides it | `can_park=True/False` |
| G | Loading zone + commercial permit | `can_park=True` |
| H | Disabled permit overrides resident restriction | `can_park=True` |
| I | Weekday restriction, checked on Saturday | `can_park=True` |
| J | No sign, no geo data | `can_park=None` |

---

## User & Vehicle Profiles

The engine considers (in order):

1. **VehicleProfile.resident_parking_permits** — stickers on the vehicle
2. **UserProfile.resident_parking_zones** — zones the driver holds a permit for
3. **ParkingRequest.user_zone** — legacy shorthand

Special overrides:
- `disabled_parking_permit=True` → overrides resident-zone restrictions
- `commercial_loading_permit=True` → allows parking in loading zones
- `vehicle_type=electric` → reserved for future EV-bay rules

---

## Adding real Tel Aviv GIS / Open Data

Replace `parking/geo_context.py` with a real data source. The function signature must remain:

```python
def get_geo_context(lat: float, lon: float) -> GeoContext:
    ...
```

Suggested sources:
- **Tel Aviv Open Data** — https://opendata.tel-aviv.gov.il  
  Endpoint: `הגבלות חניה ואזורי חניה מוסדרים`
- **Tel Aviv GIS** — WMS / WFS layers for parking zones
- **PostGIS / GeoPandas** — load municipal shapefiles and run spatial queries
- **Google Maps Geocoding API** — reverse-geocode to street name, then look up rules

---

## Adding Gemini / GPT-4o Vision

Open `parking/sign_vision.py` and implement either:

```python
def _call_gemini_vision(image_path: str) -> str:
    # see TODO comment in the file
    ...

def _call_openai_vision(image_path: str) -> str:
    # see TODO comment in the file
    ...
```

Then set environment variables:

```bash
export GEMINI_API_KEY=your-key
export USE_MOCK_VISION=false
```

The rest of the pipeline (parser → rule engine) requires no changes.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | — | Google Gemini API key for vision |
| `OPENAI_API_KEY` | — | OpenAI API key for GPT-4o vision |
| `USE_MOCK_VISION` | `true` | Use mock OCR instead of real API |
| `USE_MOCK_GEO` | `true` | Use mock JSON files for geo data |
| `APP_ENV` | `development` | `development` / `production` |

---

## Limitations

- **Mock data only** — GIS layers and street rules are simplified approximations of Tel Aviv.
- **Single-sign assumption** — the parser assumes one parking rule per text block. Intersections with multiple signs require multiple calls.
- **Hebrew regex coverage** — the parser handles the most common Tel Aviv sign formats. Edge cases (e.g., construction signs, temporary bans) are not yet covered.
- **No real-time data** — the engine does not connect to live parking availability feeds.
- **City scope** — the engine is designed for Tel Aviv only. Other Israeli cities have different zone systems.

---

## Privacy Notice

User and vehicle profile data entered via the Streamlit UI or API is **processed in memory only** and is **never stored**. No personal data, license plate numbers, or location history is persisted in this MVP.

Do not enter real license plate numbers in test data or bug reports.

---

## Legal Disclaimer

This tool is for **decision support only**. It is not legal advice. Always read the physical parking sign at your location. The authors accept no liability for parking fines, towing, or other consequences resulting from reliance on this tool.
