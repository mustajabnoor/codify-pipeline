from agent.core.db import MemoryRepository
from agent.core.dedupe import Action, decide

from .conftest import make_candidate


def test_new_company_creates_lead(repo: MemoryRepository) -> None:
    assert decide(make_candidate(), repo).action is Action.CREATE_LEAD


def test_known_domain_from_new_source_adds_signal(repo: MemoryRepository) -> None:
    lead_id = repo.create_lead(make_candidate())
    other = make_candidate(
        website="https://www.acme.com/", source="funding", url="https://news.example.com/acme"
    )
    decision = decide(other, repo)
    assert decision.action is Action.ADD_SIGNAL
    assert decision.lead_id == lead_id


def test_known_source_url_is_skipped(repo: MemoryRepository) -> None:
    repo.create_lead(make_candidate())
    assert decide(make_candidate(), repo).action is Action.SKIP_KNOWN_SIGNAL


def test_lead_without_domain_dedupes_on_source_url(repo: MemoryRepository) -> None:
    post = make_candidate(
        company="u/someone", website=None, source="social", url="https://reddit.com/r/x/1"
    )
    assert decide(post, repo).action is Action.CREATE_LEAD
    repo.create_lead(post)
    assert decide(post, repo).action is Action.SKIP_KNOWN_SIGNAL
    other_post = make_candidate(
        company="u/someone", website=None, source="social", url="https://reddit.com/r/x/2"
    )
    assert decide(other_post, repo).action is Action.CREATE_LEAD


def test_do_not_contact_domain(repo: MemoryRepository) -> None:
    repo.dnc_domains.add("acme.com")
    assert decide(make_candidate(), repo).action is Action.SKIP_DO_NOT_CONTACT


def test_do_not_contact_email(repo: MemoryRepository) -> None:
    repo.dnc_emails.add("dana@acme.com")
    c = make_candidate(contacts=[{"email": "Dana@acme.com"}])
    assert decide(c, repo).action is Action.SKIP_DO_NOT_CONTACT


def test_do_not_contact_matches_contact_email_domain(repo: MemoryRepository) -> None:
    repo.dnc_domains.add("acme.com")
    c = make_candidate(website=None, contacts=[{"email": "dana@acme.com"}])
    assert decide(c, repo).action is Action.SKIP_DO_NOT_CONTACT


def test_do_not_contact_wins_over_existing_lead(repo: MemoryRepository) -> None:
    repo.create_lead(make_candidate())
    repo.dnc_domains.add("acme.com")
    other = make_candidate(url="https://jobs.example.com/2")
    assert decide(other, repo).action is Action.SKIP_DO_NOT_CONTACT
