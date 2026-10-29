"""SupabaseRepository against a recording fake of the supabase query builder."""

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest
from postgrest.exceptions import APIError

from agent.core.db import SupabaseRepository
from agent.core.errors import DuplicateLeadError, DuplicateSignalError
from agent.core.models import RunStats, RunStatus

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
