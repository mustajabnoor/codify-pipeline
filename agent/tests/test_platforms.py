"""Source platforms (per-board switches and run status) and the Claude AI
switch, including scoring leads that were saved while AI was off."""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent import main as cli
from agent.ai.client import AIError
from agent.core.config import Settings
from agent.core.db import MemoryRepository, PlatformRow, expected_sources
from agent.core.models import LeadCandidate, LeadSource, RunStatus, SourceConfig
from agent.core.platforms import PLATFORM_HOSTS, PlatformRun, platform_for_url
from agent.sources.job_posts import REMOTEOK_API, JobPostingsSource
from agent.sources.registry import SOURCES
from agent.summary import build_summary, summary_payload

from .conftest import FakeAI, make_candidate
from .test_job_posts import REMOTEOK_JSON, WWR_FEED, WWR_RSS, config, mock_transport
from .test_job_posts import feeds as feeds  # fixture

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
# ('key', 'source', 'Name', available, enabled, needs_ai, sort_order)
_ROW = re.compile(r"\('([a-z0-9_]+)',\s*'([a-z_]+)',\s*'[^']+',\s*(true|false),")


def migration_platforms() -> dict[str, tuple[str, bool]]:
    (path,) = MIGRATIONS.glob("*_source_platforms.sql")
    return {key: (source, avail == "true") for key, source, avail in _ROW.findall(path.read_text())}


def test_platform_for_url() -> None:
    assert platform_for_url("https://remoteok.com/api") == "remoteok"
    assert platform_for_url("https://www.eu-startups.com/feed/") == "eu_startups"
    assert platform_for_url("https://news.crunchbase.com/feed/") == "crunchbase_news"
    assert platform_for_url("https://WeWorkRemotely.com/categories/x.rss") == "weworkremotely"
    assert platform_for_url("https://crunchbase.com/feed/") is None
    assert platform_for_url("https://feeds.example.com/x.rss") is None


def test_code_and_migration_agree() -> None:
    rows = migration_platforms()
    assert len(rows) == 19
    assert set(PLATFORM_HOSTS.values()) <= set(rows)
    collected = {key: cls.name for cls in SOURCES.values() for key in cls.platforms}
    # Exactly the platforms a collector reads are marked available, under its source.
    assert {key for key, (_, available) in rows.items() if available} == set(collected)
    for key, source in collected.items():
        assert rows[key][0] == source


@pytest.mark.parametrize(
    ("run", "status"),
    [
        (PlatformRun("a", fetched=True), RunStatus.SUCCESS),
        (PlatformRun("a"), RunStatus.SUCCESS),  # on, but no feed configured for it
        (PlatformRun("a", fetched=True, errors=["bad item"]), RunStatus.PARTIAL),
        (PlatformRun("a", errors=["feed failed"]), RunStatus.FAILED),
        (PlatformRun("a", fetched=True, fatal="AIConfigError"), RunStatus.FAILED),
    ],
)
def test_platform_run_status(run: PlatformRun, status: RunStatus) -> None:
    assert run.status is status


def test_platform_run_error_is_trimmed() -> None:
    assert PlatformRun("a", errors=["x" * 900, "y"]).error == "x" * 500


def job_repo(**switches: bool) -> MemoryRepository:
    repo = MemoryRepository()
    repo.source_configs = [
        SourceConfig(
            source=LeadSource.JOB_POSTING, name="default", config=config(rss_feeds=[WWR_FEED])
        )
    ]
    repo.platforms = [PlatformRow(k, "job_posting", on) for k, on in switches.items()]
    return repo


def run_jobs(repo: MemoryRepository, ai: FakeAI | None = None) -> RunStatus:
    return cli.run_source(
        "job_posting",
        settings=Settings(_env_file=None),
        repo=repo,
        dry_run=False,
        ai=ai or FakeAI(),
    )


