from __future__ import annotations
from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from .user_profile import UserProfile, VehicleProfile  # noqa: F401 – re-exported


class TimeRule(BaseModel):
    """A time window during which a parking rule is active."""
    start_time: str          # "HH:MM" – 24-hour format
    end_time: str            # "HH:MM" – may be earlier than start for overnight ranges
    days: Optional[List[str]] = None  # Hebrew weekday letters; None = every day


class AmbiguityWarning(BaseModel):
    field: str       # which field is unclear
    message_he: str  # Hebrew explanation for the user


class ParsedParkingSign(BaseModel):
    """Structured information extracted from a parking sign."""
    raw_text: str
    # Time windows where NO ONE may park
    no_parking_windows: List[TimeRule] = Field(default_factory=list)
    # Time windows where ONLY residents may park
    resident_only_windows: List[TimeRule] = Field(default_factory=list)
    # Time windows explicitly stated as free for everyone
    free_parking_windows: List[TimeRule] = Field(default_factory=list)
    # Sign says resident-only without a time qualifier
    resident_only_all_times: bool = False
    # Zone number required for resident parking (e.g. "1")
    resident_zone: Optional[str] = None
    # "Free for everyone until HH:MM" – shorthand found on many TLV signs
    free_until: Optional[str] = None
    # Weekday restrictions extracted from the sign text (None = all days)
    day_restrictions: Optional[List[str]] = None
    arrow_direction: Optional[str] = None
    no_parking_at_all: bool = False   # absolute prohibition with no time qualifier
    loading_zone: bool = False        # loading/unloading only
    disabled_only: bool = False       # handicapped bay
    ambiguities: List[AmbiguityWarning] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class GeoContext(BaseModel):
    """Geographic and municipal context resolved from a lat/lon coordinate."""
    lat: float
    lon: float
    street_name: Optional[str] = None
    parking_zone: Optional[str] = None       # municipal zone ID at this location
    street_side: Optional[str] = None
    municipal_restrictions: Optional[str] = None
    source: str = "mock"                     # "mock" | "open_data" | "gis" | "geocoding"


class ParkingRequest(BaseModel):
    """Unified input model for a parking eligibility check."""
    lat: float
    lon: float
    current_datetime: datetime
    # Convenience shorthand – used when no full profile is available
    user_zone: Optional[str] = None
    user_profile: Optional[UserProfile] = None
    vehicle_profile: Optional[VehicleProfile] = None
    sign_text: Optional[str] = None
    image_path: Optional[str] = None
    arrow_direction: Optional[str] = None


class ParkingDecision(BaseModel):
    """Output of the rule engine / AI agent."""
    can_park: Optional[bool] = None          # None = insufficient information to decide
    confidence: Literal["high", "medium", "low"] = "low"
    remaining_time: Optional[str] = None     # human-readable Hebrew duration string
    explanation_he: str                      # Hebrew explanation shown to the driver
    geo_context: Optional[GeoContext] = None
    parsed_sign: Optional[ParsedParkingSign] = None
    warnings: List[str] = Field(default_factory=list)
    # AI-enhanced fields
    side: Optional[str] = None               # "right" | "left" | "both" | None
    payment_required: Optional[bool] = None
    max_duration_minutes: Optional[int] = None
    payment_details: Optional[str] = None    # Hebrew string, e.g. "₪5/שעה"
    ai_enhanced: bool = False                # True when Claude filled in the extra fields
