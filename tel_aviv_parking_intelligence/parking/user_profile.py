from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """Represents a driver's identity and permit information."""
    user_id: str
    full_name: Optional[str] = None
    default_city: str = "תל אביב"
    # List of resident zone IDs the user holds a permit for, e.g. ["1", "2"]
    resident_parking_zones: List[str] = Field(default_factory=list)
    disabled_parking_permit: bool = False
    commercial_vehicle_permit: bool = False
    electric_vehicle: bool = False
    preferred_language: Literal["he", "en"] = "he"


class VehicleProfile(BaseModel):
    """Represents a specific vehicle and its parking entitlements."""
    vehicle_id: str
    # Deliberately Optional – do not use real license plates in test data
    license_plate: Optional[str] = None
    vehicle_type: Literal["private", "commercial", "motorcycle", "electric"] = "private"
    # Resident zone permit stickers affixed to this vehicle, e.g. ["1"]
    resident_parking_permits: List[str] = Field(default_factory=list)
    disabled_parking_permit: bool = False
    commercial_loading_permit: bool = False
