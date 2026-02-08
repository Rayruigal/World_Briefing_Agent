"""Shared LLM client – supports OpenAI and Azure OpenAI.

Provider is selected automatically based on environment variables:
  - If AZURE_OPENAI_ENDPOINT is set → Azure OpenAI
  - Otherwise                       → Standard OpenAI (or any compatible API)

Per-task model selection:
  CLASSIFY_MODEL   – model/deployment for classification  (default: gpt-4o-mini)
  SUMMARIZE_MODEL  – model/deployment for summarisation   (default: AZURE_OPENAI_DEPLOYMENT / LLM_MODEL)

Environment variables:
  Standard OpenAI / compatible:
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

  Azure OpenAI:
    AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT
"""

from __future__ import annotations

import logging
import os
from typing import Any

from openai import AzureOpenAI, OpenAI

log = logging.getLogger(__name__)

_client: OpenAI | AzureOpenAI | None = None


def _is_azure() -> bool:
    return bool(os.getenv("AZURE_OPENAI_ENDPOINT"))


def get_client() -> OpenAI | AzureOpenAI:
    """Return a singleton LLM client (Azure or standard OpenAI)."""
    global _client
    if _client is not None:
        return _client

    if _is_azure():
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        api_key = os.environ["AZURE_OPENAI_API_KEY"]
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        _client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        log.info("LLM provider: Azure OpenAI (%s)", endpoint)
    else:
        api_key = os.environ["LLM_API_KEY"]
        base_url = os.getenv("LLM_BASE_URL")
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        _client = OpenAI(**kwargs)
        log.info("LLM provider: OpenAI-compatible (%s)", base_url or "https://api.openai.com")

    return _client


# ── Per-task model selection ─────────────────────────────────────────

def _default_model() -> str:
    """Global fallback model / deployment name."""
    if _is_azure():
        return os.getenv("AZURE_OPENAI_DEPLOYMENT") or os.getenv("LLM_MODEL", "gpt-4o-mini")
    return os.getenv("LLM_MODEL", "gpt-4o-mini")


def get_model(task: str | None = None) -> str:
    """Return the model for a given task.

    Task-specific env vars (override the default):
      task="classify"   → CLASSIFY_MODEL
      task="summarize"  → SUMMARIZE_MODEL

    Falls back to AZURE_OPENAI_DEPLOYMENT / LLM_MODEL.
    """
    if task == "classify":
        m = os.getenv("CLASSIFY_MODEL")
        if m:
            return m
    elif task == "summarize":
        m = os.getenv("SUMMARIZE_MODEL")
        if m:
            return m
    return _default_model()


# ── Reasoning-model detection ───────────────────────────────────────
# These models do NOT support `temperature` or `max_tokens`; they require
# `max_completion_tokens` and temperature must be omitted (defaults to 1).
_REASONING_MODEL_PREFIXES = ("o1", "o3", "gpt-5")


def is_reasoning_model(model: str | None = None) -> bool:
    """Return True if the model is a reasoning model (o1/o3/gpt-5)."""
    model = model or _default_model()
    return any(model.lower().startswith(p) for p in _REASONING_MODEL_PREFIXES)


_REASONING_TOKEN_MULTIPLIER = 5  # reasoning models need ~5× more tokens for thinking


def chat_completion_kwargs(
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Build model-aware kwargs for chat.completions.create().

    - For reasoning models (o1, o3, gpt-5): drops temperature, scales up
      max_completion_tokens to account for internal reasoning tokens.
    - For standard models: uses temperature and max_completion_tokens as-is.
    """
    kwargs: dict[str, Any] = {}
    reasoning = is_reasoning_model(model)

    if not reasoning and temperature is not None:
        kwargs["temperature"] = temperature

    if max_tokens is not None:
        if reasoning:
            kwargs["max_completion_tokens"] = max_tokens * _REASONING_TOKEN_MULTIPLIER
        else:
            kwargs["max_completion_tokens"] = max_tokens

    return kwargs
