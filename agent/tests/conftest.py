from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from agent.ai.client import Usage
from agent.ai.schemas import Draft, Extraction, Person
from agent.core.config import Settings
from agent.core.db import MemoryRepository
from agent.core.models import Channel, LeadAssessment, LeadCandidate, Service


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Tests never see real credentials or a local .env file."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.delenv("CODIFY_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def repo() -> MemoryRepository:
    return MemoryRepository()


def make_candidate(
    *,
    company: str = "Acme",
    website: str | None = "https://acme.com",
    source: str = "job_posting",
    url: str = "https://jobs.example.com/1",
    contacts: list[dict[str, Any]] | None = None,
) -> LeadCandidate:
    return LeadCandidate.model_validate(
        {
            "company_name": company,
            "website": website,
            "signal": {"source": source, "source_url": url, "signal_type": "job_post"},
            "contacts": contacts or [],
        }
    )


FAKE_USAGE = Usage(tokens=100, cost=Decimal("0.01"))


class FakeAI:
    """Stands in for ClaudeAI: canned output per task, records each call.
    `fail` maps a task to the exception it raises."""

    def __init__(self, score: int = 7, fail: dict[str, Exception] | None = None) -> None:
        self.score = score
        self.fail = fail or {}
        self.calls: list[tuple[str, str]] = []  # (task, user prompt)

    def structured(
        self, task: str, *, system: str, user: str, output: type[BaseModel]
    ) -> tuple[Any, Usage]:
        self.calls.append((task, user))
        if task in self.fail:
            raise self.fail[task]
        canned: dict[str, BaseModel] = {
            "extract": Extraction(
                industry="saas",
                country="United States",
                city=None,
                company_size="11-50",
                description="Acme builds scheduling tools.",
                tech_stack=["React", "react", "Node"],
                people=[Person(name="Dana Lee", role="CTO")],
            ),
            "score": LeadAssessment(
                fit_score=self.score,
                score_reason="Hiring a React developer now.",
                service_fit=[Service.MVP, Service.SAAS],
                pain_point="hiring a React developer for a 3-month contract",
            ),
            "draft": Draft(
                subject="Your React contract role",
                body="Hi Dana, saw you're hiring a React developer. Worth a quick look?",
                best_channel=Channel.EMAIL,
            ),
        }
        result = canned[task]
        assert isinstance(result, output)
        return result, FAKE_USAGE

    @property
    def tasks(self) -> list[str]:
        return [task for task, _ in self.calls]
