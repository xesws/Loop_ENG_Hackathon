"""OpenAI-compatible LLM provider registry (stdlib only, no network at import).

Every provider here speaks the same OpenAI `/chat/completions` API — same request
payload, same `Authorization: Bearer` header, same response shape — so the rest of
the codebase stays provider-agnostic. Selecting a provider is one env var:

    LIVE_PROVIDER=openrouter   # default
    LIVE_PROVIDER=akash

The API key comes from the provider's env var (or a generic LLM_API_KEY fallback)
and is never hardcoded or printed. Adding a provider = one row in _PROVIDERS.
"""
from __future__ import annotations

import os
from collections import namedtuple

Provider = namedtuple("Provider", "name url key_env api_key default_model")

# name -> (chat/completions URL, api-key env var, default model)
_PROVIDERS = {
    # OpenRouter — the incumbent. Model ids look like "openai/gpt-4o-mini".
    "openrouter": (
        "https://openrouter.ai/api/v1/chat/completions",
        "OPENROUTER_API_KEY",
        "openai/gpt-4o-mini",
    ),
    # Akash Network's AkashChat API — decentralized GPU marketplace, OpenAI-compatible.
    # Model ids look like "Meta-Llama-3-1-8B-Instruct-FP8"; list at chatapi.akash.network.
    # Override with LIVE_MODEL if the default id is retired.
    "akash": (
        "https://chatapi.akash.network/api/v1/chat/completions",
        "AKASH_API_KEY",
        "Meta-Llama-3-1-8B-Instruct-FP8",
    ),
}


def resolve() -> Provider:
    """Resolve the selected provider from env. Reads env only — no network.

    api_key may be None; callers raise their own "unset" error so the graceful
    live->cached/mock fallback path stays exactly where it is.
    """
    name = (os.environ.get("LIVE_PROVIDER") or "openrouter").strip().lower()
    if name not in _PROVIDERS:
        known = ", ".join(sorted(_PROVIDERS))
        raise RuntimeError(f"unknown LIVE_PROVIDER {name!r}; known: {known}")
    url, key_env, default_model = _PROVIDERS[name]
    api_key = os.environ.get(key_env) or os.environ.get("LLM_API_KEY")
    return Provider(name, url, key_env, api_key, default_model)
