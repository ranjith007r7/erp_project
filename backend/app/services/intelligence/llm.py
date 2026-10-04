"""
The ONLY file that talks to an LLM provider. Everything else depends on the
tiny LLMClient interface below, which is what lets the whole pipeline be
tested deterministically (a scripted fake model, including one that tries to
write malicious SQL on purpose) without a network call or an API key.

Free-tier reality (Gemini via Google AI Studio, checked Oct 2026): roughly
10-15 requests/minute and a daily cap, shared per Google PROJECT, not per
key. So this client retries politely on 429/5xx with exponential backoff, and
the pipeline keeps calls per question low and reports how many it used.
"""
import time
from typing import Protocol

from app.core.config import settings


class LLMNotConfigured(Exception):
    """No API key configured."""


class LLMError(Exception):
    """The model could not be reached or refused. `reason` is safe to show."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class LLMClient(Protocol):
    calls_used: int

    def generate(self, prompt: str, *, max_tokens: int = 1024) -> str: ...


RETRYABLE_CODES = {429, 500, 502, 503, 504}


def call_with_retry(fn, *, attempts: int = 4, base_delay: float = 1.5, sleep=time.sleep):
    """
    Retries `fn` on rate-limit / transient server errors with exponential
    backoff (1.5s, 3s, 6s). Anything else (bad key, bad request) fails at
    once: retrying a 403 only wastes the free-tier quota.
    `fn` must raise an exception carrying a `.code` int for HTTP-style errors.
    """
    last = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - classified below
            code = getattr(exc, "code", None)
            if code not in RETRYABLE_CODES:
                raise
            last = exc
            if attempt < attempts - 1:
                sleep(base_delay * (2 ** attempt))
    raise last


class GeminiClient:
    def __init__(self, api_key: str, model: str, *, client=None, sleep=time.sleep):
        self.model = model
        self.calls_used = 0
        self._sleep = sleep
        if client is not None:
            self._client = client  # injected in tests
        else:
            from google import genai  # imported lazily so the app boots without the SDK configured
            self._client = genai.Client(api_key=api_key)

    def generate(self, prompt: str, *, max_tokens: int = 1024) -> str:
        from google.genai import types

        config = types.GenerateContentConfig(temperature=0.0, max_output_tokens=max_tokens)

        def _once():
            self.calls_used += 1
            return self._client.models.generate_content(model=self.model, contents=prompt, config=config)

        try:
            response = call_with_retry(_once, sleep=self._sleep)
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None)
            if code == 429:
                raise LLMError(
                    "The free Gemini quota is exhausted for the moment (it allows only a few requests per minute "
                    "and a daily cap). Wait a minute and try again."
                )
            if code in (401, 403):
                raise LLMError("The Gemini API key was rejected. Check GEMINI_API_KEY.")
            if code in RETRYABLE_CODES:
                raise LLMError("The Gemini service is overloaded right now. Please try again shortly.")
            raise LLMError("The language model request failed.")

        text = getattr(response, "text", None)
        if not text or not text.strip():
            raise LLMError("The language model returned no answer (it may have been blocked by a safety filter).")
        return text.strip()


def get_llm_client() -> GeminiClient:
    if not settings.GEMINI_API_KEY:
        raise LLMNotConfigured(
            "The intelligence layer is not configured yet: set GEMINI_API_KEY "
            "(a free key from Google AI Studio)."
        )
    return GeminiClient(settings.GEMINI_API_KEY, settings.GEMINI_MODEL)
