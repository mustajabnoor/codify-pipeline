"""Find a decision-maker's email for a new lead (Hunter) and verify it
(MillionVerifier). Runs after scoring, only for leads worth contacting, so
credits aren't spent on rejects."""

import logging
import re
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from agent.core.models import ContactIn, EmailStatus, LeadCandidate
from agent.core.normalize import normalize_email
from agent.enrich.providers import EnrichError, Hunter, MillionVerifier, Person, ProviderStopped

log = logging.getLogger(__name__)

# Leads scoring below this are saved without a contact search.
MIN_SCORE = 6
# Hunter lookups per run; the rest are saved without a contact search.
MAX_LOOKUPS_PER_RUN = 10
# Addresses verified per lead: the best pick, then the next if it bounces.
MAX_VERIFY_PER_LEAD = 2

# Titles that can buy development work, best first.
_TITLE_TIERS = [
    re.compile(r"\b(co-?founder|founder|ceo|chief executive|owner|managing director)\b", re.I),
    re.compile(r"\b(cto|chief technology|chief product|cpo|coo|president)\b", re.I),
    re.compile(
        r"\b(vp|vice president|head|director)\b.*\b(engineering|product|tech|digital)", re.I
    ),
]

ErrorReporter = Callable[..., None]
IsBlocked = Callable[[str], bool]


def _rank(person: Person) -> tuple[int, int, int]:
    """Lower is better: title tier, then seniority, then Hunter's confidence."""
    title = person.position or ""
    tier = next((i for i, rx in enumerate(_TITLE_TIERS) if rx.search(title)), len(_TITLE_TIERS))
    seniority = {"executive": 0, "senior": 1}.get(person.seniority or "", 2)
    return (tier, seniority, -(person.confidence or 0))


def pick_people(people: list[Person]) -> list[Person]:
    """Best contacts first: named people before generic inboxes (info@)."""
    personal = [p for p in people if p.type != "generic" and p.full_name]
    generic = [p for p in people if p not in personal]
    return sorted(personal, key=_rank) + sorted(generic, key=lambda p: -(p.confidence or 0))


def _x_url(handle: str | None) -> str | None:
    if not handle:
        return None
    handle = handle.strip().lstrip("@")
    return handle if handle.startswith("http") else f"https://x.com/{handle}"


