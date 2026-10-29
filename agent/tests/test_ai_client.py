"""ClaudeAI against a mock HTTP transport returning saved-shape API responses."""

import json
from decimal import Decimal
from typing import Any

import anthropic
import httpx2
import pytest

from agent.ai.client import API_BASE_URL, FALLBACK_BETA, AIConfigError, AIError, ClaudeAI
from agent.ai.schemas import Assessment, Extraction
from agent.core.config import Settings
from agent.core.errors import MissingConfigError

GOOD_SCORE = {
    "fit_score": 8,
    "score_reason": "Funded startup hiring on contract.",
    "service_fit": ["mvp"],
    "pain_point": "hiring a React developer for 3 months",
}
GOOD_EXTRACT = {
    "industry": "saas",
    "country": None,
    "city": None,
    "company_size": None,
    "description": None,
    "tech_stack": ["react"],
    "people": [],
}


def message(
    content: Any = None,
    *,
    model: str = "claude-opus-5-5",
    stop_reason: str = "end_turn",
    usage: dict[str, int] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content)
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [] if content is None else [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage
        or {
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 2000,
        },
        **extra,
    }


class Recorder:
    def __init__(self, *responses: httpx2.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.responses.pop(0)

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def ai_with(*responses: dict[str, Any] | httpx2.Response) -> tuple[ClaudeAI, Recorder]:
    recorder = Recorder(
        *(r if isinstance(r, httpx2.Response) else httpx2.Response(200, json=r) for r in responses)
    )
    settings = Settings(_env_file=None, anthropic_api_key="sk-test")
    http = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(recorder))
    return ClaudeAI.from_settings(settings, http_client=http), recorder


def test_scores_with_opus_fallbacks_and_cost() -> None:
    ai, recorder = ai_with(message(GOOD_SCORE))
    parsed, usage = ai.structured("score", system="rubric", user="lead", output=Assessment)

    assert parsed.fit_score == 8
    # 1000 in x $4 + 500 out x $20 + 2000 cache reads x $0.20, per million tokens.
    assert usage.tokens == 3500
    assert usage.cost == Decimal("0.0144")

    (request,) = recorder.requests
    assert str(request.url) == f"{API_BASE_URL}/v1/messages"
    assert FALLBACK_BETA in request.headers["anthropic-beta"]
    body = recorder.body()
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["system"] == "rubric"
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["additionalProperties"] is False


def test_extract_uses_haiku_without_fallbacks() -> None:
    ai, recorder = ai_with(message(GOOD_EXTRACT, model="claude-haiku-5-5"))
    parsed, _ = ai.structured("extract", system="s", user="u", output=Extraction)
    assert parsed.tech_stack == ["react"]
    body = recorder.body()
    assert body["model"] == "claude-haiku-5-5"
    assert "fallbacks" not in body
    assert FALLBACK_BETA not in recorder.requests[0].headers.get("anthropic-beta", "")


def test_ignores_anthropic_base_url_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://claude-code-proxy.invalid")
    ai, recorder = ai_with(message(GOOD_SCORE))
    ai.structured("score", system="s", user="u", output=Assessment)
    assert recorder.requests[0].url.host == "api.anthropic.com"


def test_invalid_output_is_retried_once_with_the_problem() -> None:
    ai, recorder = ai_with(message({**GOOD_SCORE, "fit_score": 12}), message(GOOD_SCORE))
    parsed, usage = ai.structured("score", system="s", user="lead", output=Assessment)
    assert parsed.fit_score == 8
    assert usage.tokens == 7000  # both calls are counted
    retry_prompt = recorder.body(1)["messages"][0]["content"]
    assert retry_prompt.startswith("lead\n\n")
    assert "fit_score" in retry_prompt and "rejected by validation" in retry_prompt


def test_invalid_output_twice_fails_with_usage() -> None:
    ai, _ = ai_with(message("not json"), message({"fit_score": 5}))
    with pytest.raises(AIError, match="invalid output after retry") as exc:
        ai.structured("score", system="s", user="u", output=Assessment)
    assert exc.value.usage.tokens == 7000


def test_refusal_is_an_item_error() -> None:
    refusal = message(
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": "declined"},
    )
    ai, recorder = ai_with(refusal)
    with pytest.raises(AIError, match=r"declined.*cyber") as exc:
        ai.structured("score", system="s", user="u", output=Assessment)
    assert exc.value.usage.tokens == 3500
    assert len(recorder.requests) == 1  # a refusal is not retried


def test_max_tokens_is_an_item_error() -> None:
    ai, _ = ai_with(message('{"fit_score": 8, "score_re', stop_reason="max_tokens"))
    with pytest.raises(AIError, match="max_tokens"):
        ai.structured("score", system="s", user="u", output=Assessment)


def test_bad_key_stops_the_run() -> None:
    error = {
        "type": "error",
        "error": {"type": "authentication_error", "message": "invalid x-api-key"},
    }
    ai, _ = ai_with(httpx2.Response(401, json=error))
    with pytest.raises(AIConfigError, match="rejected"):
        ai.structured("score", system="s", user="u", output=Assessment)


def test_bad_request_is_an_item_error() -> None:
    error = {"type": "error", "error": {"type": "invalid_request_error", "message": "too long"}}
    ai, _ = ai_with(httpx2.Response(400, json=error))
    with pytest.raises(AIError, match="BadRequestError"):
        ai.structured("score", system="s", user="u", output=Assessment)


def test_missing_key_names_both_env_vars() -> None:
    with pytest.raises(MissingConfigError, match="CODIFY_ANTHROPIC_API_KEY"):
        ClaudeAI.from_settings(Settings(_env_file=None))
