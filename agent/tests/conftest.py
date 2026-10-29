from typing import Any

import pytest

from agent.core.config import Settings
from agent.core.db import MemoryRepository
from agent.core.models import LeadCandidate


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """Tests never see real credentials or a local .env file."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
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
