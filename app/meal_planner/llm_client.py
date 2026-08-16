"""Provider-agnostic wrapper around whichever LLM backs the meal planner's
generation and free-text parsing calls. Defaults to Gemini (Google AI
Studio's free tier - genuinely free, not a trial: no card, no expiry) since
that's what this project runs on; set LLM_PROVIDER=anthropic (+
ANTHROPIC_API_KEY) to swap to Claude instead - callers never change either
way, they just call generate_json(system, user)."""

import json
import time

from app.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_PROVIDER,
)

_client = None
_client_provider = None

# Free-tier Gemini genuinely returns "503 UNAVAILABLE... currently
# experiencing high demand" under real, ordinary load - hit this live, not
# hypothetical. Retried with backoff since it's transient by definition;
# NOT retried are 4xx-type errors (bad request, auth, model-not-found) -
# those need a code/config fix, not another attempt.
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (1, 3)


def _is_retryable(exc: Exception) -> bool:
    try:
        from google.genai.errors import ServerError

        if isinstance(exc, ServerError):
            return True
    except ImportError:
        pass
    try:
        from anthropic import APIConnectionError, APITimeoutError, InternalServerError, OverloadedError, RateLimitError

        if isinstance(exc, (InternalServerError, OverloadedError, APIConnectionError, APITimeoutError, RateLimitError)):
            return True
    except ImportError:
        pass
    return False


def _with_retry(fn):
    last_exc = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if not _is_retryable(e) or attempt == _MAX_ATTEMPTS - 1:
                raise
            time.sleep(_BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)])
    raise last_exc  # pragma: no cover - loop always returns or raises above


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
    from google.genai import errors, types

    base_kwargs = dict(
        system_instruction=system,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",  # Gemini-native JSON mode, no fence-stripping needed
    )
    # Some (not all - hit this live, "-lite" models reject it as an invalid
    # argument) Gemini models "think" before answering by default, which
    # eats into max_output_tokens and can silently truncate a small budget
    # before any visible output appears (also hit live: 50 tokens came back
    # empty, thinking consumed it all). None of our calls need multi-step
    # reasoning, so disable it where supported; fall back to omitting the
    # param entirely for models (like GEMINI_MODEL's current default,
    # gemini-flash-lite-latest) that don't recognize it - future model
    # swaps shouldn't have to remember this quirk.
    try:
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0), **base_kwargs
        )
        response = _gemini_client().models.generate_content(model=GEMINI_MODEL, contents=user, config=config)
    except errors.ClientError as e:
        if "INVALID_ARGUMENT" not in str(e):
            raise
        config = types.GenerateContentConfig(**base_kwargs)
        response = _gemini_client().models.generate_content(model=GEMINI_MODEL, contents=user, config=config)
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
    model to respond with JSON only. Transient upstream errors (Gemini's
    free-tier "high demand" 503s, Anthropic overload/rate-limit) are
    retried with backoff - anything else (bad request, auth, unsupported
    model) fails immediately since retrying won't fix it."""
    if LLM_PROVIDER == "anthropic":
        text = _with_retry(lambda: _generate_anthropic(system, user, max_tokens))
    else:
        text = _with_retry(lambda: _generate_gemini(system, user, max_tokens))
    return _parse_json(text)
