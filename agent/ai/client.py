"""Claude API access: one client, per-task model settings, structured JSON
output validated with pydantic, and token + cost accounting per call."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from agent.core.config import Settings
from agent.core.errors import FatalRunError

log = logging.getLogger(__name__)

# Explicit on purpose: Claude Code cloud sessions set ANTHROPIC_BASE_URL for
# Claude Code's own traffic, and the SDK would otherwise pick it up.
API_BASE_URL = "https://api.anthropic.com"
OPUS = "claude-opus-5-5"
HAIKU = "claude-haiku-5-5"
# Re-runs a safety-classifier decline on Anthropic's recommended model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class TaskSpec:
    model: str
    effort: str
    max_tokens: int
    fallbacks: bool  # Haiku has no server-side fallback


# Cheap model for extraction, the stronger one for judgment and writing (CLAUDE.md §6).
TASKS = {
    "extract": TaskSpec(HAIKU, "low", 8000, fallbacks=False),
    "funding_extract": TaskSpec(HAIKU, "low", 8000, fallbacks=False),
    "score": TaskSpec(OPUS, "medium", 16000, fallbacks=True),
    "draft": TaskSpec(OPUS, "medium", 16000, fallbacks=True),
}


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: Decimal
    output: Decimal
    cache_write: Decimal
    cache_read: Decimal


def _price(input_: str, output: str, cache_read: str) -> Price:
    base = Decimal(input_)
    return Price(base, Decimal(output), base * Decimal("1.25"), Decimal(cache_read))


PRICES = {
    OPUS: _price("4", "20", "0.20"),
    HAIKU: _price("0.10", "0.50", "0.01"),
    # Server-side fallback targets for Opus 5.5 declines.
    "claude-opus-5": _price("5", "25", "0.50"),
    "claude-opus-4-8": _price("5", "25", "0.50"),
}


@dataclass(frozen=True)
class Usage:
    tokens: int = 0
    cost: Decimal = Decimal("0")

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.tokens + other.tokens, self.cost + other.cost)


def usage_of(response: Any, fallback_model: str) -> Usage:
    u = response.usage
    counts = {
        "input": u.input_tokens or 0,
        "output": u.output_tokens or 0,
        "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
    }
    price = PRICES.get(response.model) or PRICES[fallback_model]
    cost = sum(
        (Decimal(n) * getattr(price, kind) for kind, n in counts.items()), Decimal("0")
    ) / Decimal(1_000_000)
    return Usage(sum(counts.values()), cost)


class AIError(Exception):
    """One AI call failed for this item (refusal, invalid output, API error).
    Carries the tokens already spent so the run can still account for them."""

    def __init__(self, message: str, usage: Usage | None = None) -> None:
        super().__init__(message)
        self.usage = usage or Usage()


class AIConfigError(FatalRunError):
    """Bad key, no access or unknown model: every call would fail, so stop the run."""


class AIClient(Protocol):
    def structured(
        self, task: str, *, system: str, user: str, output: type[T]
    ) -> tuple[T, Usage]: ...


class ClaudeAI:
    def __init__(self, client: anthropic.Anthropic) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, settings: Settings, **client_kwargs: Any) -> "ClaudeAI":
        settings.require("anthropic_api_key", scope="AI scoring")
        assert settings.anthropic_api_key
        return cls(
            anthropic.Anthropic(
                api_key=settings.anthropic_api_key.get_secret_value(),
                base_url=API_BASE_URL,
                max_retries=3,
                **client_kwargs,
            )
        )

    def structured(self, task: str, *, system: str, user: str, output: type[T]) -> tuple[T, Usage]:
        """One request with JSON output matching `output`. An answer that fails
        validation is retried once, with the validation error in the prompt."""
        spec = TASKS[task]
        spent = Usage()
        problem: str | None = None
        for _ in range(2):
            content = user if problem is None else f"{user}\n\n{_retry_note(problem)}"
            response = self._create(spec, system, content, output)
            spent += usage_of(response, spec.model)
            try:
                return _parse(response, output), spent
            except _InvalidOutput as exc:
                problem = str(exc)
                log.warning("%s: invalid output, retrying once: %s", task, problem)
            except AIError as exc:
                raise AIError(f"{task}: {exc}", spent) from None
        raise AIError(f"{task}: invalid output after retry: {problem}", spent)

    def _create(self, spec: TaskSpec, system: str, user: str, output: type[BaseModel]) -> Any:
        kwargs: dict[str, Any] = {
            "model": spec.model,
            "max_tokens": spec.max_tokens,
            # Caches the fixed system prompt across a run's calls.
            "cache_control": {"type": "ephemeral"},
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "effort": spec.effort,
                "format": {"type": "json_schema", "schema": anthropic.transform_schema(output)},
            },
        }
        if spec.fallbacks:
            kwargs.update(fallbacks="default", betas=[FALLBACK_BETA])
        try:
            return self._client.beta.messages.create(**kwargs)
        except (
            anthropic.AuthenticationError,
            anthropic.PermissionDeniedError,
            anthropic.NotFoundError,
        ) as exc:
            raise AIConfigError(f"Claude API rejected the request: {exc}") from exc
        except anthropic.APIError as exc:
            # The SDK already retried 408/409/429/5xx and connection errors.
            raise AIError(f"Claude API error: {type(exc).__name__}: {exc}") from exc


class _InvalidOutput(Exception):
    pass


def _retry_note(problem: str) -> str:
    return f"Your previous answer was rejected by validation: {problem}\nAnswer again and fix that."


def _parse[M: BaseModel](response: Any, output: type[M]) -> M:
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None)
        raise AIError(f"model declined (category: {category})")
    if response.stop_reason == "max_tokens":
        raise AIError("response hit max_tokens")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise AIError(f"no text in response (stop_reason: {response.stop_reason})")
    try:
        return output.model_validate_json(text)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'output'}: {e['msg']}" for e in exc.errors()
        )
        raise _InvalidOutput(problems) from None
