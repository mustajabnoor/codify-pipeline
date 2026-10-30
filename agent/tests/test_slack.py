import json
import logging
from decimal import Decimal

import httpx
import pytest

from agent.core.models import RunError, RunStats
from agent.core.slack import SlackNotifier, actions_run_url, run_alert

WEBHOOK = "https://hooks.slack.com/services/T000/B000/secret-token"


def stats(errors: int = 0) -> RunStats:
    return RunStats(
        items_seen=15,
        leads_new=12,
        leads_updated=3,
        cost_estimate=Decimal("0.3121"),
        errors=[
            RunError(
                message=f"feed failed: HTTPStatusError {i} " + "x" * 300,
                context={"feed": f"https://f{i}.example.com/rss"},
            )
            for i in range(errors)
        ],
    )


def text_of(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_run_alert_lists_first_errors_with_links() -> None:
    payload = run_alert("job_posting", "partial", stats(errors=7))
    body = text_of(payload)
    assert payload["text"] == "job_posting run partial"
    assert "seen 15 · new 12 · updated 3" in body and "$0.31" in body
    assert body.count("feed failed") == 5  # first 5 only
    assert "…and 2 more" in body
    assert "<https://f0.example.com/rss|link>" in body
    assert "x" * 250 not in body  # long errors are truncated


def test_actions_link_only_inside_github_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    assert actions_run_url() is None
    assert "Actions run" not in text_of(run_alert("funding", "failed", stats()))
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "mustajabnoor/codify-pipeline")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    url = "https://github.com/mustajabnoor/codify-pipeline/actions/runs/42"
    assert actions_run_url() == url
    assert url in text_of(run_alert("funding", "failed", stats()))


def test_test_messages_are_labelled() -> None:
    assert run_alert("funding", "failed", stats(), test=True)["text"].startswith("[TEST] ")


class Webhook:
    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return httpx.Response(self.statuses.pop(0), text="ok")


def test_post_sends_json_to_the_webhook() -> None:
    hook = Webhook(200)
    assert SlackNotifier(WEBHOOK, httpx.MockTransport(hook)).post({"text": "hi"})
    assert hook.bodies == [{"text": "hi"}]


def test_missing_webhook_skips_quietly(caplog: pytest.LogCaptureFixture) -> None:
    assert not SlackNotifier(None).post({"text": "hi"})
    assert not SlackNotifier("  ").enabled
    assert "Slack not configured" in caplog.text


def test_slack_errors_are_logged_never_raised_or_leaked(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    hook = Webhook(500, 500, 500)
    with caplog.at_level(logging.WARNING):
        assert not SlackNotifier(WEBHOOK, httpx.MockTransport(hook)).post({"text": "hi"})
    assert len(hook.bodies) == 3  # retried, then gave up
    assert "Slack post failed: HTTPStatusError" in caplog.text
    assert "secret-token" not in caplog.text  # the webhook URL is a secret


def test_only_failed_and_partial_runs_alert() -> None:
    hook = Webhook(200, 200)
    notifier = SlackNotifier(WEBHOOK, httpx.MockTransport(hook))
    for status in ("success", "partial", "failed"):
        notifier.run_finished("job_posting", status, stats())
    assert [b["text"] for b in hook.bodies] == ["job_posting run partial", "job_posting run failed"]
