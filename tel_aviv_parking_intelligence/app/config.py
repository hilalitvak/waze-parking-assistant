import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Config:
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    use_mock_vision: bool = True
    use_mock_geo: bool = True
    app_env: str = "development"


def load_config() -> Config:
    return Config(
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        use_mock_vision=os.environ.get("USE_MOCK_VISION", "true").lower() == "true",
        use_mock_geo=os.environ.get("USE_MOCK_GEO", "true").lower() == "true",
        app_env=os.environ.get("APP_ENV", "development"),
    )


settings = load_config()
