"""
Extracts text from a parking sign image.

Current implementation: mock — returns pre-defined Hebrew text so the project
runs without any API key.

To integrate a real vision model, replace _call_gemini_vision() or
_call_openai_vision() below and set USE_MOCK_VISION=false in your environment.

Expected output schema (for the real implementation):
  {
    "raw_text": "...",           # full Hebrew text as seen on the sign
    "confidence": 0.0–1.0
  }
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# TODO: real vision integration – swap the function body below
# ---------------------------------------------------------------------------

def _call_gemini_vision(image_path: str) -> str:
    """
    TODO: implement with google-generativeai SDK.

    Example skeleton:
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        model = genai.GenerativeModel("gemini-1.5-flash")
        with open(image_path, "rb") as f:
            image_data = f.read()
        response = model.generate_content([
            "Extract all Hebrew text from this Israeli parking sign. "
            "Return only the sign text, no explanation.",
            {"mime_type": "image/jpeg", "data": image_data},
        ])
        return response.text
    """
    raise NotImplementedError("Gemini vision not yet configured")


def _call_openai_vision(image_path: str) -> str:
    """
    TODO: implement with openai SDK.

    Example skeleton:
        import base64, openai
        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all Hebrew text from this Israeli parking sign."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }],
        )
        return response.choices[0].message.content
    """
    raise NotImplementedError("OpenAI vision not yet configured")


# ---------------------------------------------------------------------------
# Mock implementation
# ---------------------------------------------------------------------------

_MOCK_TEXT = (
    "החניה מותרת לכולם עד השעה 17:00\n"
    "לאחר 17:00 לבעלי תו אזורי 1 בלבד"
)


def extract_sign_text(image_path: Optional[str] = None, use_mock: bool = True) -> str:
    """
    Return Hebrew text extracted from a parking sign image.

    Args:
        image_path: Path to the image file (required when use_mock=False).
        use_mock:   When True, returns hard-coded sample text without any API call.

    Returns:
        Raw Hebrew text string from the sign.
    """
    if use_mock or image_path is None:
        return _MOCK_TEXT

    # Try Gemini first, fall back to OpenAI
    try:
        return _call_gemini_vision(image_path)
    except NotImplementedError:
        pass

    try:
        return _call_openai_vision(image_path)
    except NotImplementedError:
        pass

    raise RuntimeError(
        "No vision provider is configured. "
        "Set GEMINI_API_KEY or OPENAI_API_KEY and USE_MOCK_VISION=false."
    )
