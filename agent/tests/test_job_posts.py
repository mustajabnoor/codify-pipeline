import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent import main as cli
from agent.core.config import Settings
from agent.core.db import MemoryRepository
from agent.core.models import LeadSource, RunStatus, SourceConfig
from agent.sources.job_posts import (
    REMOTEOK_API,
    Filters,
    JobPost,
    JobPostingsSource,
    parse_remoteok,
    parse_rss,
    to_candidate,
)

from .conftest import FakeAI

FIXTURES = Path(__file__).parent / "fixtures" / "job_posts"
REMOTEOK_JSON = json.loads((FIXTURES / "remoteok_api.json").read_text())
WWR_RSS = (FIXTURES / "wwr_full_stack.rss").read_bytes()
WWR_FEED = "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss"
NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
FILTERS = Filters(
    title_keywords=tuple(JobPostingsSource.default_config["title_keywords"]),
    exclude_keywords=("unpaid",),
)


class Errors:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, message: str, **context: Any) -> None:
        self.calls.append((message, context))


def post(title: str, **kwargs: Any) -> JobPost:
    return JobPost(
        board="rss", company="Acme", title=title, url="https://jobs.example.com/1", **kwargs
    )


def test_parse_remoteok() -> None:
    posts = parse_remoteok(REMOTEOK_JSON)
    assert [p.company for p in posts] == [
        "Huzzle",
        "B2spin",
        "Sotheby\u2019s",  # double-encoded UTF-8 repaired
        "Somnio Software",
        "Lemon.io",
    ]
    b2spin = posts[1]
    assert b2spin.title == "Senior Frontend Engineer"
    assert b2spin.url.startswith("https://remoteOK.com/remote-jobs/")
    assert b2spin.posted_at == datetime(2026, 10, 23, 16, 0, 12, tzinfo=UTC)
    assert "front end" in b2spin.tags
    # RemoteOK's per-requester anti-spam line is stripped.
    assert "Please mention the word" not in b2spin.description_html


def test_parse_remoteok_rejects_non_list() -> None:
    with pytest.raises(ValueError, match="list"):
        parse_remoteok({"error": "rate limited"})


def test_parse_remoteok_reports_bad_items() -> None:
    errors = Errors()
    posts = parse_remoteok([{"id": "1", "position": "React Dev", "url": "https://x.io/1"}], errors)
    assert posts == []
    assert errors.calls[0][1] == {"id": "1"}


def test_parse_rss_wwr() -> None:
    posts = parse_rss(WWR_RSS)
    assert [(p.company, p.title) for p in posts] == [
        ("Salesloft", "HR Enablement Lead"),
        ("Vested, Inc.", "Senior Software Engineer"),
        ("Proxify AB", "Senior Fullstack Developer (React.js / Node.js)"),
    ]
    salesloft = posts[0]
    assert salesloft.board == "weworkremotely"
    assert salesloft.details["country"] == "United States of America"  # flag emoji dropped
    assert salesloft.details["employment_type"] == "Full-Time"
    assert salesloft.posted_at == datetime(2026, 10, 29, 7, 30, 57, tzinfo=UTC)


def test_parse_rss_skips_items_without_company_and_reports_bad_dates() -> None:
    xml = """<rss><channel>
      <item><title>Just a title</title><link>https://feed.example.com/1</link></item>
      <item><title>Acme: React Developer</title><link>https://feed.example.com/2</link>
            <pubDate>not a date</pubDate></item>
    </channel></rss>"""
    errors = Errors()
    (only,) = parse_rss(xml, errors)
    assert (only.company, only.title, only.posted_at, only.board) == (
        "Acme",
        "React Developer",
        None,
        "rss",
    )
    assert errors.calls == [("bad pubDate in RSS item", {"url": "https://feed.example.com/2"})]


def test_dates_without_offset_are_utc() -> None:
    (rss,) = parse_rss(
        "<rss><channel><item><title>Acme: React Dev</title><link>https://f.example.com/1</link>"
        "<pubDate>Wed, 28 Oct 2026 07:31:13 -0000</pubDate></item></channel></rss>"
    )
    (api,) = parse_remoteok(
        [
            {
                "company": "Acme",
                "position": "React Dev",
                "url": "https://x.io/1",
                "date": "2026-10-28T07:31:13",
            }
        ]
    )
    for parsed in (rss, api):
        assert parsed.posted_at == datetime(2026, 10, 28, 7, 31, 13, tzinfo=UTC)
        assert FILTERS.matches(parsed, now=NOW)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Sr REACT NATIVE", True),
        ("Senior Fullstack Developer (React.js / Node.js)", True),
        ("Front-End Developer", True),
        ("Bubble.io Developer (contract)", True),
        ("iOS Engineer", True),
        ("Web Developer: WordPress & HubSpot", True),
        ("Next.js Engineer", True),
        ("HR Enablement Lead", False),
        ("Senior Software Engineer", False),
        ("Studios Operations Manager", False),  # "ios" must start a word
    ],
)
def test_title_filter(title: str, expected: bool) -> None:
    assert FILTERS.matches(post(title), now=NOW) is expected


