import sys
from pathlib import Path

# Ensure the project root is importable when running with `uvicorn app.main:app`
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from parking.api import router

app = FastAPI(
    title="Tel Aviv Parking Intelligence",
    description=(
        "Geospatial parking rule engine for Tel Aviv. "
        "Answers: 'Can I legally park here right now?' "
        "The final decision is always made by a deterministic rule engine — "
        "not by an LLM."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "service": "tel-aviv-parking-intelligence"}
