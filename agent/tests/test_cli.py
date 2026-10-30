import json
from collections.abc import Iterable
from typing import Any, ClassVar

import pytest

from agent import main as cli
from agent.core.config import Settings
from agent.core.db import DryRunRepository, MemoryRepository
from agent.core.errors import MissingConfigError
from agent.core.models import LeadCandidate, LeadSource, RunStatus, SourceConfig
from agent.sources.base import Source

from .conftest import FakeAI, make_candidate


def test_fixture_dry_run_prints_inserts(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "fixture", "--dry-run"]) == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    actions = [
        (line["action"], line.get("lead", {}).get("domain") or line.get("domain")) for line in lines
    ]
    assert actions == [
        ("create_lead", "brightloop.io"),
        ("add_signal", "brightloop.io"),
        ("create_lead", None),
        ("create_lead", "nimbus-analytics.com"),
    ]
    assert lines[0]["contacts"][0]["email"] == "dana@brightloop.io"


def test_fixture_source_refuses_real_run(capsys: pytest.CaptureFixture[str]) -> None:
    repo = MemoryRepository()
    with pytest.raises(cli.AgentError, match="dev-only"):
        cli.run_source("fixture", settings=Settings(_env_file=None), repo=repo, dry_run=False)
    assert repo.runs == {}


def test_real_run_without_supabase_fails_clearly() -> None:
    assert cli.main(["run", "fixture"]) == 2


def test_unknown_source() -> None:
    assert cli.main(["run", "upwork", "--dry-run"]) == 2


def test_list_sources(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["sources"]) == 0
    assert "fixture" in capsys.readouterr().out


class NeedsKeySource(Source):
    name = "job_posting"
    required_settings = ("apify_token",)
    default_config: ClassVar[dict[str, Any]] = {"keywords": ["default"]}
    seen_configs: ClassVar[list[dict[str, Any]]] = []

    def collect(self, config: dict[str, Any]) -> Iterable[LeadCandidate]:
        NeedsKeySource.seen_configs.append(config)
        yield make_candidate()
        self.report_error("could not parse item", index=7)


@pytest.fixture
def needs_key(monkeypatch: pytest.MonkeyPatch) -> type[NeedsKeySource]:
    monkeypatch.setitem(cli.SOURCES, NeedsKeySource.name, NeedsKeySource)
    NeedsKeySource.seen_configs = []
    return NeedsKeySource


def test_missing_key_fails_that_source_and_logs_run(needs_key: type[NeedsKeySource]) -> None:
    repo = MemoryRepository()
    with pytest.raises(MissingConfigError, match="APIFY_TOKEN"):
        cli.run_source("job_posting", settings=Settings(_env_file=None), repo=repo, dry_run=False)
    (row,) = repo.runs.values()
    assert row["status"] == "failed"
    assert "APIFY_TOKEN" in row["errors"][0]["message"]


def test_runs_each_enabled_config(needs_key: type[NeedsKeySource]) -> None:
    repo = MemoryRepository()
    repo.source_configs = [
        SourceConfig(source=LeadSource.JOB_POSTING, name="a", config={"keywords": ["bubble"]}),
        SourceConfig(
            source=LeadSource.JOB_POSTING, name="b", config={"keywords": ["x"]}, enabled=False
        ),
    ]
    settings = Settings(_env_file=None, apify_token="t")
    status = cli.run_source("job_posting", settings=settings, repo=repo, dry_run=False, ai=FakeAI())
    assert needs_key.seen_configs == [{"keywords": ["bubble"]}]
    # One lead stored, one item error reported by the source -> partial.
    assert status is RunStatus.PARTIAL
    (row,) = repo.runs.values()
    assert row["leads_new"] == 1
    assert row["errors"][0]["context"] == {"index": 7}


def test_default_config_when_no_rows(needs_key: type[NeedsKeySource]) -> None:
    settings = Settings(_env_file=None, apify_token="t")
    cli.run_source("job_posting", settings=settings, repo=DryRunRepository(), dry_run=True)
    assert needs_key.seen_configs == [{"keywords": ["default"]}]


def test_disabled_source_does_nothing(needs_key: type[NeedsKeySource]) -> None:
    repo = MemoryRepository()
    repo.source_configs = [SourceConfig(source=LeadSource.JOB_POSTING, name="a", enabled=False)]
    status = cli.run_source(
        "job_posting", settings=Settings(_env_file=None), repo=repo, dry_run=False
    )
    assert status is RunStatus.SUCCESS
    assert repo.runs == {} and needs_key.seen_configs == []


def test_dry_run_reads_but_never_writes(capsys: pytest.CaptureFixture[str]) -> None:
    db = MemoryRepository()
    db.create_lead(make_candidate())
    before = (dict(db.leads), dict(db.signals))
    dry = DryRunRepository(reader=db)

    with cli.RunRecorder(dry, "job_posting") as run:
        cli.process_candidate(make_candidate(url="https://jobs.example.com/2"), dry, run)
        cli.process_candidate(make_candidate(), dry, run)

    assert (dict(db.leads), dict(db.signals)) == before
    assert (run.stats.leads_updated, run.stats.leads_skipped) == (1, 1)
    (line,) = capsys.readouterr().out.splitlines()
    assert json.loads(line)["action"] == "add_signal"