class Enricher:
    """Adds at most one verified contact to a candidate. Never raises: a failed
    lookup is recorded and the lead is saved without it. A rejected key or used
    up credits turns that provider off for the rest of the run."""

    def __init__(
        self,
        hunter: Hunter,
        verifier: MillionVerifier | None,
        *,
        is_blocked: IsBlocked,
        report_error: ErrorReporter,
        max_lookups: int = MAX_LOOKUPS_PER_RUN,
    ) -> None:
        self.hunter: Hunter | None = hunter
        self.verifier = verifier
        self._is_blocked = is_blocked
        self._report_error = report_error
        self.lookups_left = max_lookups

    def __call__(self, candidate: LeadCandidate) -> LeadCandidate:
        note = self._skip_reason(candidate)
        if note is None:
            self.lookups_left -= 1
            try:
                note = self._enrich(candidate)
            except ProviderStopped as exc:
                self._report_error(f"enrichment stopped for this run: {exc}")
                self.hunter = None
                note = {"error": str(exc)}
            except (EnrichError, ValidationError) as exc:
                self._report_error(
                    f"enrichment failed: {exc}",
                    source_url=candidate.signal.source_url,
                    domain=candidate.domain,
                )
                note = {"error": str(exc)}
        contact = note.pop("contact", None)
        metadata = {**candidate.signal.metadata, "enrichment": note}
        update: dict[str, Any] = {
            "signal": candidate.signal.model_copy(update={"metadata": metadata})
        }
        if contact is not None:
            update["contacts"] = self._merge(candidate.contacts, contact)
        return candidate.model_copy(update=update)

    def _skip_reason(self, candidate: LeadCandidate) -> dict[str, Any] | None:
        score = candidate.assessment.fit_score if candidate.assessment else None
        if not candidate.domain:
            reason = "no domain"
        elif score is None or score < MIN_SCORE:
            reason = f"score below {MIN_SCORE}"
        elif candidate.emails:
            reason = "email already known"
        elif self.hunter is None:
            reason = "provider stopped"
        elif self.lookups_left <= 0:
            reason = "run limit reached"
        else:
            return None
        return {"skipped": reason}

    def _enrich(self, candidate: LeadCandidate) -> dict[str, Any]:
        assert self.hunter is not None and candidate.domain
        domain = candidate.domain
        named = [c for c in candidate.contacts if c.full_name and _is_buyer(c.role)]
        people: list[Person] = []
        method = "domain_search"
        if named:
            # A founder named in the signal: ask for that person's email.
            person = named[0]
            assert person.full_name
            if found := self.hunter.email_finder(domain, person.full_name):
                update = {
                    "first_name": person.full_name,
                    "last_name": None,
                    "position": person.role,
                }
                people = [found.model_copy(update=update)]
                method = "email_finder"
        if not people:
            people = pick_people(self.hunter.domain_search(domain))
        people = [p for p in people if _same_domain(p.email, domain)]
        if not people:
            return {"provider": "hunter", "method": method, "found": False}

        verified = None
        tried: dict[str, str] = {}
        for person in people[:MAX_VERIFY_PER_LEAD]:
            email = normalize_email(person.email)
            if email is None or self._is_blocked(email):
                tried[person.email] = "do_not_contact" if email else "malformed"
                continue
            status, result = self._verify(email)
            tried[email] = result
            if status is not EmailStatus.INVALID:
                verified = (person, email, status)
                break
        note: dict[str, Any] = {"provider": "hunter", "method": method, "verified": tried}
        if verified is None:
            return {**note, "found": False}
        person, email, status = verified
        contact = ContactIn(
            full_name=person.full_name,
            role=person.position,
            email=email,
            email_status=status,
            phone=person.phone_number,
            linkedin_url=person.linkedin,
            x_url=_x_url(person.twitter),
            found_via=f"hunter:{method}",
        )
        return {**note, "found": True, "contact": contact}

    def _verify(self, email: str) -> tuple[EmailStatus, str]:
        """Status and the verifier's raw verdict. Without a verifier (or after
        it stopped) the email stays unverified: only a verifier response may
        mark it valid."""
        if self.verifier is None:
            return EmailStatus.UNVERIFIED, "not_verified"
        try:
            verdict = self.verifier.verify(email)
        except ProviderStopped as exc:
            self._report_error(f"email verification stopped for this run: {exc}")
            self.verifier = None
            return EmailStatus.UNVERIFIED, "not_verified"
        if verdict is None:
            return EmailStatus.UNVERIFIED, "no_verdict"
        return verdict.status, verdict.result

    @staticmethod
    def _merge(contacts: list[ContactIn], found: ContactIn) -> list[ContactIn]:
        """Fill in the matching named contact (same name), else add the found
        one. It becomes primary unless the lead already has one."""
        primary = not any(c.is_primary for c in contacts)
        name = (found.full_name or "").lower()
        merged, matched = [], False
        for contact in contacts:
            if not matched and name and (contact.full_name or "").lower() == name:
                updates = {k: v for k, v in found.model_dump().items() if v is not None}
                updates["role"] = contact.role or found.role
                updates["is_primary"] = contact.is_primary or primary
                merged.append(contact.model_copy(update=updates))
                matched = True
            else:
                merged.append(contact)
        if not matched:
            merged.append(found.model_copy(update={"is_primary": primary}))
        return merged


def _is_buyer(role: str | None) -> bool:
    return bool(role) and any(rx.search(role or "") for rx in _TITLE_TIERS)


def _same_domain(email: str, domain: str) -> bool:
    host = email.rsplit("@", 1)[-1].lower()
    return host == domain or host.endswith(f".{domain}")
