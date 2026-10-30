"""Daily Slack summary: new leads, the best of them, and how each source ran."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from agent.core.db import LeadDigest, ReportReader, RunDigest
from agent.core.slack import STATUS_EMOJI, Payload, actions_run_url
from agent.core.text import truncate

TEAM_TZ = ZoneInfo("Asia/Karachi")
WINDOW = timedelta(hours=24)
# A daily source with no run in this long missed its schedule.
MISSED_AFTER = timedelta(hours=26)
HIGH_SCORE = 8
TOP_LEADS = 5


@dataclass(frozen=True)
class SourceHealth:
    source: str
    last_status: str | None  # None: no run in the window
    runs: int
    leads_new: int
    errors: int
    missed: bool


@dataclass
class DailySummary:
    since: datetime
    until: datetime
    new_by_source: dict[str, int] = field(default_factory=dict)
    high_score: int = 0
    rejected: int = 0
    top: list[LeadDigest] = field(default_factory=list)
    health: list[SourceHealth] = field(default_factory=list)
    tokens: int = 0
    cost: Decimal = Decimal("0")
    followups_due: int = 0

    @property
    def total_new(self) -> int:
        return sum(self.new_by_source.values())


def _health(source: str, runs: list[RunDigest], now: datetime) -> SourceHealth:
    mine = sorted((r for r in runs if r.source == source), key=lambda r: r.started_at)
    last = mine[-1] if mine else None
    return SourceHealth(
        source=source,
        last_status=last.status if last else None,
        runs=len(mine),
        leads_new=sum(r.leads_new for r in mine),
        errors=sum(r.errors for r in mine),
        missed=last is None or now - last.started_at > MISSED_AFTER,
    )


def build_summary(reader: ReportReader, now: datetime) -> DailySummary:
    since = now - WINDOW
    leads = reader.recent_leads(since)
    # Look back far enough to tell "missed" from "ran yesterday morning".
    runs = reader.recent_runs(now - MISSED_AFTER)
    summary = DailySummary(since=since, until=now)
    for lead in leads:
        summary.new_by_source[lead.first_source] = (
            summary.new_by_source.get(lead.first_source, 0) + 1
        )
    summary.high_score = sum(1 for lead in leads if (lead.fit_score or 0) >= HIGH_SCORE)
    summary.rejected = sum(1 for lead in leads if lead.status == "rejected")
    summary.top = sorted(
        (lead for lead in leads if lead.status != "rejected" and lead.fit_score),
        key=lambda lead: (-(lead.fit_score or 0), lead.created_at),
    )[:TOP_LEADS]
    sources = sorted(set(reader.enabled_sources()) | {r.source for r in runs})
    summary.health = [_health(s, runs, now) for s in sources]
    in_window = [r for r in runs if r.started_at >= since]
    summary.tokens = sum(r.tokens_used for r in in_window)
    summary.cost = sum((r.cost_estimate for r in in_window), Decimal("0"))
    summary.followups_due = reader.followups_due_count()
    return summary


def _lead_line(lead: LeadDigest) -> str:
    name = f"<{lead.signal_url}|{lead.company_name}>" if lead.signal_url else lead.company_name
    detail = lead.pain_point or lead.signal_title or ""
    round_ = f" · {lead.funding_round}" if lead.funding_round else ""
    return f"*{lead.fit_score}/10* {name} ({lead.first_source}{round_}): {truncate(detail, 140)}"


def _health_line(h: SourceHealth) -> str:
    if h.missed:
        return f":rotating_light: *{h.source}*: no run in the last 26h"
    emoji = STATUS_EMOJI.get(h.last_status or "", ":grey_question:")
    errors = f", {h.errors} errors" if h.errors else ""
    return f"{emoji} *{h.source}*: {h.last_status}, {h.leads_new} new{errors}"


def summary_payload(summary: DailySummary, *, test: bool = False) -> Payload:
    day = summary.until.astimezone(TEAM_TZ).strftime("%a %d %b")
    prefix = "[TEST] " if test else ""
    title = f"{prefix}Codify Pipeline daily summary, {day}"
    if summary.total_new:
        per_source = ", ".join(f"{s} {n}" for s, n in sorted(summary.new_by_source.items()))
        overview = (
            f"*{summary.total_new} new leads* ({per_source}) · "
            f"*{summary.high_score}* scored 8+ · {summary.rejected} auto-rejected"
        )
    else:
        overview = "No new leads in the last 24h."
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": title}},
        {"type": "section", "text": {"type": "mrkdwn", "text": overview}},
    ]
    if summary.top:
        lines = "\n".join(_lead_line(lead) for lead in summary.top)
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Top new leads*\n{lines}"}}
        )
    health = "\n".join(_health_line(h) for h in summary.health) or "No sources enabled."
    footer = (
        f"Follow-ups due: {summary.followups_due} · "
        f"AI cost (24h): ${summary.cost:.2f} ({summary.tokens:,} tokens)"
    )
    if url := actions_run_url():
        footer += f" · <{url}|Actions run>"
    blocks += [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Agent health*\n{health}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": footer}]},
    ]
    return {"text": f"{title}: {overview}", "blocks": blocks}
