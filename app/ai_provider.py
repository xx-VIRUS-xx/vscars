"""
Provider-agnostic AI chat layer.

Supports:
- anthropic: native Anthropic SDK (claude-* models)
- openai: OpenAI API (gpt-* models)
- groq: Groq API (OpenAI-compatible)
- together: Together AI (OpenAI-compatible)
- ollama: local Ollama (OpenAI-compatible, base_url required)
- custom: any OpenAI-compatible endpoint (base_url + api_key)
"""
import os
from typing import Optional

PROVIDER_DEFAULTS = {
    "anthropic": {
        "model": "claude-haiku-4-5-20251001",
        "base_url": None,
    },
    "openai": {
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
    },
    "groq": {
        "model": "llama-3.1-8b-instant",
        "base_url": "https://api.groq.com/openai/v1",
    },
    "together": {
        "model": "mistralai/Mixtral-8x7B-Instruct-v0.1",
        "base_url": "https://api.together.xyz/v1",
    },
    "ollama": {
        "model": "llama3",
        "base_url": "http://localhost:11434/v1",
    },
    "custom": {
        "model": "gpt-3.5-turbo",
        "base_url": None,
    },
}


def get_ai_config(db, user_id: int) -> Optional[object]:
    """Return the UserAIConfig for a user, or None if not configured."""
    from app.database import UserAIConfig
    return db.query(UserAIConfig).filter(UserAIConfig.user_id == user_id).first()


def has_ai_configured(db, user_id: int) -> bool:
    """Return True if the user has an AI provider configured with a key."""
    cfg = get_ai_config(db, user_id)
    if not cfg or not cfg.api_key:
        # Also check server-level env vars as fallback
        if os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"):
            return True
        return False
    return True


def chat(db, user_id: int, messages: list, system: str = "") -> str:
    """
    Send a chat completion request using the user's configured provider.
    messages: list of {"role": "user"|"assistant", "content": str}
    Returns the assistant's reply as a string.
    Raises ValueError if no provider is configured.
    """
    from app.database import UserAIConfig

    cfg = get_ai_config(db, user_id)

    # Resolve provider, key, model, base_url
    if cfg and cfg.api_key:
        provider = cfg.provider or "anthropic"
        api_key = cfg.api_key
        model = cfg.model or PROVIDER_DEFAULTS.get(provider, {}).get("model", "gpt-3.5-turbo")
        base_url = cfg.base_url or PROVIDER_DEFAULTS.get(provider, {}).get("base_url")
    else:
        # Fall back to server env vars
        if os.getenv("ANTHROPIC_API_KEY"):
            provider = "anthropic"
            api_key = os.getenv("ANTHROPIC_API_KEY")
            model = "claude-haiku-4-5-20251001"
            base_url = None
        elif os.getenv("OPENAI_API_KEY"):
            provider = "openai"
            api_key = os.getenv("OPENAI_API_KEY")
            model = "gpt-4o-mini"
            base_url = "https://api.openai.com/v1"
        else:
            raise ValueError(
                "No AI provider configured. Go to Settings → AI Keys to add your API key."
            )

    if provider == "anthropic":
        return _chat_anthropic(api_key, model, messages, system)
    else:
        return _chat_openai_compat(api_key, model, base_url, messages, system)


def _chat_anthropic(api_key: str, model: str, messages: list, system: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise ValueError("anthropic package not installed. Run: pip install anthropic")

    client = anthropic.Anthropic(api_key=api_key)
    kwargs = {
        "model": model,
        "max_tokens": 4096,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system

    resp = client.messages.create(**kwargs)
    return resp.content[0].text


def _chat_openai_compat(api_key: str, model: str, base_url: Optional[str], messages: list, system: str) -> str:
    try:
        import openai
    except ImportError:
        raise ValueError("openai package not installed. Run: pip install openai")

    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url

    client = openai.OpenAI(**kwargs)

    all_messages = []
    if system:
        all_messages.append({"role": "system", "content": system})
    all_messages.extend(messages)

    resp = client.chat.completions.create(
        model=model,
        messages=all_messages,
        max_tokens=4096,
    )
    return resp.choices[0].message.content
