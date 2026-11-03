"""Social listening (Reddit RSS): parsing, filters, candidates and full runs
against saved feeds. The fixtures are invented posts in Reddit's Atom format."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent import main as cli
from agent.core.config import Settings
from agent.core.db import MemoryRepository, PlatformRow
from agent.core.models import LeadSource, RunStatus, SourceConfig
from agent.core.normalize import normalize_url
from agent.sources.social import (
    FEED_URL,
    PostFilter,
    RedditPost,
    SocialListeningSource,
    parse_reddit_atom,
    to_candidate,
)

from .conftest import FakeAI

FIXTURES = Path(__file__).parent / "fixtures" / "social"
FORHIRE = (FIXTURES / "forhire_new.atom").read_bytes()
STARTUPS = (FIXTURES / "startups_new.atom").read_bytes()
FORHIRE_FEED = FEED_URL.format(subreddit="forhire")
STARTUPS_FEED = FEED_URL.format(subreddit="startups")
NOW = datetime(2026, 11, 3, 8, tzinfo=UTC)
FILTER = PostFilter.from_config(SocialListeningSource.default_config)


def titles(posts: list[RedditPost]) -> list[str]:
    return [p.title for p in posts]


def test_parse_reddit_atom() -> None:
    posts = parse_reddit_atom(FORHIRE)
    # The entry from a deleted account (no author) is skipped.
    assert len(posts) == 5
    bubble = posts[0]
    assert bubble.id == "t3_1xa0001"
    assert bubble.subreddit == "forhire"
    assert bubble.author == "bluefinch_ops"
    assert (
        bubble.url
        == "https://www.reddit.com/r/forhire/comments/1xa0001/hiring_bubble_developer_to_fix_stripe_connect/"
    )
    assert bubble.published_at == datetime(2026, 11, 3, 6, 10, tzinfo=UTC)
    assert bubble.text.startswith("We run a two-sided rental marketplace built on Bubble.")
    assert "We're Bluefinch Rentals" in bubble.text  # entities decoded
    # Reddit's "submitted by /u/x [link] [comments]" footer is not post text.
    assert "submitted by" not in bubble.text and "[comments]" not in bubble.text


def test_link_post_has_no_text() -> None:
    link_post = parse_reddit_atom(STARTUPS)[-1]
    assert link_post.title == "Need a developer? Our launch page"
    assert link_post.text == ""


def test_bad_date_is_reported_not_fatal() -> None:
    xml = FORHIRE.replace(b"<published>2026-11-03T06:10:00+00:00", b"<published>yesterday", 1)
    errors: list[str] = []
    posts = parse_reddit_atom(xml, lambda message, **_: errors.append(message))
    assert posts[0].published_at is None and len(errors) == 1


def test_forhire_keeps_hiring_posts_for_our_work() -> None:
    kept = [p for p in parse_reddit_atom(FORHIRE) if FILTER.matches(p, NOW)]
    # Dropped: [For Hire] offer, a video-editing job (not our work), a post
    # older than max_age_days.
    assert titles(kept) == [
        "[Hiring] Bubble developer to fix Stripe Connect payouts in our marketplace",
        "[HIRING] Shopify developer to speed up our store",
    ]


def test_other_subreddits_need_a_keyword() -> None:
    kept = [p for p in parse_reddit_atom(STARTUPS) if FILTER.matches(p, NOW)]
    # Dropped: a pricing question (no keyword), a [For Hire] pitch that uses
    # the keywords, and nothing else; the link post matches on its title.
    assert titles(kept) == [
        "Looking for a developer to build our MVP (pre-seed, have budget)",
        "Our app is broken after an update and the freelancer vanished",
        "Need a developer? Our launch page",
    ]


def test_exclude_keywords() -> None:
    post_filter = PostFilter.from_config(
        {**SocialListeningSource.default_config, "exclude_keywords": ["pre-seed"]}
    )
    kept = [p for p in parse_reddit_atom(STARTUPS) if post_filter.matches(p, NOW)]
    assert "Looking for a developer to build our MVP (pre-seed, have budget)" not in titles(kept)


def test_for_hire_wording_in_a_hiring_post_is_fine() -> None:
    post = RedditPost(
        id="t3_x",
        subreddit="startups",
        title="Need a developer, agencies for hire welcome",
        url="https://www.reddit.com/r/startups/comments/x/y/",
        author="someone",
        published_at=NOW,
        text="",
    )
    assert FILTER.matches(post, NOW)


def test_to_candidate() -> None:
    post = parse_reddit_atom(FORHIRE)[0]
    candidate = to_candidate(post, FORHIRE_FEED)
    assert candidate.company_name == "u/bluefinch_ops"
    assert candidate.domain is None and candidate.website is None
    signal = candidate.signal
    assert signal.source is LeadSource.SOCIAL
    assert signal.signal_type == "reddit_post"
    assert signal.platform == "reddit"
    assert signal.source_url == normalize_url(post.url)  # as dedupe compares it
    assert signal.metadata == {
        "subreddit": "r/forhire",
        "posted_at": "2026-11-03T06:10:00+00:00",
        "feed": FORHIRE_FEED,
    }
    (contact,) = candidate.contacts
    assert contact.full_name == "u/bluefinch_ops" and contact.is_primary
    assert contact.other_url == "https://www.reddit.com/user/bluefinch_ops"
    assert contact.email is None
    assert candidate.lead_row()["source_platform"] == "reddit"


# Full runs ------------------------------------------------------------------


@pytest.fixture
def requested(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Serve the saved feeds (other subreddits 404); record requested URLs."""
    urls: list[str] = []
    routes = {
        FORHIRE_FEED: httpx.Response(200, content=FORHIRE),
        STARTUPS_FEED: httpx.Response(200, content=STARTUPS),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return routes.get(str(request.url), httpx.Response(404))

    monkeypatch.setattr(SocialListeningSource, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(SocialListeningSource, "sleep", lambda _seconds: None)
    return urls


def social_config(**overrides: Any) -> dict[str, Any]:
    # Fixtures are dated November 2026; keep them all in the age window.
    return {
        **SocialListeningSource.default_config,
        "subreddits": ["forhire", "startups"],
        "max_age_days": 36500,
        **overrides,
    }


def run(config: dict[str, Any], *, reddit_on: bool | None = True, ai: FakeAI | None = None):
    repo = MemoryRepository()
    repo.source_configs = [SourceConfig(source=LeadSource.SOCIAL, name="default", config=config)]
    if reddit_on is not None:
        repo.platforms = [PlatformRow("reddit", "social", reddit_on)]
    status = cli.run_source(
        "social", settings=Settings(_env_file=None), repo=repo, dry_run=False, ai=ai or FakeAI()
    )
    return status, repo


@pytest.mark.usefixtures("requested")
def test_run_end_to_end() -> None:
    status, repo = run(social_config())
    assert status is RunStatus.SUCCESS
    leads = sorted(lead["company_name"] for lead in repo.leads.values())
    # The old [Hiring] post is in the window here (max_age_days is huge).
    assert leads == [
        "u/bluefinch_ops",
        "u/linkposter",
        "u/maya_builds",
        "u/oakandiron_shop",
        "u/oldpost_owner",
        "u/stuck_founder_22",
    ]
    assert all(
        lead["source_platform"] == "reddit" and lead["domain"] is None
        for lead in repo.leads.values()
    )
    assert all(lead["fit_score"] == 7 for lead in repo.leads.values())  # scored by AI
    assert len(repo.outreach) == 6
    # The draft goes to the poster (their profile is the contact).
    contact_ids = {c["id"] for c in repo.contacts if c["full_name"].startswith("u/")}
    assert {o["contact_id"] for o in repo.outreach} <= contact_ids
    (platform_run,) = repo.platform_runs
    assert (platform_run.key, platform_run.status, platform_run.leads_new) == (
        "reddit",
        RunStatus.SUCCESS,
        6,
    )


@pytest.mark.usefixtures("requested")
def test_second_run_skips_known_posts_without_ai() -> None:
    _, repo = run(social_config())
    ai = FakeAI()
    status = cli.run_source(
        "social", settings=Settings(_env_file=None), repo=repo, dry_run=False, ai=ai
    )
    assert status is RunStatus.SUCCESS
    assert ai.calls == []
    (_, second) = repo.runs.values()
    assert second["items_seen"] == 0


@pytest.mark.usefixtures("requested")
def test_max_posts_caps_ai_work() -> None:
    _, repo = run(social_config(max_posts=2))
    assert len(repo.leads) == 2


def test_reddit_switched_off_reads_nothing(requested: list[str]) -> None:
    status, repo = run(social_config(), reddit_on=False)
    assert status is RunStatus.SUCCESS
    assert requested == [] and repo.runs == {}


def test_feed_failure_marks_platform(requested: list[str]) -> None:
    status, repo = run(social_config(subreddits=["forhire", "gone_sub"]))
    assert status is RunStatus.PARTIAL
    assert requested[-1] == FEED_URL.format(subreddit="gone_sub")
    (platform_run,) = repo.platform_runs
    assert platform_run.status is RunStatus.PARTIAL  # forhire worked, gone_sub didn't
    (row,) = repo.runs.values()
    assert row["errors"][0]["context"] == {
        "feed": FEED_URL.format(subreddit="gone_sub"),
        "platform": "reddit",
    }


def test_invalid_subreddit_names_are_skipped(requested: list[str]) -> None:
    run(social_config(subreddits=["forhire", "../evil", "r/startups"]))
    assert requested == [FORHIRE_FEED, STARTUPS_FEED]


def test_pauses_between_subreddits(requested: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    pauses: list[float] = []
    monkeypatch.setattr(SocialListeningSource, "sleep", pauses.append)
    run(social_config(request_delay_seconds=3))
    assert pauses == [3.0]


def test_ai_off_saves_unscored_reddit_leads(requested: list[str]) -> None:
    repo = MemoryRepository()
    repo.source_configs = [
        SourceConfig(source=LeadSource.SOCIAL, name="default", config=social_config())
    ]
    repo.platforms = [PlatformRow("reddit", "social", True)]
    repo.ai_on = False
    ai = FakeAI()
    cli.run_source("social", settings=Settings(_env_file=None), repo=repo, dry_run=False, ai=ai)
    assert ai.calls == [] and repo.leads
    assert all(lead.get("fit_score") is None for lead in repo.leads.values())


def test_rate_limit_stops_the_run_early(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(429)

    monkeypatch.setattr(SocialListeningSource, "transport", httpx.MockTransport(handler))
    monkeypatch.setattr(SocialListeningSource, "sleep", lambda _seconds: None)
    monkeypatch.setattr("agent.core.http.time.sleep", lambda _seconds: None)
    status, repo = run(social_config())
    assert status is RunStatus.FAILED
    # Only the first subreddit was asked (with retries); startups never was.
    assert set(urls) == {FORHIRE_FEED}
    (row,) = repo.runs.values()
    assert len(row["errors"]) == 1 and "rate limit" in row["errors"][0]["message"]
    (platform_run,) = repo.platform_runs
    assert platform_run.status is RunStatus.FAILED
