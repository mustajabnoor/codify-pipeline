"""Database access behind one small interface.

* SupabaseRepository - the real thing (service-role key, bypasses RLS).
* MemoryRepository   - in-process store with the same rules (tests).
* DryRunRepository   - reads from Supabase when credentials exist, never writes;
                       prints what it would insert as JSON lines on stdout.
"""

import json
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, TextIO
from uuid import UUID, uuid4

from agent.core.config import Settings
from agent.core.dedupe import DedupeLookup
from agent.core.errors import DuplicateLeadError, DuplicateSignalError
from agent.core.models import LeadCandidate, LeadSource, RunStats, RunStatus, SourceConfig

log = logging.getLogger(__name__)


class Repository(DedupeLookup, Protocol):
    def get_source_configs(self, source: str) -> list[SourceConfig]: ...

    def create_lead(self, candidate: LeadCandidate) -> UUID:
        """Insert lead + signal + contacts + activity. Raises DuplicateLeadError
        if the domain was taken concurrently, DuplicateSignalError likewise."""
        ...

    def add_signal(self, lead_id: UUID, candidate: LeadCandidate) -> None:
        """Attach a new signal (and any new emailed contacts) to an existing lead."""
        ...

    def start_run(self, source: str) -> UUID | None: ...

    def finish_run(
        self, run_id: UUID | None, source: str, status: RunStatus, stats: RunStats
    ) -> None: ...


def _activity(lead_id: UUID, type_: str, candidate: LeadCandidate) -> dict[str, Any]:
    title = candidate.signal.title or candidate.signal.signal_type
    note = f"{candidate.source.value}: {title} ({candidate.signal.source_url})"
    if candidate.assessment:
        note += f"; scored {candidate.assessment.fit_score}/10"
    return {"lead_id": str(lead_id), "type": type_, "note": note, "actor": "agent"}


def _outreach_contact(rows: list[dict[str, Any]]) -> str | None:
    """Which stored contact a draft is addressed to: primary, else one with an
    email, else the first named one."""
    for wanted in (lambda r: r["is_primary"], lambda r: r["email"], lambda r: r["full_name"]):
        if match := next((r for r in rows if wanted(r)), None):
            return match["id"]
    return None


def _run_row(status: RunStatus, stats: RunStats) -> dict[str, Any]:
    row = stats.model_dump(mode="json")
    row.update(status=status.value, finished_at=datetime.now(UTC).isoformat())
    return row


class MemoryRepository:
    def __init__(self) -> None:
        self.leads: dict[UUID, dict[str, Any]] = {}
        self.signals: dict[str, dict[str, Any]] = {}  # by source_url
        self.contacts: list[dict[str, Any]] = []
        self.outreach: list[dict[str, Any]] = []
        self.activities: list[dict[str, Any]] = []
        self.runs: dict[UUID, dict[str, Any]] = {}
        self.source_configs: list[SourceConfig] = []
        self.dnc_emails: set[str] = set()
        self.dnc_domains: set[str] = set()

    def is_do_not_contact(self, *, domains: Sequence[str], emails: Sequence[str]) -> bool:
        return bool(self.dnc_domains.intersection(domains) or self.dnc_emails.intersection(emails))

    def lead_id_for_source_url(self, source_url: str) -> UUID | None:
        signal = self.signals.get(source_url)
        return UUID(signal["lead_id"]) if signal else None

    def lead_id_for_domain(self, domain: str) -> UUID | None:
        return next((i for i, lead in self.leads.items() if lead["domain"] == domain), None)

    def get_source_configs(self, source: str) -> list[SourceConfig]:
        return [c for c in self.source_configs if c.source.value == source]

    def create_lead(self, candidate: LeadCandidate) -> UUID:
        if candidate.domain and self.lead_id_for_domain(candidate.domain):
            raise DuplicateLeadError(candidate.domain)
        if candidate.signal.source_url in self.signals:
            raise DuplicateSignalError(candidate.signal.source_url)
        lead_id = uuid4()
        self.leads[lead_id] = candidate.lead_row()
        self.signals[candidate.signal.source_url] = candidate.signal_row(lead_id)
        contacts = [{**row, "id": str(uuid4())} for row in candidate.contact_rows(lead_id)]
        self.contacts.extend(contacts)
        if candidate.outreach:
            self.outreach.append(
                candidate.outreach.outreach_row(lead_id, _outreach_contact(contacts))
            )
        self.activities.append(_activity(lead_id, "lead_created", candidate))
        return lead_id

    def add_signal(self, lead_id: UUID, candidate: LeadCandidate) -> None:
        if candidate.signal.source_url in self.signals:
            raise DuplicateSignalError(candidate.signal.source_url)
        self.signals[candidate.signal.source_url] = candidate.signal_row(lead_id)
        known = {c["email"] for c in self.contacts if c["lead_id"] == str(lead_id)}
        for row in candidate.contact_rows(lead_id, allow_primary=False):
            if row["email"] and row["email"] not in known:
                self.contacts.append(row)
        self.activities.append(_activity(lead_id, "signal_added", candidate))

    def start_run(self, source: str) -> UUID | None:
        run_id = uuid4()
        self.runs[run_id] = {"source": source, "status": RunStatus.RUNNING.value}
        return run_id

    def finish_run(
        self, run_id: UUID | None, source: str, status: RunStatus, stats: RunStats
    ) -> None:
        if run_id is not None:
            self.runs[run_id].update(_run_row(status, stats))


