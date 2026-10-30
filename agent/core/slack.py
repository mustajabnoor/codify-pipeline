"""Slack alerts through an Incoming Webhook: run failures and the daily summary.

Posting never raises. An alert must not break the run it reports on, and a
missing webhook only means alerts are off."""

import logging
import os
from typing import Any

import httpx

from agent.core.config import Settings
from agent.core.http import http_client, request_with_retry
from agent.core.models import RunError, RunStats
from agent.core.text import truncate

log = logging.getLogger(__name__)

MAX_ERRORS_SHOWN = 5
ERROR_CHARS = 200
STATUS_EMOJI = {"success": ":white_check_mark:", "partial": ":warning:", "failed": ":x:"}

Payload = dict[str, Any]


def actions_run_url() -> str | None:
    """Link to the GitHub Actions run, when running inside one."""
    server, repo, run_id = (
        os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")
    )
    return f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else None


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _error_line(error: RunError) -> str:
    where = error.context.get("source_url") or error.context.get("url") or error.context.get("feed")
    line = truncate(error.message.replace("\n", " "), ERROR_CHARS)
    return f"• {line}" + (f" (<{where}|link>)" if where else "")


def run_alert(source: str, status: str, stats: RunStats, *, test: bool = False) -> Payload:
    """Message for a failed or partial run."""
    emoji = STATUS_EMOJI.get(status, ":grey_question:")
    prefix = "[TEST] " if test else ""
    headline = f"{prefix}{emoji} *{source}* run {status}"
    counts = (
        f"seen {stats.items_seen} · new {stats.leads_new} · updated {stats.leads_updated} "
        f"· skipped {stats.leads_skipped} · errors {len(stats.errors)} "
        f"· ${stats.cost_estimate:.2f}"
    )
    lines = [_error_line(e) for e in stats.errors[:MAX_ERRORS_SHOWN]]
    if len(stats.errors) > MAX_ERRORS_SHOWN:
        lines.append(f"…and {len(stats.errors) - MAX_ERRORS_SHOWN} more (see agent_runs.errors)")
    blocks = [_section(f"{headline}\n{counts}")]
    if lines:
        blocks.append(_section("\n".join(lines)))
    if url := actions_run_url():
        blocks.append(
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{url}|Actions run>"}]}
        )
    return {"text": f"{prefix}{source} run {status}", "blocks": blocks}


class SlackNotifier:
    def __init__(
        self, webhook_url: str | None, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.webhook_url = webhook_url
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings) -> "SlackNotifier":
        url = settings.slack_webhook_url
        return cls(url.get_secret_value() if url else None)

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url and self.webhook_url.strip())

    def post(self, payload: Payload) -> bool:
        """True when Slack accepted the message."""
        if not self.enabled:
            log.warning("Slack not configured (SLACK_WEBHOOK_URL); message not sent")
            return False
        assert self.webhook_url
        try:
            with http_client(self._transport) as client:
                request_with_retry(
                    client, "POST", self.webhook_url, json=payload, label="Slack webhook"
                )
        except httpx.HTTPError as exc:
            # The webhook URL is a secret; log the error type only.
            log.warning("Slack post failed: %s", type(exc).__name__)
            return False
        return True

    def run_finished(self, source: str, status: str, stats: RunStats) -> None:
        """Called after every real run; only failed or partial runs alert."""
        if status in ("failed", "partial"):
            self.post(run_alert(source, status, stats))
