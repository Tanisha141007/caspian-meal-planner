"""Provider-agnostic wrapper around whichever LLM backs the meal planner's
generation and free-text parsing calls. Defaults to Gemini (Google AI
Studio's free tier - genuinely free, not a trial: no card, no expiry) since
that's what this project runs on; set LLM_PROVIDER=anthropic (+
ANTHROPIC_API_KEY) to swap to Claude instead - callers never change either
way, they just call generate_json(system, user)."""

import json

from app.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_PROVIDER,
)

_client = None
_client_provider = None


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.lower().startswith("json"):
            text = text.split("\n", 1)[1]
    return json.loads(text)


def _gemini_client():
    global _client, _client_provider
    if _client is None or _client_provider != "gemini":
        from google import genai

        _client = genai.Client(api_key=GEMINI_API_KEY)
        _client_provider = "gemini"
    return _client


def _anthropic_client():
    global _client, _client_provider
    if _client is None or _client_provider != "anthropic":
        from anthropic import Anthropic

        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
        _client_provider = "anthropic"
    return _client


def _generate_gemini(system: str, user: str, max_tokens: int) -> str:
    from google.genai import types

    response = _gemini_client().models.generate_content(
        model=GEMINI_MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",  # Gemini-native JSON mode, no fence-stripping needed
        ),
    )
    return response.text


def _generate_anthropic(system: str, user: str, max_tokens: int) -> str:
    response = _anthropic_client().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def generate_json(system: str, user: str, max_tokens: int = 4000) -> dict:
    """Runs one system+user prompt through the configured provider and
    parses the response as JSON. Both prompt builders already instruct the
    model to respond with JSON only."""
    if LLM_PROVIDER == "anthropic":
        text = _generate_anthropic(system, user, max_tokens)
    else:
        text = _generate_gemini(system, user, max_tokens)
    return _parse_json(text)
