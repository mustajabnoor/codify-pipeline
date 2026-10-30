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
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
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


@dataclass(frozen=True)
class LeadDigest:
    """A new lead as the daily summary shows it."""

    company_name: str
    domain: str | None
    fit_score: int | None
    status: str
    first_source: str
    pain_point: str | None
    funding_round: str | None
    created_at: datetime
    signal_title: str | None = None
    signal_url: str | None = None


@dataclass(frozen=True)
class RunDigest:
    source: str
    status: str
    started_at: datetime
    leads_new: int
    errors: int
    tokens_used: int
    cost_estimate: Decimal


class ReportReader(Protocol):
    """Read-only queries for the daily summary."""

    def recent_leads(self, since: datetime) -> list[LeadDigest]: ...

    def recent_runs(self, since: datetime) -> list[RunDigest]: ...

    def enabled_sources(self) -> list[str]: ...

    def followups_due_count(self) -> int: ...


def _ts(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


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
        self.leads[lead_id] = {**candidate.lead_row(), "created_at": datetime.now(UTC)}
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
        self.runs[run_id] = {
            "source": source,
            "status": RunStatus.RUNNING.value,
            "started_at": datetime.now(UTC),
        }
        return run_id

    def finish_run(
        self, run_id: UUID | None, source: str, status: RunStatus, stats: RunStats
    ) -> None:
        if run_id is not None:
            self.runs[run_id].update(_run_row(status, stats))

    def recent_leads(self, since: datetime) -> list[LeadDigest]:
        digests = []
        for lead_id, lead in self.leads.items():
            if _ts(lead["created_at"]) < since:
                continue
            signals = sorted(
                (s for s in self.signals.values() if s["lead_id"] == str(lead_id)),
                key=lambda s: s["detected_at"],
            )
            first = signals[0] if signals else {}
            digests.append(
                LeadDigest(
                    company_name=lead["company_name"],
                    domain=lead.get("domain"),
                    fit_score=lead.get("fit_score"),
                    status=lead["status"],
                    first_source=lead["first_source"],
                    pain_point=lead.get("pain_point"),
                    funding_round=lead.get("funding_round"),
                    created_at=_ts(lead["created_at"]),
                    signal_title=first.get("title"),
                    signal_url=first.get("source_url"),
                )
            )
        return digests

    def recent_runs(self, since: datetime) -> list[RunDigest]:
        return [
            RunDigest(
                source=run["source"],
                status=run["status"],
                started_at=_ts(run["started_at"]),
                leads_new=run.get("leads_new", 0),
                errors=len(run.get("errors", [])),
                tokens_used=run.get("tokens_used", 0),
                cost_estimate=Decimal(str(run.get("cost_estimate", 0))),
            )
            for run in self.runs.values()
            if _ts(run["started_at"]) >= since
        ]

    def enabled_sources(self) -> list[str]:
        return sorted({c.source.value for c in self.source_configs if c.enabled})

    def followups_due_count(self) -> int:
        now = datetime.now(UTC)
        return sum(
            1
            for lead in self.leads.values()
            if lead.get("next_follow_up_at")
            and _ts(lead["next_follow_up_at"]) <= now
            and lead["status"] not in ("won", "lost", "rejected")
        )


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

    def recent_leads(self, since: datetime) -> list[LeadDigest]:
        rows = (
            self._db.table("leads")
            .select(
                "company_name, domain, fit_score, status, first_source, pain_point, "
                "funding_round, created_at, signals(title, source_url, detected_at)"
            )
            .gte("created_at", since.isoformat())
            .execute()
            .data
        )
        digests = []
        for row in rows:
            signals = sorted(row.get("signals") or [], key=lambda s: s["detected_at"])
            first = signals[0] if signals else {}
            digests.append(
                LeadDigest(
                    company_name=row["company_name"],
                    domain=row.get("domain"),
                    fit_score=row.get("fit_score"),
                    status=row["status"],
                    first_source=row["first_source"],
                    pain_point=row.get("pain_point"),
                    funding_round=row.get("funding_round"),
                    created_at=_ts(row["created_at"]),
                    signal_title=first.get("title"),
                    signal_url=first.get("source_url"),
                )
            )
        return digests

    def recent_runs(self, since: datetime) -> list[RunDigest]:
        rows = (
            self._db.table("agent_runs")
            .select("source, status, started_at, leads_new, errors, tokens_used, cost_estimate")
            .gte("started_at", since.isoformat())
            .execute()
            .data
        )
        return [
            RunDigest(
                source=row["source"],
                status=row["status"],
                started_at=_ts(row["started_at"]),
                leads_new=row["leads_new"],
                errors=len(row.get("errors") or []),
                tokens_used=row["tokens_used"],
                cost_estimate=Decimal(str(row["cost_estimate"])),
            )
            for row in rows
        ]

    def enabled_sources(self) -> list[str]:
        rows = self._db.table("source_configs").select("source").eq("enabled", True).execute()
        return sorted({row["source"] for row in rows.data})

    def followups_due_count(self) -> int:
        result = self._db.table("v_followups_due").select("id", count="exact").limit(1).execute()
        return result.count or 0
