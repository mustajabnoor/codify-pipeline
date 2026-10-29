from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent import main as cli
from agent.ai.client import AIError
from agent.ai.schemas import Founder, FundingExtraction
from agent.core.config import Settings
from agent.core.db import DryRunRepository, MemoryRepository
from agent.core.errors import AgentError
from agent.core.feeds import FeedItem, parse_feed
from agent.core.models import LeadSource, RunStatus, SourceConfig
from agent.sources.funding import (
    FundingNewsSource,
    is_candidate_article,
    to_candidate,
    verified_domain,
)

from .conftest import FAKE_USAGE, FakeAI

SAMPLE = (Path(__file__).parent / "fixtures" / "funding" / "sample_feed.rss").read_bytes()
FEED = "https://news.example.com/feed/"
BAD_FEED = "https://gone.example.com/feed/"
NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
CONFIG = {**FundingNewsSource.default_config, "rss_feeds": [FEED]}
ITEMS = {item.title.split()[0].rstrip(":"): item for item in parse_feed(SAMPLE)}


def extraction(**overrides: Any) -> FundingExtraction:
    base: dict[str, Any] = {
        "is_single_announcement": True,
        "company_name": "Acme AI",
        "website": "https://acme.ai",
        "round": "seed",
        "amount": 3_000_000,
        "currency": "USD",
        "investors": ["Foo Ventures"],
        "founders": [Founder(name="Jane Roe", role="CEO and co-founder")],
        "industry": "healthtech",
        "country": "United States",
        "city": "San Francisco",
        "description": "Scheduling agents for clinics.",
        "tech_stack": [],
    }
    return FundingExtraction(**{**base, **overrides})


# What the fake extractor "reads" in each sample article, keyed by title word.
ANSWERS: dict[str, FundingExtraction] = {
    "Acme": extraction(),
    "Bolt": extraction(
        company_name="Bolt Robotics",
        website="bolt-robotics.eu",
        round="pre-seed",
        amount=2_500_000,
        currency="EUR",
        founders=[],
        city="Berlin",
        country="Germany",
    ),
    "Weekly": extraction(is_single_announcement=False, company_name=None, round=None),
    "Ghost": extraction(company_name="Ghost Co", website="ghost.co", amount=1_000_000),
}


def answer(prompt: str) -> FundingExtraction:
    title = prompt.split("\n", 1)[0].removeprefix("Title: ")
    return ANSWERS[title.split()[0]]


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("Acme", True),
        ("Bolt", True),
        ("Mega", False),  # "series b" is excluded before any AI call
        ("Weekly", True),  # passes the title filter; the extractor drops it
        ("Opinion", False),  # no funding wording
        ("Old", False),  # older than max_age_days
    ],
)
def test_title_and_age_filter(word: str, expected: bool) -> None:
    assert is_candidate_article(ITEMS[word], CONFIG, NOW) is expected


def test_verified_domain_needs_the_article_to_show_it() -> None:
    text = "Acme AI (https://www.acme.ai/) raised $3M."
    assert verified_domain(extraction(), text) == "acme.ai"
    # A bare mention counts too.
    assert (
        verified_domain(extraction(website="acme.ai"), "Acme AI (acme.ai) raised $3M.") == "acme.ai"
    )
    # Claude's website isn't in the article: rejected, never guessed.
    assert verified_domain(extraction(website="acme.com"), "Acme AI raised $3M.") is None
    # Falls back to a linked host containing the company name.
    assert (
        verified_domain(extraction(website=None), "See https://acmeai.io for more") == "acmeai.io"
    )


def test_usd_round_becomes_a_funded_lead() -> None:
    candidate = to_candidate(ITEMS["Acme"], FEED, extraction(), ["seed"])
    assert candidate is not None
    assert (candidate.company_name, candidate.domain) == ("Acme AI", "acme.ai")
    assert (candidate.funding_amount, candidate.funding_round) == (Decimal("3000000"), "seed")
    assert candidate.funding_date == datetime(2026, 10, 28).date()
    assert (candidate.country, candidate.city) == ("United States", "San Francisco")
    (jane,) = candidate.contacts
    assert (jane.full_name, jane.role, jane.email) == ("Jane Roe", "CEO and co-founder", None)
    assert jane.found_via == "funding:funding_round"
    signal = candidate.signal
    assert (signal.source, signal.signal_type) == (LeadSource.FUNDING, "funding_round")
    assert signal.source_url == "https://news.example.com/2026/10/acme-ai-raises-3m"
    assert signal.metadata["ai_prompts"] == {"extract": "funding_extract_v1"}
    assert signal.metadata["investors"] == ["Foo Ventures"]
    assert "scheduling agents" in (signal.raw_text or "")


def test_non_usd_amount_stays_in_metadata() -> None:
    candidate = to_candidate(ITEMS["Bolt"], FEED, ANSWERS["Bolt"], ["pre-seed", "seed"])
    assert candidate is not None
    assert candidate.domain == "bolt-robotics.eu"
    assert candidate.funding_amount is None
    assert (candidate.signal.metadata["amount"], candidate.signal.metadata["currency"]) == (
        2_500_000,
        "EUR",
    )


