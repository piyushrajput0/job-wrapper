"""Claude client.

Design rules:
  * Every call is optional. If there is no API key, or the user disabled the LLM, callers fall
    back to deterministic logic - the tool never hard-fails because of a missing key.
  * The expensive, stable context (system prompt + profile + master resume) is a cached prefix;
    the volatile part (this job's description) always goes last. Tailoring 40 jobs in a run
    therefore pays for the profile once, not forty times.
  * Structured output is used everywhere a machine reads the result, so responses are validated
    rather than parsed out of prose.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .. import paths
from ..config import LLMConfig
from ..logging_setup import get
from .providers import OpenAICompatibleClient, get_provider

log = get("llm")
T = TypeVar("T", bound=BaseModel)

# $ per million tokens, from the Anthropic pricing table.
PRICING = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


class LLMUnavailable(RuntimeError):
    """Raised when no model call can be made. Callers must degrade, not crash."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    calls: int = 0

    def cost_usd(self, model: str) -> float:
        rate_in, rate_out = PRICING.get(model, (5.00, 25.00))
        # cache reads bill at ~10% of input, cache writes at ~125%
        billed_in = self.input_tokens + self.cache_read_tokens * 0.1 + self.cache_write_tokens * 1.25
        return (billed_in * rate_in + self.output_tokens * rate_out) / 1_000_000


