from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from agent.core.models import LeadCandidate
from agent.core.normalize import email_domain


class DedupeLookup(Protocol):
    def is_do_not_contact(self, *, domains: Sequence[str], emails: Sequence[str]) -> bool: ...

    def lead_id_for_source_url(self, source_url: str) -> UUID | None: ...

    def lead_id_for_domain(self, domain: str) -> UUID | None: ...


class Action(StrEnum):
    CREATE_LEAD = "create_lead"
    ADD_SIGNAL = "add_signal"
    SKIP_KNOWN_SIGNAL = "skip_known_signal"
    SKIP_DO_NOT_CONTACT = "skip_do_not_contact"


@dataclass(frozen=True)
class Decision:
    action: Action
    lead_id: UUID | None = None

    @property
    def is_skip(self) -> bool:
        return self.action in (Action.SKIP_KNOWN_SIGNAL, Action.SKIP_DO_NOT_CONTACT)


def decide(candidate: LeadCandidate, lookup: DedupeLookup) -> Decision:
    """What to do with a candidate, in order:
    1. do-not-contact match (company domain, contact emails or their domains) -> skip
    2. signal source_url already stored -> skip
    3. a lead with the same domain exists -> add this signal to it
    4. otherwise -> create a new lead
    """
    emails = candidate.emails
    domains = sorted({d for d in [candidate.domain, *map(email_domain, emails)] if d})
    if lookup.is_do_not_contact(domains=domains, emails=emails):
        return Decision(Action.SKIP_DO_NOT_CONTACT)

    if lead_id := lookup.lead_id_for_source_url(candidate.signal.source_url):
        return Decision(Action.SKIP_KNOWN_SIGNAL, lead_id)

    if candidate.domain and (lead_id := lookup.lead_id_for_domain(candidate.domain)):
        return Decision(Action.ADD_SIGNAL, lead_id)

    return Decision(Action.CREATE_LEAD)