@pytest.mark.parametrize(
    "found",
    [
        extraction(is_single_announcement=False),
        extraction(company_name=None),
        extraction(round="series b"),
        extraction(round=None),
    ],
)
def test_articles_that_are_not_a_wanted_round_are_dropped(found: FundingExtraction) -> None:
    assert to_candidate(ITEMS["Acme"], FEED, found, ["pre-seed", "seed", "series a"]) is None


def run(
    monkeypatch: pytest.MonkeyPatch,
    ai: FakeAI,
    repo: MemoryRepository | None = None,
    **config: Any,
) -> tuple[RunStatus, MemoryRepository]:
    routes = {FEED: httpx.Response(200, content=SAMPLE)}
    monkeypatch.setattr(
        FundingNewsSource,
        "transport",
        httpx.MockTransport(lambda r: routes.get(str(r.url), httpx.Response(404))),
    )
    repo = repo or MemoryRepository()
    # Sample articles are dated October 2026; keep them in the age window.
    full = {**CONFIG, "max_age_days": 36500, **config}
    full["exclude_keywords"] = [*full["exclude_keywords"], "old co"]
    repo.source_configs = [SourceConfig(source=LeadSource.FUNDING, name="default", config=full)]
    status = cli.run_source(
        "funding", settings=Settings(_env_file=None), repo=repo, dry_run=False, ai=ai
    )
    return status, repo


def test_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    ai = FakeAI(answers={"funding_extract": answer})
    status, repo = run(monkeypatch, ai)

    assert status is RunStatus.SUCCESS
    leads = sorted((lead["company_name"], lead["domain"]) for lead in repo.leads.values())
    # Ghost Co: the article never shows ghost.co, so it has no domain.
    assert leads == [
        ("Acme AI", "acme.ai"),
        ("Bolt Robotics", "bolt-robotics.eu"),
        ("Ghost Co", None),
    ]
    # 4 articles read (Acme, Bolt, Weekly, Ghost); the generic
    # extract step is skipped for them; 3 new leads scored and drafted.
    assert ai.tasks.count("funding_extract") == 4
    assert "extract" not in ai.tasks
    assert (ai.tasks.count("score"), ai.tasks.count("draft")) == (3, 3)
    acme = next(lead for lead in repo.leads.values() if lead["domain"] == "acme.ai")
    assert (acme["funding_round"], acme["fit_score"], acme["first_source"]) == (
        "seed",
        7,
        "funding",
    )
    signal = repo.signals["https://news.example.com/2026/10/acme-ai-raises-3m"]
    assert signal["metadata"]["ai_prompts"] == {
        "extract": "funding_extract_v1",
        "score": "score_v2",
        "draft": "draft_v1",
    }
    (run_row,) = repo.runs.values()
    assert run_row["tokens_used"] == 10 * FAKE_USAGE.tokens


def test_known_articles_are_not_read_again(monkeypatch: pytest.MonkeyPatch) -> None:
    _, repo = run(monkeypatch, FakeAI(answers={"funding_extract": answer}))
    second = FakeAI(answers={"funding_extract": answer})
    run(monkeypatch, second, repo)
    # Only the article that didn't become a lead (the roundup) is read again.
    assert second.tasks == ["funding_extract"]


def test_max_articles_caps_ai_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    ai = FakeAI(answers={"funding_extract": answer})
    run(monkeypatch, ai, max_articles=2)
    assert ai.tasks.count("funding_extract") == 2


def test_failed_extraction_skips_that_article(monkeypatch: pytest.MonkeyPatch) -> None:
    def flaky(prompt: str) -> FundingExtraction:
        if "Bolt Robotics" in prompt:
            raise AIError("model declined", FAKE_USAGE)
        return answer(prompt)

    status, repo = run(monkeypatch, FakeAI(answers={"funding_extract": flaky}))
    assert status is RunStatus.PARTIAL
    assert "Bolt Robotics" not in {lead["company_name"] for lead in repo.leads.values()}
    (run_row,) = repo.runs.values()
    assert "article extraction failed" in run_row["errors"][0]["message"]


def test_feed_failure_is_recorded_and_others_run(monkeypatch: pytest.MonkeyPatch) -> None:
    status, repo = run(
        monkeypatch, FakeAI(answers={"funding_extract": answer}), rss_feeds=[BAD_FEED, FEED]
    )
    assert status is RunStatus.PARTIAL
    assert len(repo.leads) == 3
    (run_row,) = repo.runs.values()
    assert run_row["errors"][0]["context"] == {"feed": BAD_FEED}


def test_no_feeds_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    status, repo = run(monkeypatch, FakeAI(), rss_feeds=[])
    assert status is RunStatus.FAILED
    (run_row,) = repo.runs.values()
    assert "rss_feeds" in run_row["errors"][0]["message"]


def test_needs_ai_even_in_dry_runs() -> None:
    with pytest.raises(AgentError, match="needs AI"):
        cli.run_source(
            "funding", settings=Settings(_env_file=None), repo=DryRunRepository(), dry_run=True
        )
    assert cli.main(["run", "funding", "--dry-run", "--no-ai"]) == 2


def test_feed_item_without_date_is_kept() -> None:
    item = FeedItem("Acme raises seed", "https://n.example.com/1", None, "")
    assert is_candidate_article(item, CONFIG, NOW)
