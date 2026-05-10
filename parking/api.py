from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .geo_context import get_geo_context
from .models import ParkingDecision, ParkingRequest
from .rule_engine import TLVParkingRuleEngine
from .sign_parser import parse_sign_text
from .sign_vision import extract_sign_text

router = APIRouter(tags=["parking"])
_engine = TLVParkingRuleEngine()


@router.post("/can_i_park_here", response_model=ParkingDecision)
def can_i_park_here(request: ParkingRequest) -> ParkingDecision:
    """
    Main endpoint: given location, time, and optional sign text, decide whether
    parking is currently allowed.

    The LLM / vision model is only invoked for text extraction (if image_path is
    provided). All parking logic is deterministic.
    """
    geo_context = get_geo_context(request.lat, request.lon)

    # Determine sign text source
    raw_text: str | None = request.sign_text
    if not raw_text and request.image_path:
        try:
            raw_text = extract_sign_text(image_path=request.image_path, use_mock=False)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Vision extraction failed: {exc}",
            )

    parsed_sign = parse_sign_text(raw_text) if raw_text else None
    return _engine.decide(request, geo_context, parsed_sign)


@router.get("/zones", summary="List all mock parking zones")
def list_zones():
    import json
    from pathlib import Path

    data_path = Path(__file__).parent.parent / "data" / "mock_parking_zones.json"
    with open(data_path, encoding="utf-8") as fh:
        return json.load(fh)


@router.get("/sample_signs", summary="List sample Hebrew sign texts for testing")
def sample_signs():
    import json
    from pathlib import Path

    data_path = Path(__file__).parent.parent / "data" / "sample_sign_texts.json"
    with open(data_path, encoding="utf-8") as fh:
        return json.load(fh)
