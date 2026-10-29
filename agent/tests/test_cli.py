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

from .conftest import make_candidate


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
    status = cli.run_source("job_posting", settings=settings, repo=repo, dry_run=False)
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
