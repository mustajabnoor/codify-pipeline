"""The AI step for a new lead: extract company facts (cheap model), score the
fit, and draft the first message unless the lead is a reject."""

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from agent.ai.client import AIClient, AIError
from agent.ai.schemas import Assessment, Draft, Extraction
from agent.core.models import ContactIn, LeadAssessment, LeadCandidate, OutreachDraft
from agent.core.text import truncate

PROMPTS_DIR = Path(__file__).parent / "prompts"
# Bump the version (new file) when a prompt changes; it is saved on each signal.
EXTRACT_PROMPT = "extract_v1"
SCORE_PROMPT = "score_v2"
DRAFT_PROMPT = "draft_v1"
TEXT_LIMIT = 6000

UsageRecorder = Callable[[int, Decimal], None]
# Signal metadata that is bookkeeping, not information about the lead.
_BRIEF_SKIP = frozenset({"ai_prompts", "feed"})
T = TypeVar("T", bound=BaseModel)


def load_prompt(name: str) -> str:
    text = (PROMPTS_DIR / f"{name}.md").read_text()
    profile = (PROMPTS_DIR / "company_profile.md").read_text().strip()
    return text.replace("{company_profile}", profile).strip()


def _lines(pairs: list[tuple[str, object]]) -> str:
    return "\n".join(f"{label}: {value}" for label, value in pairs if value not in (None, "", []))


def signal_brief(candidate: LeadCandidate) -> str:
    signal = candidate.signal
    head = _lines(
        [
            ("Company", candidate.company_name),
            ("Website", candidate.website or "unknown"),
            ("Signal", f"{signal.source.value} / {signal.signal_type}: {signal.title or ''}"),
            ("Source URL", signal.source_url),
            *(
                (k.replace("_", " ").capitalize(), v)
                for k, v in sorted(signal.metadata.items())
                if k not in _BRIEF_SKIP
            ),
        ]
    )
    text = truncate(signal.raw_text or "", TEXT_LIMIT)
    return f"{head}\n\n<signal_text>\n{text}\n</signal_text>"


def lead_brief(candidate: LeadCandidate) -> str:
    facts = _lines(
        [
            ("Industry", candidate.industry),
            ("Country", candidate.country),
            ("City", candidate.city),
            ("Company size", candidate.company_size),
            ("About", candidate.description),
            ("Tech stack", ", ".join(candidate.tech_stack)),
            ("Funding", candidate.funding_amount and f"{candidate.funding_amount} USD"),
            ("Funding round", candidate.funding_round),
            ("Funding date", candidate.funding_date),
        ]
    )
    return f"{signal_brief(candidate)}\n\n{facts}".strip()


def draft_brief(candidate: LeadCandidate, assessment: LeadAssessment) -> str:
    contact = next((c for c in candidate.contacts if c.is_primary), None) or next(
        (c for c in candidate.contacts if c.full_name), None
    )
    who = (
        f"{contact.full_name}" + (f" ({contact.role})" if contact.role else "")
        if contact and contact.full_name
        else "none known"
    )
    scoring = _lines(
        [
            ("Fit score", f"{assessment.fit_score}/10"),
            ("Why", assessment.score_reason),
            ("Pain point", assessment.pain_point),
            ("Matching services", ", ".join(s.value for s in assessment.service_fit)),
            ("Contact", who),
            ("Contact email known", "yes" if candidate.emails else "no"),
        ]
    )
    return f"{lead_brief(candidate)}\n\n{scoring}"


def apply_extraction(candidate: LeadCandidate, extraction: Extraction) -> LeadCandidate:
    """Fill fields the collector left blank; never overwrite collected data."""
    updates: dict[str, object] = {}
    for field in ("industry", "country", "city", "company_size", "description"):
        value = getattr(extraction, field)
        if getattr(candidate, field) is None and value and value.strip():
            updates[field] = value.strip()
    if not candidate.tech_stack and extraction.tech_stack:
        stack = {t.strip().lower() for t in extraction.tech_stack if t.strip()}
        updates["tech_stack"] = sorted(stack)
    known = {c.full_name.strip().lower() for c in candidate.contacts if c.full_name}
    people = []
    for person in extraction.people:
        name = person.name.strip()
        if name and name.lower() not in known:
            known.add(name.lower())
            found_via = f"{candidate.source.value}:{candidate.signal.signal_type}"
            people.append(ContactIn(full_name=name, role=person.role, found_via=found_via))
    if people:
        updates["contacts"] = [*candidate.contacts, *people]
    return candidate.model_copy(update=updates)


class Assessor:
    """Runs the AI steps. The pipeline calls it on each candidate about to
    become a new lead; sources that must read their items with AI first (e.g.
    funding news) call `run` directly."""

    def __init__(self, ai: AIClient, record_usage: UsageRecorder) -> None:
        self.ai = ai
        self._record = record_usage
        self._prompts: dict[str, str] = {}

    def run(self, task: str, prompt: str, user: str, output: type[T]) -> T:
        """One AI call; tokens are recorded whether it succeeds or not."""
        if prompt not in self._prompts:
            self._prompts[prompt] = load_prompt(prompt)
        try:
            result, usage = self.ai.structured(
                task, system=self._prompts[prompt], user=user, output=output
            )
        except AIError as exc:
            self._record(exc.usage.tokens, exc.usage.cost)
            raise
        self._record(usage.tokens, usage.cost)
        return result

    def __call__(self, candidate: LeadCandidate) -> LeadCandidate:
        prompts = dict(candidate.signal.metadata.get("ai_prompts") or {})
        # Sources that already extracted with AI (funding news) skip this step.
        if "extract" not in prompts:
            extraction = self.run("extract", EXTRACT_PROMPT, signal_brief(candidate), Extraction)
            candidate = apply_extraction(candidate, extraction)
            prompts["extract"] = EXTRACT_PROMPT
        assessment = self.run("score", SCORE_PROMPT, lead_brief(candidate), Assessment)
        prompts["score"] = SCORE_PROMPT
        outreach = None
        if not assessment.is_reject:
            draft = self.run("draft", DRAFT_PROMPT, draft_brief(candidate, assessment), Draft)
            outreach = OutreachDraft(
                channel=draft.best_channel, subject=draft.subject, body=draft.body
            )
            prompts["draft"] = DRAFT_PROMPT
        signal = candidate.signal.model_copy(
            update={"metadata": {**candidate.signal.metadata, "ai_prompts": prompts}}
        )
        return candidate.model_copy(
            update={"signal": signal, "assessment": assessment, "outreach": outreach}
        )
