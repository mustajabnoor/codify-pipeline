from uuid import UUID

import pytest

from agent.core.db import MemoryRepository
from agent.core.dedupe import Action
from agent.core.errors import DuplicateLeadError
from agent.core.models import LeadCandidate
from agent.core.pipeline import process_candidate
from agent.core.runs import RunRecorder

from .conftest import make_candidate


def run_all(repo: MemoryRepository, *candidates: LeadCandidate) -> tuple[list[Action], RunRecorder]:
    with RunRecorder(repo, "job_posting") as run:
        actions = [process_candidate(c, repo, run) for c in candidates]
    return actions, run


def test_company_seen_twice_becomes_one_lead_with_two_signals(repo: MemoryRepository) -> None:
    job = make_candidate(contacts=[{"email": "dana@acme.com", "is_primary": True}])
    funding = make_candidate(
        source="funding",
        url="https://news.example.com/acme",
        contacts=[{"email": "dana@acme.com", "is_primary": True}, {"email": "cto@acme.com"}],
    )
    actions, run = run_all(repo, job, funding, job)

    assert actions == [Action.CREATE_LEAD, Action.ADD_SIGNAL, Action.SKIP_KNOWN_SIGNAL]
    assert len(repo.leads) == 1
    assert {s["source"] for s in repo.signals.values()} == {"job_posting", "funding"}
    # The known email is not duplicated; the new one is added but not as primary.
    assert sorted((c["email"], c["is_primary"]) for c in repo.contacts) == [
        ("cto@acme.com", False),
        ("dana@acme.com", True),
    ]
    assert [a["type"] for a in repo.activities] == ["lead_created", "signal_added"]
    assert (run.stats.leads_new, run.stats.leads_updated, run.stats.leads_skipped) == (1, 1, 1)


def test_lead_first_source_is_kept(repo: MemoryRepository) -> None:
    run_all(repo, make_candidate(), make_candidate(source="funding", url="https://n.example.com/x"))
    (lead,) = repo.leads.values()
    assert lead["first_source"] == "job_posting"


class RacingRepository(MemoryRepository):
    """Simulates another run inserting the same domain between lookup and insert."""

    def __init__(self) -> None:
        super().__init__()
        self.raced = False

    def lead_id_for_domain(self, domain: str) -> UUID | None:
        if not self.raced:
            return None
        return super().lead_id_for_domain(domain)

    def create_lead(self, candidate: LeadCandidate) -> UUID:
        if not self.raced:
            self.raced = True
            super().create_lead(make_candidate(url="https://other-run.example.com/1"))
            raise DuplicateLeadError(candidate.domain)
        return super().create_lead(candidate)


def test_concurrent_insert_falls_back_to_add_signal() -> None:
    repo = RacingRepository()
    actions, run = run_all(repo, make_candidate())
    assert actions == [Action.ADD_SIGNAL]
    assert len(repo.leads) == 1
    assert len(repo.signals) == 2
    assert run.stats.leads_updated == 1


def test_unexpected_error_propagates(
    repo: MemoryRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_: LeadCandidate) -> UUID:
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "create_lead", boom)
    with pytest.raises(RuntimeError):
        run_all(repo, make_candidate())
