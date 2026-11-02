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
from agent.core.platforms import PlatformRun

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredLead:
    """A saved lead rebuilt for scoring later (it was saved while AI was off).
    contact_ids[i] is the stored id of candidate.contacts[i]."""

    lead_id: UUID
    candidate: LeadCandidate
    contact_ids: list[str]


@dataclass(frozen=True)
class PlatformRow:
    """The parts of a source_platforms row the agent reads."""

    key: str
    source: str
    enabled: bool
    needs_ai: bool = False


def expected_sources(
    enabled_configs: set[str], platforms: Sequence[PlatformRow], ai_enabled: bool
) -> list[str]:
    """Sources that should run on schedule: enabled in source_configs, with at
    least one platform switched on (when it has platforms), and not paused
    because every platform it has on needs AI while AI is off."""
    expected = []
    for source in sorted(enabled_configs):
        own = [p for p in platforms if p.source == source]
        on = [p for p in own if p.enabled]
        if own and not on:
            continue
        if not ai_enabled and on and all(p.needs_ai for p in on):
            continue
        expected.append(source)
    return expected


class Repository(DedupeLookup, Protocol):
    def get_source_configs(self, source: str) -> list[SourceConfig]: ...

    def get_platform_switches(self, source: str) -> dict[str, bool] | None:
        """source_platforms.enabled by key for this source; None if unknown."""
        ...

    def ai_enabled(self) -> bool:
        """The Claude API switch (app_settings.ai_enabled)."""
        ...

    def record_platform_runs(self, runs: list[PlatformRun]) -> None:
        """Write each platform's last run (time, status, counts, first error)."""
        ...

    def unscored_leads(self, source: str, limit: int) -> list[StoredLead]:
        """New leads of this first_source saved without a score, oldest first."""
        ...

    def save_assessment(self, stored: StoredLead, assessed: LeadCandidate) -> bool:
        """Store a later AI assessment: score fields, filled-in facts, contacts,
        draft. False if the lead was scored or moved on in the meantime."""
        ...

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

    def enabled_sources(self) -> list[str]:
        """Sources expected to run on schedule (see expected_sources)."""
        ...

    def followups_due_count(self) -> int: ...

    def ai_enabled(self) -> bool: ...


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


def _platform_row(run: PlatformRun) -> dict[str, Any]:
    return {
        "last_run_at": datetime.now(UTC).isoformat(),
        "last_run_status": run.status.value,
        "last_run_items": run.items_seen,
        "last_run_leads_new": run.leads_new,
        "last_run_error": run.error,
    }


# Lead facts the extract step may fill in (it never overwrites collected ones).
_EXTRACTED_FIELDS = ("industry", "country", "city", "company_size", "description", "tech_stack")


def _assessed_lead_update(assessed: LeadCandidate) -> dict[str, Any]:
    row = assessed.model_dump(mode="json", include=set(_EXTRACTED_FIELDS))
    row.update(assessed.assessment_fields())
    return row


def _contact_changes(
    stored: StoredLead, assessed: LeadCandidate
) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    """(updates to stored contacts by id, new contact rows). The AI step keeps
    the stored contacts first and in order; it may fill one in (an email
    found for a named person) and add new ones after them."""
    updates, inserts = [], []
    rows = assessed.contact_rows(stored.lead_id)
    for index, (contact, row) in enumerate(zip(assessed.contacts, rows, strict=True)):
        if index < len(stored.contact_ids):
            if contact != stored.candidate.contacts[index]:
                row.pop("lead_id")
                updates.append((stored.contact_ids[index], row))
        else:
            inserts.append(row)
    return updates, inserts


