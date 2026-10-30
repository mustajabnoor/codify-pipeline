"""The AI step in the pipeline, with FakeAI standing in for Claude."""

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from agent import main as cli
from agent.ai.assess import Assessor, load_prompt
from agent.ai.client import AIConfigError, AIError
from agent.core.config import Settings
from agent.core.db import DryRunRepository, MemoryRepository
from agent.core.dedupe import Action
from agent.core.models import SIGN_OFF, LeadSource, RunStatus, SourceConfig
from agent.core.pipeline import process_candidate
from agent.core.runs import RunRecorder
from agent.sources.job_posts import REMOTEOK_API, JobPostingsSource

from .conftest import FAKE_USAGE, FakeAI, make_candidate
from .test_job_posts import REMOTEOK_JSON, config, mock_transport


class Spend:
    def __init__(self) -> None:
        self.calls: list[tuple[int, Decimal]] = []

    def __call__(self, tokens: int, cost: Decimal) -> None:
        self.calls.append((tokens, cost))


def test_prompts_load_with_company_profile() -> None:
    for name in ("score_v1", "score_v2", "draft_v1"):
        text = load_prompt(name)
        assert "{company_profile}" not in text
        assert "5+ years building on Bubble.io" in text
    assert "Proof points" not in load_prompt("extract_v1")


def test_new_lead_is_extracted_scored_and_drafted() -> None:
    ai, spend = FakeAI(score=7), Spend()
    candidate = make_candidate(company="Acme")
    result = Assessor(ai, spend)(candidate)

    assert ai.tasks == ["extract", "score", "draft"]
    assert spend.calls == [(FAKE_USAGE.tokens, FAKE_USAGE.cost)] * 3
    # Extraction fills blanks only.
    assert (result.company_name, result.domain) == ("Acme", "acme.com")
    assert (result.industry, result.country, result.company_size) == (
        "saas",
        "United States",
        "11-50",
    )
    assert result.tech_stack == ["node", "react"]
    (dana,) = result.contacts
    assert (dana.full_name, dana.role, dana.email) == ("Dana Lee", "CTO", None)
    assert dana.found_via == "job_posting:job_post"
    assert result.assessment and result.assessment.fit_score == 7
    assert result.outreach and result.outreach.draft_body.endswith(SIGN_OFF)
    assert result.signal.metadata["ai_prompts"] == {
        "extract": "extract_v1",
        "score": "score_v2",
        "draft": "draft_v1",
    }
    # The draft prompt sees the score, the pain point and who to address.
    draft_prompt = ai.calls[2][1]
    assert "Fit score: 7/10" in draft_prompt and "Contact: Dana Lee (CTO)" in draft_prompt


def test_collected_fields_are_not_overwritten() -> None:
    candidate = make_candidate().model_copy(update={"country": "Canada", "tech_stack": ["bubble"]})
    result = Assessor(FakeAI(), Spend())(candidate)
    assert result.country == "Canada"
    assert result.tech_stack == ["bubble"]


def test_reject_gets_no_draft() -> None:
    ai = FakeAI(score=3)
    result = Assessor(ai, Spend())(make_candidate())
    assert ai.tasks == ["extract", "score"]
    assert result.outreach is None
    assert result.lead_row()["status"] == "rejected"
    assert "draft" not in result.signal.metadata["ai_prompts"]


def test_failed_call_still_records_spend() -> None:
    spend = Spend()
    ai = FakeAI(fail={"score": AIError("declined", FAKE_USAGE)})
    with pytest.raises(AIError):
        Assessor(ai, spend)(make_candidate())
    assert len(spend.calls) == 2  # extract + the failed score call


def run_with(ai: FakeAI, repo: MemoryRepository, *candidates: Any) -> list[Action]:
    with RunRecorder(repo, "job_posting") as run:
        assess = Assessor(ai, run.add_tokens)
        return [process_candidate(c, repo, run, assess) for c in candidates]


def test_pipeline_stores_score_and_outreach_draft() -> None:
    repo, ai = MemoryRepository(), FakeAI()
    run_with(ai, repo, make_candidate())

    (lead,) = repo.leads.values()
    assert (lead["fit_score"], lead["status"], lead["best_channel"]) == (7, "new", "email")
    assert lead["pain_point"] == "hiring a React developer for a 3-month contract"
    (draft,) = repo.outreach
    (dana,) = repo.contacts
    assert draft["contact_id"] == dana["id"]
    assert (draft["status"], draft["channel"]) == ("draft", "email")
    assert draft["draft_body"].endswith(SIGN_OFF)
    assert "scored 7/10" in repo.activities[0]["note"]
    (run,) = repo.runs.values()
    assert (run["tokens_used"], Decimal(run["cost_estimate"])) == (300, Decimal("0.03"))


def test_known_companies_and_posts_cost_no_tokens() -> None:
    repo, ai = MemoryRepository(), FakeAI()
    first = make_candidate()
    same_company = make_candidate(source="funding", url="https://news.example.com/acme")
    actions = run_with(ai, repo, first, same_company, first)
    assert actions == [Action.CREATE_LEAD, Action.ADD_SIGNAL, Action.SKIP_KNOWN_SIGNAL]
    assert ai.tasks == ["extract", "score", "draft"]  # only the new lead


def test_dry_run_prints_the_draft(capsys: pytest.CaptureFixture[str]) -> None:
    run_with(FakeAI(), DryRunRepository(), make_candidate())
    (line,) = capsys.readouterr().out.splitlines()
    payload = json.loads(line)
    assert payload["lead"]["fit_score"] == 7
    assert payload["outreach"]["subject"] == "Your React contract role"
    assert payload["outreach"]["draft_body"].endswith(SIGN_OFF)


def run_job_posts(monkeypatch: pytest.MonkeyPatch, ai: FakeAI, repo: MemoryRepository) -> RunStatus:
    routes = {REMOTEOK_API: httpx.Response(200, json=REMOTEOK_JSON)}
    monkeypatch.setattr(JobPostingsSource, "transport", mock_transport(routes))
    repo.source_configs = [
        SourceConfig(source=LeadSource.JOB_POSTING, name="default", config=config(rss_feeds=[]))
    ]
    return cli.run_source(
        "job_posting", settings=Settings(_env_file=None), repo=repo, dry_run=False, ai=ai
    )


def test_ai_failure_saves_nothing_and_next_run_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MemoryRepository()
    failing = FakeAI(fail={"score": AIError("model declined", FAKE_USAGE)})
    assert run_job_posts(monkeypatch, failing, repo) is RunStatus.FAILED
    assert repo.leads == {} and repo.signals == {}
    (first,) = repo.runs.values()
    assert len(first["errors"]) == 3 and "model declined" in first["errors"][0]["message"]
    assert first["tokens_used"] == 600  # 3 items x (extract + failed score)

    assert run_job_posts(monkeypatch, FakeAI(), repo) is RunStatus.SUCCESS
    assert len(repo.leads) == 3


def test_bad_api_key_stops_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MemoryRepository()
    ai = FakeAI(fail={"extract": AIConfigError("Claude API rejected the request")})
    with pytest.raises(AIConfigError):
        run_job_posts(monkeypatch, ai, repo)
    assert len(ai.calls) == 1  # stopped at the first item
    (run,) = repo.runs.values()
    assert run["status"] == "failed"