class DryRunRepository(MemoryRepository):
    """Never writes to the database. Lookups check this run's would-be inserts
    first, then the real database (if a reader is given), so a dry run reports
    the same create/add/skip decisions a real run would."""

    def __init__(self, reader: Repository | None = None, out: TextIO | None = None) -> None:
        super().__init__()
        self._reader = reader
        self._out = out

    def _emit(self, payload: dict[str, Any]) -> None:
        print(json.dumps(payload, default=str), file=self._out or sys.stdout, flush=True)

    def is_do_not_contact(self, *, domains: Sequence[str], emails: Sequence[str]) -> bool:
        return super().is_do_not_contact(domains=domains, emails=emails) or bool(
            self._reader and self._reader.is_do_not_contact(domains=domains, emails=emails)
        )

    def lead_id_for_source_url(self, source_url: str) -> UUID | None:
        return super().lead_id_for_source_url(source_url) or (
            self._reader.lead_id_for_source_url(source_url) if self._reader else None
        )

    def lead_id_for_domain(self, domain: str) -> UUID | None:
        return super().lead_id_for_domain(domain) or (
            self._reader.lead_id_for_domain(domain) if self._reader else None
        )

    def get_source_configs(self, source: str) -> list[SourceConfig]:
        return self._reader.get_source_configs(source) if self._reader else []

    def create_lead(self, candidate: LeadCandidate) -> UUID:
        lead_id = super().create_lead(candidate)
        self._emit(
            {
                "action": "create_lead",
                "lead": candidate.lead_row(),
                "signal": candidate.signal.model_dump(mode="json"),
                "contacts": [c.model_dump(mode="json") for c in candidate.contacts],
                "outreach": candidate.outreach
                and {
                    **candidate.outreach.model_dump(mode="json", exclude={"body"}),
                    "draft_body": candidate.outreach.draft_body,
                },
            }
        )
        return lead_id

    def add_signal(self, lead_id: UUID, candidate: LeadCandidate) -> None:
        super().add_signal(lead_id, candidate)
        self._emit(
            {
                "action": "add_signal",
                "lead_id": str(lead_id),
                "domain": candidate.domain,
                "signal": candidate.signal.model_dump(mode="json"),
            }
        )

    def start_run(self, source: str) -> UUID | None:
        return None

    def finish_run(
        self, run_id: UUID | None, source: str, status: RunStatus, stats: RunStats
    ) -> None:
        log.info("dry run: agent_runs row not written")


