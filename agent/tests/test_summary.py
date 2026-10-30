import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from agent.core.db import MemoryRepository
from agent.core.models import LeadSource, SourceConfig
from agent.summary import build_summary, summary_payload

NOW = datetime(2026, 10, 30, 4, 15, tzinfo=UTC)  # 09:15 in Karachi


def add_lead(
    repo: MemoryRepository, name: str, score: int, *, hours_ago: float, **extra: object
) -> None:
    lead_id = uuid4()
    repo.leads[lead_id] = {
        "company_name": name,
        "domain": f"{name.lower()}.com",
        "fit_score": score,
        "status": "rejected" if score <= 3 else "new",
        "first_source": "job_posting",
        "pain_point": f"{name} needs a React developer",
        "funding_round": None,
        "created_at": NOW - timedelta(hours=hours_ago),
        **extra,
    }
    repo.signals[f"https://jobs.example.com/{name}"] = {
        "lead_id": str(lead_id),
        "title": f"{name} job",
        "source_url": f"https://jobs.example.com/{name}",
        "detected_at": (NOW - timedelta(hours=hours_ago)).isoformat(),
    }


def add_run(
    repo: MemoryRepository, source: str, status: str, *, hours_ago: float, **extra: object
) -> None:
    repo.runs[uuid4()] = {
        "source": source,
        "status": status,
        "started_at": NOW - timedelta(hours=hours_ago),
        "leads_new": 0,
        "errors": [],
        "tokens_used": 0,
        "cost_estimate": "0",
        **extra,
    }


def make_repo() -> MemoryRepository:
    repo = MemoryRepository()
    repo.source_configs = [
        SourceConfig(source=LeadSource.JOB_POSTING, name="default"),
        SourceConfig(source=LeadSource.FUNDING, name="default"),
        SourceConfig(source=LeadSource.SOCIAL, name="default", enabled=False),
    ]
    return repo


def test_counts_only_the_last_24_hours() -> None:
    repo = make_repo()
    for i, score in enumerate([9, 8, 7, 6, 5, 4, 2]):
        add_lead(repo, f"Co{i}", score, hours_ago=i + 1)
    add_lead(repo, "Funded", 8, hours_ago=2, first_source="funding", funding_round="seed")
    add_lead(repo, "Old", 10, hours_ago=30)
    add_run(repo, "job_posting", "success", hours_ago=1.25, leads_new=7, tokens_used=1000,
            cost_estimate="0.25")  # fmt: skip
    add_run(repo, "funding", "partial", hours_ago=0.75, leads_new=1, errors=[{"m": 1}],
            tokens_used=500, cost_estimate="0.10")  # fmt: skip

    summary = build_summary(repo, NOW)

    assert summary.new_by_source == {"job_posting": 7, "funding": 1}
    assert (summary.high_score, summary.rejected) == (3, 1)
    # Top 5 by score, rejects left out, "Old" outside the window.
    assert [lead.company_name for lead in summary.top] == ["Co0", "Co1", "Funded", "Co2", "Co3"]
    assert (summary.tokens, summary.cost) == (1500, Decimal("0.35"))
    health = {h.source: h for h in summary.health}
    assert set(health) == {"job_posting", "funding"}  # disabled social isn't listed
    assert health["funding"].last_status == "partial" and health["funding"].errors == 1
    assert not health["job_posting"].missed


def test_missed_source_is_flagged() -> None:
    repo = make_repo()
    add_run(repo, "job_posting", "success", hours_ago=25.25)  # yesterday's run: fine
    add_run(repo, "funding", "success", hours_ago=27)  # skipped today
    health = {h.source: h for h in build_summary(repo, NOW).health}
    assert not health["job_posting"].missed
    assert health["funding"].missed


def test_payload_for_a_busy_day() -> None:
    repo = make_repo()
    add_lead(repo, "Acme", 9, hours_ago=1, first_source="funding", funding_round="seed")
    add_run(repo, "funding", "success", hours_ago=1, leads_new=1)
    payload = summary_payload(build_summary(repo, NOW))
    body = json.dumps(payload, ensure_ascii=False)
    assert payload["blocks"][0]["text"]["text"] == "Codify Pipeline daily summary, Fri 30 Oct"
    assert "*1 new leads* (funding 1)" in body
    assert "*9/10* <https://jobs.example.com/Acme|Acme> (funding · seed)" in body
    assert ":rotating_light: *job_posting*: no run in the last 26h" in body


def test_payload_for_a_quiet_day_still_says_so() -> None:
    payload = summary_payload(build_summary(make_repo(), NOW), test=True)
    assert payload["text"].startswith("[TEST] Codify Pipeline daily summary")
    assert "No new leads in the last 24h." in payload["text"]
