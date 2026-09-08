"""Model providers.

Two shapes cover the field: Anthropic's own API, and the OpenAI chat-completions API, which
OpenAI, Google (via its compatibility endpoint), Groq, Mistral, DeepSeek, xAI, Together,
OpenRouter and a local Ollama all speak. So there are two adapters, not nine.

Model lists are fetched from the provider at runtime rather than hard-coded here, because a
baked-in list is wrong within months. The static lists are only a fallback for when the key is
missing or the endpoint refuses to enumerate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..logging_setup import get

log = get("llm.providers")


@dataclass
class Provider:
    id: str
    label: str
    kind: str                      # "anthropic" | "openai"
    base_url: str = ""
    key_prefix: str = ""           # a cheap sanity check on pasted keys
    key_url: str = ""              # where the user gets one
    models: list[str] = field(default_factory=list)     # fallback list only
    default_model: str = ""
    needs_key: bool = True
    supports_json_schema: bool = True
    notes: str = ""


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        id="anthropic", label="Anthropic (Claude)", kind="anthropic",
        key_prefix="sk-ant-", key_url="https://console.anthropic.com/settings/keys",
        models=["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
        default_model="claude-sonnet-5",
        notes="Structured output and prompt caching are used natively here.",
    ),
    "openai": Provider(
        id="openai", label="OpenAI", kind="openai",
        base_url="https://api.openai.com/v1", key_prefix="sk-",
        key_url="https://platform.openai.com/api-keys",
        models=["gpt-4o", "gpt-4o-mini", "o3-mini"], default_model="gpt-4o-mini",
    ),
    "google": Provider(
        id="google", label="Google (Gemini)", kind="openai",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        key_url="https://aistudio.google.com/apikey",
        models=["gemini-2.0-flash", "gemini-2.0-pro"], default_model="gemini-2.0-flash",
        notes="Uses Google's OpenAI-compatible endpoint.",
    ),
    "groq": Provider(
        id="groq", label="Groq", kind="openai", base_url="https://api.groq.com/openai/v1",
        key_prefix="gsk_", key_url="https://console.groq.com/keys",
        models=["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        default_model="llama-3.3-70b-versatile",
    ),
    "mistral": Provider(
        id="mistral", label="Mistral", kind="openai", base_url="https://api.mistral.ai/v1",
        key_url="https://console.mistral.ai/api-keys",
        models=["mistral-large-latest", "mistral-small-latest"],
        default_model="mistral-large-latest",
    ),
    "deepseek": Provider(
        id="deepseek", label="DeepSeek", kind="openai", base_url="https://api.deepseek.com/v1",
        key_prefix="sk-", key_url="https://platform.deepseek.com/api_keys",
        models=["deepseek-chat", "deepseek-reasoner"], default_model="deepseek-chat",
    ),
    "xai": Provider(
        id="xai", label="xAI (Grok)", kind="openai", base_url="https://api.x.ai/v1",
        key_prefix="xai-", key_url="https://console.x.ai",
        models=["grok-2-latest"], default_model="grok-2-latest",
    ),
    "openrouter": Provider(
        id="openrouter", label="OpenRouter (any model)", kind="openai",
        base_url="https://openrouter.ai/api/v1", key_prefix="sk-or-",
        key_url="https://openrouter.ai/keys",
        models=["anthropic/claude-sonnet-4.5", "openai/gpt-4o", "meta-llama/llama-3.3-70b-instruct"],
        default_model="anthropic/claude-sonnet-4.5",
        notes="One key, hundreds of models. Model ids look like vendor/model.",
    ),
    "together": Provider(
        id="together", label="Together AI", kind="openai",
        base_url="https://api.together.xyz/v1", key_url="https://api.together.ai/settings/api-keys",
        models=["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
    ),
    "ollama": Provider(
        id="ollama", label="Ollama (local, free)", kind="openai",
        base_url="http://localhost:11434/v1", needs_key=False,
        key_url="https://ollama.com/download",
        models=["llama3.1", "qwen2.5", "mistral"], default_model="llama3.1",
        supports_json_schema=False,
        notes="Runs on your machine. Nothing leaves it, and it costs nothing.",
    ),
}


def get_provider(provider_id: str) -> Provider:
    return PROVIDERS.get(provider_id) or PROVIDERS["anthropic"]


def catalog() -> list[dict[str, Any]]:
    """What the settings page renders."""
    return [
        {"id": p.id, "label": p.label, "kind": p.kind, "needs_key": p.needs_key,
         "key_url": p.key_url, "key_prefix": p.key_prefix, "models": p.models,
         "default_model": p.default_model, "notes": p.notes}
        for p in PROVIDERS.values()
    ]


def looks_like_key(provider_id: str, key: str) -> bool:
    provider = get_provider(provider_id)
    if not provider.needs_key:
        return True
    if not key or len(key) < 12:
        return False
    return key.startswith(provider.key_prefix) if provider.key_prefix else True


def list_models(provider_id: str, api_key: str, timeout: float = 15.0) -> list[str]:
    """Ask the provider what it can run today. Falls back to the static list."""
    provider = get_provider(provider_id)
    try:
        import httpx

        if provider.kind == "anthropic":
            response = httpx.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                timeout=timeout)
            if response.status_code == 200:
                found = [m["id"] for m in response.json().get("data", []) if m.get("id")]
                return found or provider.models
        else:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            response = httpx.get(f"{provider.base_url}/models", headers=headers, timeout=timeout)
            if response.status_code == 200:
                payload = response.json()
                rows = payload.get("data", payload if isinstance(payload, list) else [])
                found = sorted({row.get("id", "") for row in rows if row.get("id")})
                return found or provider.models
        log.debug("%s /models returned %s", provider_id, response.status_code)
    except Exception as exc:
        log.debug("could not list models for %s: %s", provider_id, exc)
    return provider.models


class OpenAICompatibleClient:
    """One adapter for every provider that speaks chat-completions."""

    def __init__(self, provider: Provider, api_key: str, model: str, timeout: float = 180.0):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.last_usage: dict[str, int] = {}

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.provider.id == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/piyushrajput0/job-wrapper"
            headers["X-Title"] = "Job Wrapper"
        return headers

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        response = httpx.post(f"{self.provider.base_url}/chat/completions",
                              headers=self._headers(), json=payload, timeout=self.timeout)
        if response.status_code >= 400:
            raise RuntimeError(f"{self.provider.label} returned {response.status_code}: "
                               f"{response.text[:300]}")
        data = response.json()
        self.last_usage = data.get("usage", {}) or {}
        return data

    @staticmethod
    def _content(data: dict[str, Any]) -> str:
        choices = data.get("choices") or [{}]
        return (choices[0].get("message") or {}).get("content") or ""

    def text(self, system: str, prompt: str, max_tokens: int = 4000) -> str:
        data = self._post({
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        })
        return self._content(data).strip()

    def json_object(self, system: str, prompt: str, schema: dict[str, Any],
                    max_tokens: int = 6000) -> dict[str, Any]:
        """Structured output, degrading as the provider allows."""
        base = {
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": f"{system}\n\nReply with JSON only, matching this schema:\n"
                            f"{json.dumps(schema)}"},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
        }
        attempts: list[dict[str, Any]] = []
        if self.provider.supports_json_schema:
            attempts.append({**base, "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": schema, "strict": False}}})
        attempts.append({**base, "response_format": {"type": "json_object"}})
        attempts.append(base)

        last_error: Exception | None = None
        for payload in attempts:
            try:
                return _loads(self._content(self._post(payload)))
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"{self.provider.label} could not produce JSON: {last_error}")


def _loads(text: str) -> dict[str, Any]:
    """Models wrap JSON in prose or fences more often than they should."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text.strip("`")
        text = text.removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise
