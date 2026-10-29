import logging

from agent.core.db import Repository
from agent.core.dedupe import Action, Decision, decide
from agent.core.errors import DuplicateLeadError, DuplicateSignalError
from agent.core.models import LeadCandidate
from agent.core.runs import RunRecorder

log = logging.getLogger(__name__)


def process_candidate(candidate: LeadCandidate, repo: Repository, run: RunRecorder) -> Action:
    """Dedupe one candidate and store it. Enrichment, scoring and drafting slot in
    before the write in Phase 2."""
    decision = decide(candidate, repo)
    try:
        if decision.action is Action.CREATE_LEAD:
            try:
                repo.create_lead(candidate)
            except DuplicateLeadError:
                # Another run inserted this domain since we looked; decide again.
                decision = decide(candidate, repo)
                if decision.action is not Action.ADD_SIGNAL:
                    raise
                assert decision.lead_id is not None
                repo.add_signal(decision.lead_id, candidate)
        elif decision.action is Action.ADD_SIGNAL:
            assert decision.lead_id is not None
            repo.add_signal(decision.lead_id, candidate)
    except DuplicateSignalError:
        # Stored by another run between our lookup and the insert.
        decision = Decision(Action.SKIP_KNOWN_SIGNAL)

    match decision.action:
        case Action.CREATE_LEAD:
            run.stats.leads_new += 1
        case Action.ADD_SIGNAL:
            run.stats.leads_updated += 1
        case _:
            run.stats.leads_skipped += 1
    log.debug("%s %s %s", decision.action, candidate.domain, candidate.signal.source_url)
    return decision.action
