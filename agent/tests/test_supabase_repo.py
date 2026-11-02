"""SupabaseRepository against a recording fake of the supabase query builder."""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from postgrest.exceptions import APIError

from agent.core.db import SupabaseRepository
from agent.core.errors import DuplicateLeadError, DuplicateSignalError
from agent.core.models import (
    Channel,
    ContactIn,
    LeadAssessment,
    OutreachDraft,
    RunStats,
    RunStatus,
    Service,
)
from agent.core.platforms import PlatformRun

from .conftest import make_candidate


@dataclass
class Call:
    table: str
    op: str
    payload: Any = None
    filters: list[tuple[str, str, Any]] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)


class FakeQuery:
    def __init__(self, client: "FakeClient", table: str) -> None:
        self.client = client
        self.call = Call(table, "select")

    def _op(self, op: str, payload: Any = None, **kwargs: Any) -> "FakeQuery":
        self.call.op, self.call.payload, self.call.kwargs = op, payload, kwargs
        return self

    def select(self, columns: str) -> "FakeQuery":
        return self._op("select", columns)

    def insert(self, payload: Any) -> "FakeQuery":
        return self._op("insert", payload)

    def upsert(self, payload: Any, **kwargs: Any) -> "FakeQuery":
        return self._op("upsert", payload, **kwargs)

    def update(self, payload: Any) -> "FakeQuery":
        return self._op("update", payload)

    def delete(self) -> "FakeQuery":
        return self._op("delete")

    def eq(self, column: str, value: Any) -> "FakeQuery":
        self.call.filters.append(("eq", column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> "FakeQuery":
        self.call.filters.append(("in", column, values))
        return self

    def is_(self, column: str, value: Any) -> "FakeQuery":
        self.call.filters.append(("is", column, value))
        return self

    def order(self, column: str, **_: Any) -> "FakeQuery":
        return self

    def limit(self, _: int) -> "FakeQuery":
        return self

    def execute(self) -> Any:
        self.client.calls.append(self.call)
        key = (self.call.table, self.call.op)
        result = self.client.responses.get(key, [])
        if isinstance(result, Exception):
            raise result

        @dataclass
        class Response:
            data: Any

        return Response(result)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.responses: dict[tuple[str, str], Any] = {}

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def ops(self) -> list[tuple[str, str]]:
        return [(c.table, c.op) for c in self.calls]


def unique_violation(constraint: str) -> APIError:
    return APIError(
        {
            "code": "23505",
            "message": f'duplicate key value violates unique constraint "{constraint}"',
            "details": None,
            "hint": None,
        }
    )


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def repo(client: FakeClient) -> SupabaseRepository:
    return SupabaseRepository(client)


def test_lookups(client: FakeClient, repo: SupabaseRepository) -> None:
    lead_id = uuid4()
    client.responses[("leads", "select")] = [{"id": str(lead_id)}]
    assert repo.lead_id_for_domain("acme.com") == lead_id
    assert client.calls[-1].filters == [("eq", "domain", "acme.com")]

    assert repo.lead_id_for_source_url("https://x.example.com") is None


def test_do_not_contact_checks_domains_then_emails(
    client: FakeClient, repo: SupabaseRepository
) -> None:
    assert not repo.is_do_not_contact(domains=["acme.com"], emails=["a@acme.com"])
    assert [c.filters for c in client.calls] == [
        [("in", "domain", ["acme.com"])],
        [("in", "email", ["a@acme.com"])],
    ]
    client.calls.clear()
    assert not repo.is_do_not_contact(domains=[], emails=[])
    assert client.calls == []


def test_create_lead_writes_lead_signal_contacts_activity(
    client: FakeClient, repo: SupabaseRepository
) -> None:
    lead_id = uuid4()
    client.responses[("leads", "insert")] = [{"id": str(lead_id)}]
    candidate = make_candidate(contacts=[{"email": "a@acme.com", "is_primary": True}])

    assert repo.create_lead(candidate) == lead_id
    assert client.ops() == [
        ("leads", "insert"),
        ("signals", "insert"),
        ("contacts", "insert"),
        ("activities", "insert"),
    ]
    assert client.calls[0].payload["domain"] == "acme.com"
    assert client.calls[1].payload["lead_id"] == str(lead_id)


def test_create_lead_duplicate_domain(client: FakeClient, repo: SupabaseRepository) -> None:
    client.responses[("leads", "insert")] = unique_violation("leads_domain_key")
    with pytest.raises(DuplicateLeadError):
        repo.create_lead(make_candidate())


def test_create_lead_rolls_back_when_signal_insert_fails(
    client: FakeClient, repo: SupabaseRepository
) -> None:
    lead_id = uuid4()
    client.responses[("leads", "insert")] = [{"id": str(lead_id)}]
    client.responses[("signals", "insert")] = unique_violation("signals_source_url_key")
    with pytest.raises(DuplicateSignalError):
        repo.create_lead(make_candidate())
    assert client.calls[-1].op == "delete"
    assert client.calls[-1].filters == [("eq", "id", str(lead_id))]


def test_other_api_errors_propagate(client: FakeClient, repo: SupabaseRepository) -> None:
    client.responses[("leads", "insert")] = APIError({"code": "42501", "message": "denied"})
    with pytest.raises(APIError):
        repo.create_lead(make_candidate())


def test_add_signal_upserts_emailed_contacts_only(
    client: FakeClient, repo: SupabaseRepository
) -> None:
    lead_id = uuid4()
    candidate = make_candidate(
        contacts=[{"email": "a@acme.com", "is_primary": True}, {"full_name": "No Email"}]
    )
    repo.add_signal(lead_id, candidate)
    assert client.ops() == [("signals", "insert"), ("contacts", "upsert"), ("activities", "insert")]
    upsert = client.calls[1]
    assert [r["email"] for r in upsert.payload] == ["a@acme.com"]
    assert upsert.payload[0]["is_primary"] is False
    assert upsert.kwargs == {"on_conflict": "lead_id,email", "ignore_duplicates": True}


def test_finish_run_updates_run_and_source_configs(
    client: FakeClient, repo: SupabaseRepository
) -> None:
    run_id = uuid4()
    repo.finish_run(run_id, "funding", RunStatus.SUCCESS, RunStats(leads_new=2))
    run_update, config_update = client.calls
    assert run_update.payload["status"] == "success"
    assert run_update.payload["leads_new"] == 2
    assert config_update.table == "source_configs"
    assert config_update.filters == [("eq", "source", "funding"), ("eq", "enabled", True)]

    client.calls.clear()
    repo.finish_run(uuid4(), "fixture", RunStatus.SUCCESS, RunStats())
    assert client.ops() == [("agent_runs", "update")]


def test_source_configs_only_for_lead_sources(client: FakeClient, repo: SupabaseRepository) -> None:
    assert repo.get_source_configs("fixture") == []
    assert client.calls == []
    client.responses[("source_configs", "select")] = [
        {"source": "funding", "name": "default", "config": {"rounds": ["seed"]}, "enabled": True}
    ]
    (config,) = repo.get_source_configs("funding")
    assert config.config == {"rounds": ["seed"]}


def test_create_lead_writes_outreach_draft_for_primary_contact(
    client: FakeClient, repo: SupabaseRepository
) -> None:
    lead_id = uuid4()
    client.responses[("leads", "insert")] = [{"id": str(lead_id)}]
    client.responses[("contacts", "insert")] = [
        {"id": "c-other", "is_primary": False, "email": None, "full_name": "Sam"},
        {"id": "c-primary", "is_primary": True, "email": "a@acme.com", "full_name": "Dana"},
    ]
    candidate = make_candidate(
        contacts=[{"full_name": "Sam"}, {"email": "a@acme.com", "is_primary": True}]
    ).model_copy(
        update={"outreach": OutreachDraft(channel="email", subject="Hi", body="Worth a look?")}
    )

    repo.create_lead(candidate)
    assert client.ops() == [
        ("leads", "insert"),
        ("signals", "insert"),
        ("contacts", "insert"),
        ("outreach", "insert"),
        ("activities", "insert"),
    ]
    outreach = client.calls[3].payload
    assert outreach["contact_id"] == "c-primary"
    assert (outreach["status"], outreach["subject"]) == ("draft", "Hi")
    assert outreach["draft_body"].startswith("Worth a look?\n\n")


def test_failed_outreach_insert_removes_the_lead(
    client: FakeClient, repo: SupabaseRepository
) -> None:
    lead_id = uuid4()
    client.responses[("leads", "insert")] = [{"id": str(lead_id)}]
    client.responses[("outreach", "insert")] = APIError({"code": "23514", "message": "check"})
    candidate = make_candidate().model_copy(
        update={"outreach": OutreachDraft(channel="email", subject="Hi", body="b")}
    )
    with pytest.raises(APIError):
        repo.create_lead(candidate)
    assert (client.calls[-1].table, client.calls[-1].op) == ("leads", "delete")


def test_platform_switches_and_ai_setting(client: FakeClient, repo: SupabaseRepository) -> None:
    assert repo.get_platform_switches("fixture") is None
    assert repo.get_platform_switches("job_posting") is None  # no rows
    client.responses[("source_platforms", "select")] = [
        {"key": "remoteok", "source": "job_posting", "enabled": False, "needs_ai": False},
    ]
    assert repo.get_platform_switches("job_posting") == {"remoteok": False}
    assert repo.ai_enabled() is True  # no settings row
    client.responses[("app_settings", "select")] = [{"ai_enabled": False}]
    assert repo.ai_enabled() is False


def test_record_platform_runs(client: FakeClient, repo: SupabaseRepository) -> None:
    repo.record_platform_runs(
        [PlatformRun("remoteok", items_seen=4, leads_new=1, fetched=True, errors=["bad item"])]
    )
    (call,) = client.calls
    assert (call.table, call.op, call.filters) == (
        "source_platforms",
        "update",
        [("eq", "key", "remoteok")],
    )
    assert call.payload["last_run_status"] == "partial"
    assert (call.payload["last_run_items"], call.payload["last_run_leads_new"]) == (4, 1)
    assert call.payload["last_run_error"] == "bad item"


def stored_lead_row() -> dict[str, Any]:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "company_name": "Acme",
        "domain": "acme.com",
        "website": "https://acme.com",
        "tech_stack": [],
        "signals": [
            {
                "source": "funding",
                "source_url": "https://news.example.com/other",
                "signal_type": "funding_round",
                "detected_at": "2026-10-01T00:00:00+00:00",
                "metadata": {},
            },
            {
                "source": "job_posting",
                "source_url": "https://remoteok.com/remote-jobs/2",
                "signal_type": "job_post",
                "detected_at": "2026-10-03T00:00:00+00:00",
                "metadata": {},
                "platform": "remoteok",
            },
        ],
        "contacts": [
            {
                "id": "c1",
                "full_name": "Dana Lee",
                "role": "CTO",
                "email": None,
                "email_status": "unverified",
                "is_primary": False,
                "created_at": "2026-10-03T00:00:00+00:00",
            }
        ],
    }


def test_unscored_leads(client: FakeClient, repo: SupabaseRepository) -> None:
    client.responses[("leads", "select")] = [stored_lead_row()]
    (stored,) = repo.unscored_leads("job_posting", 5)
    (call,) = client.calls
    assert ("is", "fit_score", "null") in call.filters
    assert ("eq", "status", "new") in call.filters
    assert stored.candidate.signal.platform == "remoteok"  # its job_posting signal
    assert stored.contact_ids == ["c1"]
    assert stored.candidate.contacts[0].full_name == "Dana Lee"


def test_save_assessment(client: FakeClient, repo: SupabaseRepository) -> None:
    client.responses[("leads", "select")] = [stored_lead_row()]
    (stored,) = repo.unscored_leads("job_posting", 5)
    client.calls.clear()
    assessed = stored.candidate.model_copy(
        update={
            "assessment": LeadAssessment(
                fit_score=8, score_reason="r", service_fit=[Service.MVP], pain_point="p"
            ),
            "outreach": OutreachDraft(channel=Channel.EMAIL, subject="s", body="b"),
            "contacts": [
                stored.candidate.contacts[0].model_copy(update={"email": "dana@acme.com"}),
                ContactIn(full_name="Info", email="info@acme.com"),
            ],
        }
    )
    # The lead was scored or moved on meanwhile: nothing else is written.
    assert repo.save_assessment(stored, assessed) is False
    assert client.ops() == [("leads", "update")]

    client.calls.clear()
    client.responses[("leads", "update")] = [{"id": str(stored.lead_id)}]
    client.responses[("contacts", "select")] = [
        {"id": "c1", "is_primary": False, "email": "dana@acme.com", "full_name": "Dana Lee"}
    ]
    assert repo.save_assessment(stored, assessed) is True
    assert client.ops() == [
        ("leads", "update"),
        ("contacts", "update"),
        ("contacts", "insert"),
        ("signals", "update"),
        ("contacts", "select"),
        ("outreach", "insert"),
        ("activities", "insert"),
    ]
    lead_update = client.calls[0]
    assert lead_update.payload["fit_score"] == 8 and lead_update.payload["best_channel"] == "email"
    assert client.calls[1].payload["email"] == "dana@acme.com"
    assert client.calls[1].filters == [("eq", "id", "c1")]
    assert client.calls[5].payload["contact_id"] == "c1"