@pytest.mark.usefixtures("feeds")
def test_leads_and_signals_record_their_platform() -> None:
    repo = job_repo(remoteok=True, weworkremotely=True)
    assert run_jobs(repo) is RunStatus.SUCCESS
    platforms = {s["platform"] for s in repo.signals.values()}
    assert platforms == {"remoteok", "weworkremotely"}
    for lead in repo.leads.values():
        assert lead["source_platform"] in platforms
    runs = {r.key: r for r in repo.platform_runs}
    assert set(runs) == {"remoteok", "weworkremotely"}
    assert all(r.status is RunStatus.SUCCESS and r.fetched for r in runs.values())
    assert sum(r.items_seen for r in runs.values()) == next(iter(repo.runs.values()))["items_seen"]
    assert sum(r.leads_new for r in runs.values()) == len(repo.leads)


def test_switched_off_platform_is_not_read(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []
    routes = {
        REMOTEOK_API: httpx.Response(200, json=REMOTEOK_JSON),
        WWR_FEED: httpx.Response(200, content=WWR_RSS),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return routes.get(str(request.url), httpx.Response(404))

    monkeypatch.setattr(JobPostingsSource, "transport", httpx.MockTransport(handler))
    repo = job_repo(remoteok=False, weworkremotely=True)
    run_jobs(repo)
    assert REMOTEOK_API not in requested and WWR_FEED in requested
    assert {s["platform"] for s in repo.signals.values()} == {"weworkremotely"}
    # Only platforms that were on get a run recorded.
    assert [r.key for r in repo.platform_runs] == ["weworkremotely"]


@pytest.mark.usefixtures("feeds")
def test_failed_feed_marks_its_platform_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = {REMOTEOK_API: httpx.Response(200, json=REMOTEOK_JSON)}  # WWR feed -> 404
    monkeypatch.setattr(JobPostingsSource, "transport", mock_transport(routes))
    repo = job_repo(remoteok=True, weworkremotely=True)
    assert run_jobs(repo) is RunStatus.PARTIAL
    runs = {r.key: r for r in repo.platform_runs}
    assert runs["remoteok"].status is RunStatus.SUCCESS
    assert runs["weworkremotely"].status is RunStatus.FAILED
    assert runs["weworkremotely"].error and "feed failed" in runs["weworkremotely"].error


def test_all_platforms_off_skips_the_run() -> None:
    repo = job_repo(remoteok=False, weworkremotely=False)
    ai = FakeAI()
    assert run_jobs(repo, ai) is RunStatus.SUCCESS
    assert repo.runs == {} and ai.calls == []


@pytest.mark.usefixtures("feeds")
def test_ai_off_saves_unscored_leads_without_ai_calls() -> None:
    repo = job_repo(remoteok=True, weworkremotely=True)
    repo.ai_on = False
    ai = FakeAI()
    assert run_jobs(repo, ai) is RunStatus.SUCCESS
    assert ai.calls == []
    assert repo.leads and all(lead.get("fit_score") is None for lead in repo.leads.values())
    assert all(lead["status"] == "new" for lead in repo.leads.values())
    assert repo.outreach == []


def test_ai_off_pauses_sources_that_need_ai() -> None:
    repo = MemoryRepository()
    repo.ai_on = False
    ai = FakeAI()
    status = cli.run_source(
        "funding", settings=Settings(_env_file=None), repo=repo, dry_run=False, ai=ai
    )
    assert status is RunStatus.SUCCESS
    assert repo.runs == {} and ai.calls == []


def unscored_repo() -> tuple[MemoryRepository, list[Any]]:
    repo = MemoryRepository()
    ids = [
        repo.create_lead(make_candidate(company="Acme", url="https://jobs.example.com/1")),
        repo.create_lead(
            make_candidate(
                company="Beta",
                website="https://beta.io",
                url="https://jobs.example.com/2",
                contacts=[{"full_name": "Dana Lee", "role": "CTO"}],
            )
        ),
    ]
    return repo, ids


def test_backlog_is_scored_once_ai_is_back_on() -> None:
    repo, (acme, beta) = unscored_repo()
    repo.leads[acme]["status"] = "approved"  # moved on by hand: left alone
    ai = FakeAI()
    with cli.RunRecorder(repo, "job_posting") as run:
        scored = cli.score_backlog("job_posting", repo, run, cli.Assessor(ai, run.add_tokens))
    assert scored == 1 and run.stats.leads_updated == 1
    assert repo.leads[acme].get("fit_score") is None
    lead = repo.leads[beta]
    assert lead["fit_score"] == 7 and lead["best_channel"] == "email"
    assert lead["industry"] == "saas"  # filled in by the extract step
    # The extract step names Dana Lee, already stored: no duplicate contact.
    beta_contacts = [c for c in repo.contacts if c["lead_id"] == str(beta)]
    assert [c["full_name"] for c in beta_contacts] == ["Dana Lee"]
    (draft,) = repo.outreach
    assert draft["lead_id"] == str(beta) and draft["contact_id"] == beta_contacts[0]["id"]
    assert repo.signals["https://jobs.example.com/2"]["metadata"]["ai_prompts"]["score"]
    assert repo.activities[-1]["type"] == "lead_scored"
    # Scored now: the next run finds nothing to do.
    assert repo.unscored_leads("job_posting", 10) == []


def test_backlog_reject_gets_no_draft() -> None:
    repo, (_, beta) = unscored_repo()
    with cli.RunRecorder(repo, "job_posting") as run:
        cli.score_backlog("job_posting", repo, run, cli.Assessor(FakeAI(score=2), run.add_tokens))
    assert repo.leads[beta]["status"] == "rejected"
    assert repo.outreach == []


def test_backlog_failure_leaves_lead_for_next_run() -> None:
    repo, (acme, beta) = unscored_repo()
    ai = FakeAI(fail={"score": AIError("overloaded")})
    with cli.RunRecorder(repo, "job_posting") as run:
        scored = cli.score_backlog("job_posting", repo, run, cli.Assessor(ai, run.add_tokens))
    assert scored == 0 and len(run.stats.errors) == 2
    assert {s.lead_id for s in repo.unscored_leads("job_posting", 10)} == {acme, beta}


def test_backlog_skips_do_not_contact() -> None:
    repo, _ = unscored_repo()
    repo.dnc_domains.add("beta.io")
    ai = FakeAI()
    with cli.RunRecorder(repo, "job_posting") as run:
        assert cli.score_backlog("job_posting", repo, run, cli.Assessor(ai, run.add_tokens)) == 1


@pytest.mark.usefixtures("feeds")
def test_real_run_scores_backlog_after_collecting() -> None:
    repo = job_repo(remoteok=True, weworkremotely=True)
    repo.ai_on = False
    run_jobs(repo)
    waiting = len(repo.leads)
    repo.ai_on = True
    run_jobs(repo)
    (_, second) = repo.runs.values()
    assert waiting and second["leads_new"] == 0
    assert second["leads_updated"] == min(waiting, cli.BACKLOG_PER_RUN)
    left = len(repo.unscored_leads("job_posting", 100))
    assert left == max(0, waiting - cli.BACKLOG_PER_RUN)


def test_from_stored_round_trip() -> None:
    candidate = make_candidate(contacts=[{"full_name": "Dana", "email": "dana@acme.com"}])
    repo = MemoryRepository()
    lead_id = repo.create_lead(candidate)
    (stored,) = repo.unscored_leads("job_posting", 5)
    assert stored.lead_id == lead_id
    assert stored.candidate.model_dump(exclude={"signal"}) == candidate.model_dump(
        exclude={"signal"}
    )
    assert stored.candidate.signal.source_url == candidate.signal.source_url
    assert isinstance(stored.candidate, LeadCandidate)


def test_expected_sources() -> None:
    rows = [
        PlatformRow("remoteok", "job_posting", False),
        PlatformRow("weworkremotely", "job_posting", True),
        PlatformRow("eu_startups", "funding", True, needs_ai=True),
        PlatformRow("reddit", "social", False),
    ]
    configs = {"job_posting", "funding", "social", "fixture"}
    assert expected_sources(configs, rows, True) == ["fixture", "funding", "job_posting"]
    assert expected_sources(configs, rows, False) == ["fixture", "job_posting"]
    rows[1] = PlatformRow("weworkremotely", "job_posting", False)
    assert expected_sources(configs, rows, True) == ["fixture", "funding"]


def test_summary_says_when_ai_is_off() -> None:
    repo = MemoryRepository()
    assert "switched off" not in str(summary_payload(build_summary(repo, datetime.now(UTC))))
    repo.ai_on = False
    payload = summary_payload(build_summary(repo, datetime.now(UTC)))
    assert "Claude AI is switched off" in str(payload["blocks"])