@dataclass
class UsageTracker:
    """Persisted so `jobwrapper status` can show what the run cost."""

    path: Path = field(default_factory=lambda: paths.ensure_layout()["cache"] / "usage.json")
    usage: Usage = field(default_factory=Usage)
    model: str = "claude-opus-5"

    def record(self, response: Any) -> None:
        u = getattr(response, "usage", None)
        if not u:
            return
        self.usage.calls += 1
        self.usage.input_tokens += getattr(u, "input_tokens", 0) or 0
        self.usage.output_tokens += getattr(u, "output_tokens", 0) or 0
        self.usage.cache_read_tokens += getattr(u, "cache_read_input_tokens", 0) or 0
        self.usage.cache_write_tokens += getattr(u, "cache_creation_input_tokens", 0) or 0
        self.flush()

    def flush(self) -> None:
        try:
            existing = json.loads(self.path.read_text()) if self.path.exists() else {}
        except Exception:
            existing = {}
        totals = existing.get("total", {})
        payload = {
            "model": self.model,
            "session": {
                "calls": self.usage.calls,
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "cache_read_tokens": self.usage.cache_read_tokens,
                "cache_write_tokens": self.usage.cache_write_tokens,
                "cost_usd": round(self.usage.cost_usd(self.model), 4),
            },
            "total": {
                "calls": totals.get("calls", 0) + self.usage.calls,
                "cost_usd": round(totals.get("cost_usd", 0) + self.usage.cost_usd(self.model), 4),
            },
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2))

    def summary(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except Exception:
                pass
        return {"session": {"calls": 0, "cost_usd": 0.0}, "total": {"calls": 0, "cost_usd": 0.0}}


class LLMClient:
    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig()
        self.tracker = UsageTracker(model=self.config.model)
        self._client: Any = None
        self._key: str | None = None

    # ------------------------------------------------------------------ availability
    ENV_KEYS = {
        "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY", "groq": "GROQ_API_KEY", "mistral": "MISTRAL_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY", "xai": "XAI_API_KEY",
        "openrouter": "OPENROUTER_API_KEY", "together": "TOGETHER_API_KEY",
    }

    @property
    def provider(self):
        return get_provider(self.config.provider)

    def api_key(self) -> str:
        """Environment first, then the key the user pasted into the UI (encrypted at rest)."""
        if self._key is not None:
            return self._key
        env_name = self.ENV_KEYS.get(self.config.provider, "")
        self._key = os.environ.get(env_name, "") if env_name else ""
        if not self._key:
            try:
                from ..vault import Vault

                self._key = Vault(interactive=False).get_api_key(self.config.provider)
            except Exception as exc:
                log.debug("could not read the API key from the vault: %s", exc)
                self._key = ""
        return self._key

    def forget_key(self) -> None:
        self._key = None
        self._client = None

    def available(self) -> bool:
        if not self.config.enabled:
            return False
        if os.environ.get("JOBWRAPPER_NO_LLM"):
            return False
        if not self.provider.needs_key:          # a local Ollama needs nothing
            return True
        if self.api_key():
            return True
        return self.config.provider == "anthropic" and bool(
            os.environ.get("ANTHROPIC_AUTH_TOKEN")
            or (Path.home() / ".config" / "anthropic").exists())

    def _ensure(self) -> Any:
        if not self.available():
            raise LLMUnavailable(
                f"No API key for {self.provider.label}. Add one in Settings (or set "
                f"{self.ENV_KEYS.get(self.config.provider, 'the provider env var')}); the tool "
                f"uses its deterministic fallbacks until then.")
        if self._client is not None:
            return self._client

        if self.provider.kind == "anthropic":
            import anthropic

            key = self.api_key()
            self._client = (anthropic.Anthropic(api_key=key, timeout=180.0, max_retries=3)
                            if key else anthropic.Anthropic(timeout=180.0, max_retries=3))
        else:
            self._client = OpenAICompatibleClient(self.provider, self.api_key(),
                                                  self.config.model)
        return self._client

    # ------------------------------------------------------------------ calls
    def _system_blocks(self, system: str, cached_context: str | None) -> list[dict[str, Any]]:
        """System prompt first, then the stable context, with the cache breakpoint after it."""
        blocks: list[dict[str, Any]] = [{"type": "text", "text": system}]
        if cached_context:
            block: dict[str, Any] = {"type": "text", "text": cached_context}
            if self.config.cache_prompts:
                block["cache_control"] = {"type": "ephemeral"}
            blocks.append(block)
        elif self.config.cache_prompts:
            blocks[0]["cache_control"] = {"type": "ephemeral"}
        return blocks

    def parse(self, output_model: type[T], *, system: str, prompt: str,
              cached_context: str | None = None, effort: str | None = None,
              max_tokens: int | None = None, model: str | None = None) -> T:
        """Structured call - the result is a validated pydantic model."""
        client = self._ensure()
        if self.provider.kind != "anthropic":
            payload = client.json_object(
                system=f"{system}\n\n{cached_context or ''}".strip(), prompt=prompt,
                schema=output_model.model_json_schema(),
                max_tokens=max_tokens or self.config.max_tokens)
            self._record_openai_usage(client)
            return output_model.model_validate(payload)

        response = client.messages.parse(
            model=model or self.config.model,
            max_tokens=max_tokens or self.config.max_tokens,
            system=self._system_blocks(system, cached_context),
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort or self.config.effort},
            output_format=output_model,
        )
        self.tracker.record(response)
        parsed = response.parsed_output
        if parsed is None:
            raise LLMUnavailable("model returned no parseable structured output")
        return parsed

    def text(self, *, system: str, prompt: str, cached_context: str | None = None,
             effort: str | None = None, max_tokens: int | None = None,
             model: str | None = None) -> str:
        """Free-text call, used for cover letters and essay answers."""
        client = self._ensure()
        if self.provider.kind != "anthropic":
            out = client.text(system=f"{system}\n\n{cached_context or ''}".strip(),
                              prompt=prompt, max_tokens=max_tokens or self.config.max_tokens)
            self._record_openai_usage(client)
            return out

        response = client.messages.create(
            model=model or self.config.model,
            max_tokens=max_tokens or self.config.max_tokens,
            system=self._system_blocks(system, cached_context),
            messages=[{"role": "user", "content": prompt}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort or self.config.effort},
        )
        self.tracker.record(response)
        return "".join(b.text for b in response.content if b.type == "text").strip()

    def _record_openai_usage(self, client: Any) -> None:
        usage = getattr(client, "last_usage", None) or {}
        self.tracker.usage.calls += 1
        self.tracker.usage.input_tokens += int(usage.get("prompt_tokens", 0) or 0)
        self.tracker.usage.output_tokens += int(usage.get("completion_tokens", 0) or 0)
        self.tracker.flush()

    def cost_so_far(self) -> float:
        return self.tracker.usage.cost_usd(self.config.model)
