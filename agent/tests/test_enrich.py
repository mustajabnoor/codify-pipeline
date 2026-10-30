"""Contact finding and verification, with saved Hunter / MillionVerifier responses."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent import main as cli
from agent.ai.assess import Assessor
from agent.core.config import Settings
from agent.core.db import MemoryRepository
from agent.core.models import (
    ContactIn,
    EmailStatus,
    LeadAssessment,
    LeadCandidate,
    RunStatus,
    Service,
)
from agent.core.pipeline import process_candidate
from agent.core.runs import RunRecorder
from agent.enrich.enricher import Enricher, pick_people
from agent.enrich.providers import Hunter, MillionVerifier, Person

from .conftest import FakeAI, make_candidate

FIXTURES = Path(__file__).parent / "fixtures" / "enrich"
HUNTER_KEY = "hunter-test-key"
MV_KEY = "mv-test-key"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


Handler = Callable[[httpx.Request], httpx.Response]


class FakeAPIs:
    """Routes Hunter and MillionVerifier calls to saved responses; records each."""

    def __init__(
        self,
        *,
        domain_search: Any = "hunter_domain_search",
        email_finder: Any = "hunter_email_finder",
        verify: Callable[[str], Any] | str = "millionverifier_ok",
        hunter_status: int = 200,
    ) -> None:
        self.responses = {"domain-search": domain_search, "email-finder": email_finder}
        self.verify = verify
        self.hunter_status = hunter_status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "api.hunter.io":
            assert request.headers["X-API-KEY"] == HUNTER_KEY
            if self.hunter_status != 200:
                return httpx.Response(self.hunter_status, json=fixture("hunter_auth_failed"))
            body = self.responses[request.url.path.rsplit("/", 1)[-1]]
            return httpx.Response(200, json=fixture(body) if isinstance(body, str) else body)
        assert request.url.params["api"] == MV_KEY
        email = request.url.params["email"]
        name = self.verify if isinstance(self.verify, str) else self.verify(email)
        return httpx.Response(200, json={**fixture(name), "email": email})

    @property
    def calls(self) -> list[str]:
        return [
            r.url.path.rsplit("/", 1)[-1] if r.url.host == "api.hunter.io" else "verify"
            for r in self.requests
        ]


class Errors:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, message: str, **context: Any) -> None:
        self.calls.append((message, context))


def make_enricher(
    apis: FakeAPIs,
    *,
    verifier: bool = True,
    blocked: frozenset[str] = frozenset(),
    errors: Errors | None = None,
    max_lookups: int = 10,
) -> Enricher:
    transport = httpx.MockTransport(apis)
    return Enricher(
        Hunter(HUNTER_KEY, transport),
        MillionVerifier(MV_KEY, transport) if verifier else None,
        is_blocked=lambda email: email in blocked,
        report_error=errors or Errors(),
        max_lookups=max_lookups,
    )


def scored(candidate: LeadCandidate | None = None, score: int = 8) -> LeadCandidate:
    assessment = LeadAssessment(
        fit_score=score, score_reason="r", service_fit=[Service.MVP], pain_point="p"
    )
    return (candidate or make_candidate()).model_copy(update={"assessment": assessment})


def test_picks_founder_over_engineer_and_generic_inbox() -> None:
    people = [Person.model_validate({**p, "email": p["value"]}) for p in
              fixture("hunter_domain_search")["data"]["emails"]]  # fmt: skip
    assert [p.email for p in pick_people(people)] == [
        "dana@acme.com",
        "lee@partner-agency.com",
        "sam@acme.com",
        "info@acme.com",
    ]


def test_domain_search_finds_and_verifies_the_decision_maker() -> None:
    apis = FakeAPIs()
    result = make_enricher(apis)(scored())

    assert apis.calls == ["domain-search", "verify"]
    (contact,) = result.contacts
    assert contact.email == "dana@acme.com"
    assert (contact.full_name, contact.role) == ("Dana Lee", "Co-Founder & CEO")
    assert contact.email_status is EmailStatus.VALID
    assert contact.is_primary and contact.found_via == "hunter:domain_search"
    assert contact.x_url == "https://x.com/danalee"
    assert result.signal.metadata["enrichment"] == {
        "provider": "hunter",
        "method": "domain_search",
        "verified": {"dana@acme.com": "ok"},
        "found": True,
    }


def test_invalid_email_falls_back_to_the_next_person() -> None:
    apis = FakeAPIs(
        verify=lambda e: "millionverifier_invalid" if e == "dana@acme.com" else "millionverifier_ok"
    )
    result = make_enricher(apis)(scored())
    # lee@partner-agency.com is at another domain, so the engineer is next.
    (contact,) = result.contacts
    assert (contact.email, contact.email_status) == ("sam@acme.com", EmailStatus.VALID)
    assert result.signal.metadata["enrichment"]["verified"] == {
        "dana@acme.com": "invalid",
        "sam@acme.com": "ok",
    }


def test_only_invalid_emails_saves_no_contact() -> None:
    result = make_enricher(FakeAPIs(verify="millionverifier_invalid"))(scored())
    assert result.contacts == []
    assert result.signal.metadata["enrichment"]["found"] is False


def test_named_founder_uses_email_finder_and_fills_that_contact() -> None:
    founder = ContactIn(full_name="Priya Shah", role="Founder", found_via="funding:round")
    apis = FakeAPIs()
    result = make_enricher(apis)(
        scored(make_candidate().model_copy(update={"contacts": [founder]}))
    )

    assert apis.calls == ["email-finder", "verify"]
    (contact,) = result.contacts
    assert (contact.full_name, contact.role, contact.email) == (
        "Priya Shah",
        "Founder",
        "priya@acme.com",
    )
    assert contact.is_primary and contact.email_status is EmailStatus.VALID


def test_email_finder_miss_falls_back_to_domain_search() -> None:
    founder = ContactIn(full_name="Priya Shah", role="CEO")
    apis = FakeAPIs(email_finder="hunter_email_finder_none")
    result = make_enricher(apis)(
        scored(make_candidate().model_copy(update={"contacts": [founder]}))
    )
    assert apis.calls == ["email-finder", "domain-search", "verify"]
    assert [c.full_name for c in result.contacts] == ["Priya Shah", "Dana Lee"]
    assert [c.is_primary for c in result.contacts] == [False, True]


def test_without_verifier_email_stays_unverified() -> None:
    apis = FakeAPIs()
    result = make_enricher(apis, verifier=False)(scored())
    assert apis.calls == ["domain-search"]
    (contact,) = result.contacts
    assert contact.email_status is EmailStatus.UNVERIFIED


def test_do_not_contact_email_is_never_used() -> None:
    apis = FakeAPIs()
    result = make_enricher(apis, blocked=frozenset({"dana@acme.com"}))(scored())
    assert apis.calls == ["domain-search", "verify"]  # dana is never verified
    assert [c.email for c in result.contacts] == ["sam@acme.com"]


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (scored(score=5), "score below 6"),
        (scored(make_candidate(website=None)), "no domain"),
        (scored(make_candidate(contacts=[{"email": "a@acme.com"}])), "email already known"),
    ],
)
def test_skips_cost_no_lookups(candidate: LeadCandidate, reason: str) -> None:
    apis = FakeAPIs()
    result = make_enricher(apis)(candidate)
    assert apis.requests == []
    assert result.signal.metadata["enrichment"] == {"skipped": reason}


def test_run_limit_caps_lookups() -> None:
    apis = FakeAPIs(verify="millionverifier_ok")
    enrich = make_enricher(apis, max_lookups=1)
    enrich(scored())
    second = enrich(scored(make_candidate(website="https://beta.io", url="https://j.example/2")))
    assert apis.calls.count("domain-search") == 1
    assert second.signal.metadata["enrichment"] == {"skipped": "run limit reached"}


def test_rejected_hunter_key_stops_lookups_for_the_run() -> None:
    apis, errors = FakeAPIs(hunter_status=401), Errors()
    enrich = make_enricher(apis, errors=errors)
    first = enrich(scored())
    second = enrich(scored(make_candidate(website="https://beta.io", url="https://j.example/2")))

    assert apis.calls == ["domain-search"]
    assert first.contacts == [] and second.contacts == []
    assert second.signal.metadata["enrichment"] == {"skipped": "provider stopped"}
    ((message, _),) = errors.calls
    assert "HTTP 401" in message and "No user found" in message
    assert HUNTER_KEY not in message


def test_rejected_verifier_key_keeps_emails_unverified() -> None:
    apis, errors = FakeAPIs(verify="millionverifier_bad_key"), Errors()
    enrich = make_enricher(apis, errors=errors)
    first = enrich(scored())
    second = enrich(scored(make_candidate(url="https://j.example/2")))

    assert apis.calls == ["domain-search", "verify", "domain-search"]
    assert first.contacts[0].email_status is EmailStatus.UNVERIFIED
    assert second.contacts[0].email_status is EmailStatus.UNVERIFIED
    ((message, _),) = errors.calls
    assert "apikey_not_found" in message and MV_KEY not in message


def test_server_error_is_recorded_without_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.core.http.time.sleep", lambda _: None)
    errors = Errors()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.hunter.io":
            return httpx.Response(200, json=fixture("hunter_domain_search"))
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    enrich = Enricher(
        Hunter(HUNTER_KEY, transport),
        MillionVerifier(MV_KEY, transport),
        is_blocked=lambda _: False,
        report_error=errors,
    )
    result = enrich(scored())
    assert result.contacts == []
    ((message, context),) = errors.calls
    assert message == "enrichment failed: MillionVerifier returned HTTP 500"
    assert MV_KEY not in json.dumps(result.signal.metadata)
    assert context["domain"] == "acme.com"


def run_pipeline(ai: FakeAI, enrich: Enricher, repo: MemoryRepository) -> None:
    with RunRecorder(repo, "job_posting") as run:
        process_candidate(make_candidate(), repo, run, Assessor(ai, run.add_tokens, enrich))


def test_pipeline_enriches_before_drafting() -> None:
    # FakeAI extracts "Dana Lee (CTO)"; Hunter can't find her by name, the
    # domain search can, and her contact is filled in rather than duplicated.
    repo, ai = MemoryRepository(), FakeAI(score=8)
    apis = FakeAPIs(email_finder="hunter_email_finder_none")
    run_pipeline(ai, make_enricher(apis), repo)
    assert apis.calls == ["email-finder", "domain-search", "verify"]

    # The draft prompt knows the contact found.
    draft_prompt = next(user for task, user in ai.calls if task == "draft")
    assert "Contact email known: yes" in draft_prompt
    (dana,) = repo.contacts
    assert (dana["email"], dana["role"], dana["email_status"]) == ("dana@acme.com", "CTO", "valid")
    assert dana["is_primary"] is True
    (draft,) = repo.outreach
    assert draft["contact_id"] == dana["id"]


def test_rejected_lead_spends_no_credits() -> None:
    repo, apis = MemoryRepository(), FakeAPIs()
    run_pipeline(FakeAI(score=2), make_enricher(apis), repo)
    assert apis.requests == []
    (lead,) = repo.leads.values()
    assert lead["status"] == "rejected"


def test_dry_run_needs_enrich_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUNTER_API_KEY", HUNTER_KEY)
    repo = MemoryRepository()
    with RunRecorder(repo, "fixture") as run:
        settings = Settings(_env_file=None)
        assert cli.build_enricher(settings, repo, run, dry_run=True, enrich=False) is None
        enricher = cli.build_enricher(settings, repo, run, dry_run=True, enrich=True)
        assert enricher is not None and enricher.verifier is None  # no MillionVerifier key
        assert cli.build_enricher(settings, repo, run, dry_run=False, enrich=False) is not None


def test_missing_hunter_key_turns_enrichment_off() -> None:
    repo = MemoryRepository()
    with RunRecorder(repo, "job_posting") as run:
        settings = Settings(_env_file=None)
        assert cli.build_enricher(settings, repo, run, dry_run=False, enrich=False) is None
    (row,) = repo.runs.values()
    assert row["status"] == RunStatus.SUCCESS.value