class SupabaseRepository:
    def __init__(self, client: Any) -> None:
        self._db = client

    @classmethod
    def from_settings(cls, settings: Settings) -> "SupabaseRepository":
        from supabase import create_client

        settings.require("supabase_url", "supabase_service_role_key", scope="database")
        assert settings.supabase_url and settings.supabase_service_role_key
        client = create_client(
            settings.supabase_url, settings.supabase_service_role_key.get_secret_value()
        )
        return cls(client)

    @staticmethod
    def _is_unique_violation(exc: Exception, constraint: str) -> bool:
        from postgrest.exceptions import APIError

        return (
            isinstance(exc, APIError)
            and getattr(exc, "code", None) == "23505"
            and constraint in str(exc)
        )

    def _first(self, table: str, column: str, **filters: Any) -> Any | None:
        query = self._db.table(table).select(column)
        for key, value in filters.items():
            query = query.eq(key, value)
        rows = query.limit(1).execute().data
        return rows[0][column] if rows else None

    def is_do_not_contact(self, *, domains: Sequence[str], emails: Sequence[str]) -> bool:
        for column, values in (("domain", domains), ("email", emails)):
            if values:
                rows = (
                    self._db.table("do_not_contact")
                    .select("id")
                    .in_(column, list(values))
                    .limit(1)
                    .execute()
                    .data
                )
                if rows:
                    return True
        return False

    def lead_id_for_source_url(self, source_url: str) -> UUID | None:
        value = self._first("signals", "lead_id", source_url=source_url)
        return UUID(value) if value else None

    def lead_id_for_domain(self, domain: str) -> UUID | None:
        value = self._first("leads", "id", domain=domain)
        return UUID(value) if value else None

    def get_source_configs(self, source: str) -> list[SourceConfig]:
        if source not in LeadSource._value2member_map_:
            return []
        rows = (
            self._db.table("source_configs")
            .select("source, name, config, enabled")
            .eq("source", source)
            .execute()
            .data
        )
        return [SourceConfig.model_validate(row) for row in rows]

    def create_lead(self, candidate: LeadCandidate) -> UUID:
        # PostgREST has no multi-table transaction, so a failed insert after the
        # lead deletes it again (cascade removes anything attached).
        try:
            lead = self._db.table("leads").insert(candidate.lead_row()).execute().data[0]
        except Exception as exc:
            if self._is_unique_violation(exc, "leads_domain_key"):
                raise DuplicateLeadError(candidate.domain) from exc
            raise
        lead_id = UUID(lead["id"])
        try:
            self._insert_signal(lead_id, candidate)
            contacts: list[dict[str, Any]] = []
            if rows := candidate.contact_rows(lead_id):
                contacts = self._db.table("contacts").insert(rows).execute().data
            if candidate.outreach:
                self._db.table("outreach").insert(
                    candidate.outreach.outreach_row(lead_id, _outreach_contact(contacts))
                ).execute()
            self._db.table("activities").insert(
                _activity(lead_id, "lead_created", candidate)
            ).execute()
        except Exception:
            self._db.table("leads").delete().eq("id", str(lead_id)).execute()
            raise
        return lead_id

    def add_signal(self, lead_id: UUID, candidate: LeadCandidate) -> None:
        self._insert_signal(lead_id, candidate)
        rows = [r for r in candidate.contact_rows(lead_id, allow_primary=False) if r["email"]]
        if rows:
            self._db.table("contacts").upsert(
                rows, on_conflict="lead_id,email", ignore_duplicates=True
            ).execute()
        self._db.table("activities").insert(_activity(lead_id, "signal_added", candidate)).execute()

    def _insert_signal(self, lead_id: UUID, candidate: LeadCandidate) -> None:
        try:
            self._db.table("signals").insert(candidate.signal_row(lead_id)).execute()
        except Exception as exc:
            if self._is_unique_violation(exc, "signals_source_url_key"):
                raise DuplicateSignalError(candidate.signal.source_url) from exc
            raise

    def start_run(self, source: str) -> UUID | None:
        row = self._db.table("agent_runs").insert({"source": source}).execute().data[0]
        return UUID(row["id"])

    def finish_run(
        self, run_id: UUID | None, source: str, status: RunStatus, stats: RunStats
    ) -> None:
        if run_id is None:
            return
        self._db.table("agent_runs").update(_run_row(status, stats)).eq("id", str(run_id)).execute()
        if source in LeadSource._value2member_map_:
            self._db.table("source_configs").update(
                {"last_run_at": datetime.now(UTC).isoformat()}
            ).eq("source", source).eq("enabled", True).execute()