def _scored_activity(lead_id: UUID, assessed: LeadCandidate) -> dict[str, Any]:
    score = assessed.assessment.fit_score if assessed.assessment else None
    note = f"scored {score}/10 (saved while Claude AI was off)"
    return {"lead_id": str(lead_id), "type": "lead_scored", "note": note, "actor": "agent"}


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
        self.platforms: list[PlatformRow] = []
        self.platform_runs: list[PlatformRun] = []
        self.ai_on = True

    def is_do_not_contact(self, *, domains: Sequence[str], emails: Sequence[str]) -> bool:
        return bool(self.dnc_domains.intersection(domains) or self.dnc_emails.intersection(emails))

    def lead_id_for_source_url(self, source_url: str) -> UUID | None:
        signal = self.signals.get(source_url)
        return UUID(signal["lead_id"]) if signal else None

    def lead_id_for_domain(self, domain: str) -> UUID | None:
        return next((i for i, lead in self.leads.items() if lead["domain"] == domain), None)

    def get_source_configs(self, source: str) -> list[SourceConfig]:
        return [c for c in self.source_configs if c.source.value == source]

    def get_platform_switches(self, source: str) -> dict[str, bool] | None:
        own = {p.key: p.enabled for p in self.platforms if p.source == source}
        return own or None

    def ai_enabled(self) -> bool:
        return self.ai_on

    def record_platform_runs(self, runs: list[PlatformRun]) -> None:
        self.platform_runs.extend(runs)

    def unscored_leads(self, source: str, limit: int) -> list[StoredLead]:
        found = []
        leads = sorted(self.leads.items(), key=lambda item: _ts(item[1]["created_at"]))
        for lead_id, lead in leads:
            if (
                lead["first_source"] != source
                or lead["status"] != "new"
                or lead.get("fit_score") is not None
            ):
                continue
            signals = sorted(
                (
                    s
                    for s in self.signals.values()
                    if s["lead_id"] == str(lead_id) and s["source"] == source
                ),
                key=lambda s: _ts(s["detected_at"]),
            )
            if not signals:
                continue
            contacts = [c for c in self.contacts if c["lead_id"] == str(lead_id)]
            candidate = LeadCandidate.from_stored(lead, signals[0], contacts)
            found.append(StoredLead(lead_id, candidate, [c["id"] for c in contacts]))
            if len(found) >= limit:
                break
        return found

    def save_assessment(self, stored: StoredLead, assessed: LeadCandidate) -> bool:
        lead = self.leads.get(stored.lead_id)
        if not lead or lead["status"] != "new" or lead.get("fit_score") is not None:
            return False
        lead.update(_assessed_lead_update(assessed))
        updates, inserts = _contact_changes(stored, assessed)
        by_id = {c["id"]: c for c in self.contacts}
        for contact_id, row in updates:
            by_id[contact_id].update(row)
        self.contacts.extend({**row, "id": str(uuid4())} for row in inserts)
        signal = self.signals[stored.candidate.signal.source_url]
        signal["metadata"] = assessed.signal.metadata
        if assessed.outreach:
            own = [c for c in self.contacts if c["lead_id"] == str(stored.lead_id)]
            self.outreach.append(
                assessed.outreach.outreach_row(stored.lead_id, _outreach_contact(own))
            )
        self.activities.append(_scored_activity(stored.lead_id, assessed))
        return True

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
        configs = {c.source.value for c in self.source_configs if c.enabled}
        return expected_sources(configs, self.platforms, self.ai_on)

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

    def get_platform_switches(self, source: str) -> dict[str, bool] | None:
        return self._reader.get_platform_switches(source) if self._reader else None

    def ai_enabled(self) -> bool:
        return self._reader.ai_enabled() if self._reader else True

    def record_platform_runs(self, runs: list[PlatformRun]) -> None:
        for run in runs:
            log.info(
                "dry run: platform %s %s (seen %d, new %d)",
                run.key, run.status, run.items_seen, run.leads_new,
            )  # fmt: skip

    def unscored_leads(self, source: str, limit: int) -> list[StoredLead]:
        return self._reader.unscored_leads(source, limit) if self._reader else []

    def save_assessment(self, stored: StoredLead, assessed: LeadCandidate) -> bool:
        self._emit(
            {
                "action": "score_lead",
                "lead_id": str(stored.lead_id),
                "lead": _assessed_lead_update(assessed),
                "contacts": [c.model_dump(mode="json") for c in assessed.contacts],
                "outreach": assessed.outreach
                and {
                    **assessed.outreach.model_dump(mode="json", exclude={"body"}),
                    "draft_body": assessed.outreach.draft_body,
                },
            }
        )
        return True

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

    def _platforms(self, source: str | None = None) -> list[PlatformRow]:
        query = self._db.table("source_platforms").select("key, source, enabled, needs_ai")
        if source is not None:
            query = query.eq("source", source)
        return [PlatformRow(**row) for row in query.execute().data]

    def get_platform_switches(self, source: str) -> dict[str, bool] | None:
        if source not in LeadSource._value2member_map_:
            return None
        return {p.key: p.enabled for p in self._platforms(source)} or None

    def ai_enabled(self) -> bool:
        rows = self._db.table("app_settings").select("ai_enabled").limit(1).execute().data
        return bool(rows[0]["ai_enabled"]) if rows else True

    def record_platform_runs(self, runs: list[PlatformRun]) -> None:
        for run in runs:
            self._db.table("source_platforms").update(_platform_row(run)).eq(
                "key", run.key
            ).execute()

    def unscored_leads(self, source: str, limit: int) -> list[StoredLead]:
        rows = (
            self._db.table("leads")
            .select(
                "*, signals(source, source_url, signal_type, title, raw_text, detected_at, "
                "metadata, platform), contacts(*)"
            )
            .eq("first_source", source)
            .eq("status", "new")
            .is_("fit_score", "null")
            .order("created_at")
            .limit(limit)
            .execute()
            .data
        )
        found = []
        for row in rows:
            signals = sorted(
                (s for s in row.get("signals") or [] if s["source"] == source),
                key=lambda s: s["detected_at"],
            )
            if not signals:
                log.warning("unscored lead %s has no %s signal; skipped", row["id"], source)
                continue
            contacts = sorted(row.get("contacts") or [], key=lambda c: c["created_at"])
            candidate = LeadCandidate.from_stored(row, signals[0], contacts)
            found.append(StoredLead(UUID(row["id"]), candidate, [c["id"] for c in contacts]))
        return found

    def save_assessment(self, stored: StoredLead, assessed: LeadCandidate) -> bool:
        lead_id = str(stored.lead_id)
        # Only while still new and unscored: the dashboard may have moved it on.
        updated = (
            self._db.table("leads")
            .update(_assessed_lead_update(assessed))
            .eq("id", lead_id)
            .eq("status", "new")
            .is_("fit_score", "null")
            .execute()
            .data
        )
        if not updated:
            return False
        updates, inserts = _contact_changes(stored, assessed)
        for contact_id, row in updates:
            self._db.table("contacts").update(row).eq("id", contact_id).execute()
        if inserts:
            self._db.table("contacts").insert(inserts).execute()
        self._db.table("signals").update({"metadata": assessed.signal.metadata}).eq(
            "source_url", stored.candidate.signal.source_url
        ).execute()
        if assessed.outreach:
            contacts = (
                self._db.table("contacts")
                .select("id, is_primary, email, full_name")
                .eq("lead_id", lead_id)
                .order("created_at")
                .execute()
                .data
            )
            self._db.table("outreach").insert(
                assessed.outreach.outreach_row(stored.lead_id, _outreach_contact(contacts))
            ).execute()
        self._db.table("activities").insert(_scored_activity(stored.lead_id, assessed)).execute()
        return True

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
        configs = {row["source"] for row in rows.data}
        return expected_sources(configs, self._platforms(), self.ai_enabled())

    def followups_due_count(self) -> int:
        result = self._db.table("v_followups_due").select("id", count="exact").limit(1).execute()
        return result.count or 0