def test_real_run_requires_anthropic_key(needs_key: type[NeedsKeySource]) -> None:
    repo = MemoryRepository()
    settings = Settings(_env_file=None, apify_token="t")
    with pytest.raises(MissingConfigError, match="ANTHROPIC_API_KEY"):
        cli.run_source("job_posting", settings=settings, repo=repo, dry_run=False)
    (row,) = repo.runs.values()
    assert row["status"] == "failed" and repo.leads == {}


def test_dry_run_without_key_skips_ai(needs_key: type[NeedsKeySource]) -> None:
    repo = DryRunRepository()
    settings = Settings(_env_file=None, apify_token="t")
    cli.run_source("job_posting", settings=settings, repo=repo, dry_run=True)
    (lead,) = repo.leads.values()
    assert "fit_score" not in lead
    assert repo.outreach == []


def test_no_ai_is_dry_run_only(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["run", "fixture", "--dry-run", "--no-ai"]) == 0
    assert cli.main(["run", "fixture", "--no-ai"]) == 2


class Alerts:
    """Records run alerts (stands in for SlackNotifier.run_finished)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def __call__(self, source: str, status: str, stats: Any) -> None:
        self.calls.append((source, status, len(stats.errors)))


def test_partial_run_alerts_once(needs_key: type[NeedsKeySource]) -> None:
    alerts = Alerts()
    settings = Settings(_env_file=None, apify_token="t")
    cli.run_source(
        "job_posting", settings=settings, repo=MemoryRepository(), dry_run=False,
        ai=FakeAI(), notify=alerts,
    )  # fmt: skip
    assert alerts.calls == [("job_posting", "partial", 1)]


def test_dry_runs_never_alert(needs_key: type[NeedsKeySource]) -> None:
    alerts = Alerts()
    settings = Settings(_env_file=None, apify_token="t")
    cli.run_source(
        "job_posting", settings=settings, repo=DryRunRepository(), dry_run=True, notify=alerts
    )
    assert alerts.calls == []


def test_successful_run_does_not_alert() -> None:
    alerts = Alerts()
    repo = MemoryRepository()
    repo.source_configs = [SourceConfig(source=LeadSource.JOB_POSTING, name="a", enabled=False)]
    cli.run_source(
        "job_posting", settings=Settings(_env_file=None), repo=repo, dry_run=False, notify=alerts
    )
    assert alerts.calls == []


def test_config_error_alerts_once_and_marks_the_exception(
    needs_key: type[NeedsKeySource],
) -> None:
    alerts = Alerts()
    with pytest.raises(MissingConfigError) as exc:
        cli.run_source(
            "job_posting", settings=Settings(_env_file=None), repo=MemoryRepository(),
            dry_run=False, notify=alerts,
        )  # fmt: skip
    assert alerts.calls == [("job_posting", "failed", 1)]
    assert getattr(exc.value, "alerted", False)


class FakeNotifier:
    instances: ClassVar[list["FakeNotifier"]] = []

    def __init__(self) -> None:
        self.alerts = Alerts()
        FakeNotifier.instances.append(self)

    @classmethod
    def from_settings(cls, settings: Settings) -> "FakeNotifier":
        return cls()

    def run_finished(self, source: str, status: str, stats: Any) -> None:
        self.alerts(source, status, stats)


@pytest.fixture
def notifier(monkeypatch: pytest.MonkeyPatch) -> type[FakeNotifier]:
    FakeNotifier.instances = []
    monkeypatch.setattr(cli, "SlackNotifier", FakeNotifier)
    return FakeNotifier


def test_failure_before_the_run_starts_still_alerts(notifier: type[FakeNotifier]) -> None:
    # No Supabase credentials: the run never starts (as with missing GitHub secrets).
    assert cli.main(["run", "job_posting"]) == 2
    (instance,) = notifier.instances
    assert instance.alerts.calls == [("job_posting", "failed", 1)]


def test_failure_inside_the_run_is_not_alerted_twice(
    notifier: type[FakeNotifier], needs_key: type[NeedsKeySource], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "build_repository", lambda settings, dry_run: MemoryRepository())
    assert cli.main(["run", "job_posting"]) == 2  # APIFY_TOKEN missing
    (instance,) = notifier.instances
    assert instance.alerts.calls == [("job_posting", "failed", 1)]


def test_dry_run_cli_builds_no_notifier(notifier: type[FakeNotifier]) -> None:
    assert cli.main(["run", "fixture", "--dry-run", "--no-ai"]) == 0
    assert notifier.instances == []


def test_summary_needs_supabase_and_slack() -> None:
    assert cli.main(["summary", "--dry-run"]) == 2  # no Supabase credentials