def test_filter_excludes_keywords_in_text() -> None:
    unpaid = post("React Developer", description_html="<p>This role is <b>unpaid</b>.</p>")
    assert not FILTERS.matches(unpaid, now=NOW)


def test_filter_drops_old_posts_keeps_undated() -> None:
    filters = Filters(title_keywords=("react",), max_age=timedelta(days=30))
    assert filters.matches(post("React Dev", posted_at=NOW - timedelta(days=29)), now=NOW)
    assert not filters.matches(post("React Dev", posted_at=NOW - timedelta(days=31)), now=NOW)
    assert filters.matches(post("React Dev"), now=NOW)


def test_filters_from_config_defaults() -> None:
    filters = Filters.from_config({"title_keywords": ["react"]})
    assert filters.max_age == timedelta(days=30)
    assert filters.exclude_keywords == ()


def test_to_candidate_guesses_domain_from_description() -> None:
    proxify, vested = parse_rss(WWR_RSS)[2], parse_rss(WWR_RSS)[1]
    candidate = to_candidate(proxify, WWR_FEED)
    assert candidate.company_name == "Proxify AB"
    assert candidate.domain == "proxify.io"  # linked as career.proxify.io
    assert to_candidate(vested, WWR_FEED).domain == "vested.co"
    signal = candidate.signal
    assert signal.source is LeadSource.JOB_POSTING
    assert signal.signal_type == "job_post"
    assert signal.title == "Senior Fullstack Developer (React.js / Node.js)"
    assert signal.raw_text and "<" not in signal.raw_text
    assert signal.metadata["board"] == "weworkremotely"
    assert signal.metadata["feed"] == WWR_FEED
    assert signal.metadata["posted_at"] == "2026-10-19T09:29:00+00:00"


def test_to_candidate_without_domain() -> None:
    b2spin = parse_remoteok(REMOTEOK_JSON)[1]
    candidate = to_candidate(b2spin, REMOTEOK_API)
    assert candidate.domain is None and candidate.website is None
    # source_url is normalized (lowercase host) for dedupe.
    assert candidate.signal.source_url.startswith("https://remoteok.com/remote-jobs/")


BAD_FEED = "https://feeds.example.com/gone.rss"


def mock_transport(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return httpx.MockTransport(handler)


@pytest.fixture
def feeds(monkeypatch: pytest.MonkeyPatch) -> None:
    routes = {
        REMOTEOK_API: httpx.Response(200, json=REMOTEOK_JSON),
        WWR_FEED: httpx.Response(200, content=WWR_RSS),
    }
    monkeypatch.setattr(JobPostingsSource, "transport", mock_transport(routes))


def run(config: dict[str, Any]) -> tuple[RunStatus, MemoryRepository]:
    repo = MemoryRepository()
    repo.source_configs = [
        SourceConfig(source=LeadSource.JOB_POSTING, name="default", config=config)
    ]
    status = cli.run_source(
        "job_posting", settings=Settings(_env_file=None), repo=repo, dry_run=False, ai=FakeAI()
    )
    return status, repo


def config(**overrides: Any) -> dict[str, Any]:
    # Fixtures are dated October 2026; keep them all in the age window.
    return {**JobPostingsSource.default_config, "max_age_days": 36500, **overrides}


@pytest.mark.usefixtures("feeds")
def test_collect_end_to_end() -> None:
    status, repo = run(config(rss_feeds=[WWR_FEED, BAD_FEED]))

    assert status is RunStatus.PARTIAL  # one feed failed, the rest went through
    companies = sorted((lead["company_name"], lead["domain"]) for lead in repo.leads.values())
    assert companies == [
        ("B2spin", None),
        ("Lemon.io", "lemon.io"),
        ("Proxify AB", "proxify.io"),
        ("Somnio Software", None),
    ]
    assert {s["source"] for s in repo.signals.values()} == {"job_posting"}
    (run_row,) = repo.runs.values()
    assert (run_row["items_seen"], run_row["leads_new"]) == (4, 4)
    (error,) = run_row["errors"]
    assert error["context"] == {"feed": BAD_FEED}
    assert "404" in error["message"]


@pytest.mark.usefixtures("feeds")
def test_rerun_skips_known_posts() -> None:
    _, repo = run(config(rss_feeds=[WWR_FEED]))
    cli.run_source(
        "job_posting", settings=Settings(_env_file=None), repo=repo, dry_run=False, ai=FakeAI()
    )
    second = list(repo.runs.values())[1]
    assert (second["leads_new"], second["leads_skipped"]) == (0, 4)


@pytest.mark.usefixtures("feeds")
def test_all_feeds_failing_fails_the_run() -> None:
    status, repo = run(config(remoteok=False, rss_feeds=[BAD_FEED]))
    assert status is RunStatus.FAILED
    assert repo.leads == {}


@pytest.mark.usefixtures("feeds")
def test_config_without_title_keywords_fails_clearly() -> None:
    status, repo = run(config(title_keywords=[]))
    assert status is RunStatus.FAILED
    (run_row,) = repo.runs.values()
    assert "title_keywords" in run_row["errors"][0]["message"]
