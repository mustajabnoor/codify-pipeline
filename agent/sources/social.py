"""Social listening: public Reddit posts from people looking for a developer or
agency, or describing a broken app.

Reddit is read through its public RSS (Atom) feeds, the newest 100 posts per
subreddit, and filtered here: Reddit's search feeds proved unreliable. The
official API needs approved keys; when those exist, only `fetch_subreddit`
changes. Posts become leads named after their author (u/name) with no domain,
so they dedupe on the post URL and get no email lookup; the draft is a reply
for a human to send.

Platform (source_platforms; switched on/off in the dashboard): reddit.

Config (source_configs.config):
  subreddits            [str]  subreddit names without "r/"
  keywords              [str]  keep a post whose title or text has one
  hiring_subreddits     [str]  job-board subreddits (r/forhire): keep only
                               "[Hiring]" posts with a hiring_keywords match
  hiring_keywords       [str]  the work we sell, for hiring_subreddits
  exclude_keywords      [str]  drop a post whose title or text has one
                               (posts tagged "[For Hire]" are always dropped:
                               they offer services rather than buy them)
  max_age_days          int    ignore older posts (default 3)
  max_posts             int    new posts sent to AI per run (default 15)
  request_delay_seconds num    pause between subreddits (default 2)
"""

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import httpx
from pydantic import ValidationError

from agent.core.http import get_with_retry
from agent.core.models import LeadCandidate
from agent.core.normalize import normalize_url
from agent.core.text import has_phrase, html_to_text, truncate
from agent.sources.base import ErrorReporter, Source

PLATFORM = "reddit"
FEED_URL = "https://www.reddit.com/r/{subreddit}/new/.rss?limit=100"
PROFILE_URL = "https://www.reddit.com/user/{author}"
RAW_TEXT_LIMIT = 8000
DEFAULT_MAX_AGE_DAYS = 3
DEFAULT_MAX_POSTS = 15
DEFAULT_REQUEST_DELAY = 2.0

_ATOM = {"a": "http://www.w3.org/2005/Atom"}
_SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{2,21}$")
_AUTHOR = re.compile(r"^/?u/([A-Za-z0-9_-]{3,20})$")
# The post body sits between these markers; after them Reddit appends
# "submitted by /u/x [link] [comments]".
_BODY = re.compile(r"<!-- SC_OFF -->(.*?)<!-- SC_ON -->", re.S)
_HIRING_TAG = re.compile(r"^\s*[\[(]\s*hiring\s*[\])]", re.I)
_FOR_HIRE_TAG = re.compile(r"[\[(]\s*for\s*hire\s*[\])]", re.I)


def _iso_date(value: str | None) -> datetime | None:
    """Atom date (ISO 8601) -> aware datetime; raises ValueError on garbage."""
    if not value or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.strip())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(frozen=True)
class RedditPost:
    id: str
    subreddit: str
    title: str
    url: str
    author: str
    published_at: datetime | None
    text: str  # the post body as plain text ("" for link posts)


def parse_reddit_atom(xml: str | bytes, report: ErrorReporter | None = None) -> list[RedditPost]:
    """Posts from a subreddit's Atom feed. Entries without a link or a named
    author (deleted accounts) are skipped; a bad date is reported and left empty."""
    root = ET.fromstring(xml)
    posts = []
    for entry in root.findall("a:entry", _ATOM):
        link = entry.find("a:link", _ATOM)
        url = (link.get("href") if link is not None else None) or ""
        author = _AUTHOR.match((entry.findtext("a:author/a:name", "", _ATOM) or "").strip())
        if not url.startswith("https://") or not author:
            continue
        category = entry.find("a:category", _ATOM)
        try:
            published_at = _iso_date(entry.findtext("a:published", None, _ATOM))
        except (TypeError, ValueError):
            if report:
                report("bad published date in Reddit entry", url=url, platform=PLATFORM)
            published_at = None
        content = entry.findtext("a:content", "", _ATOM) or ""
        body = _BODY.search(content)
        posts.append(
            RedditPost(
                id=(entry.findtext("a:id", "", _ATOM) or "").strip(),
                subreddit=category.get("term", "") if category is not None else "",
                title=(entry.findtext("a:title", "", _ATOM) or "").strip(),
                url=url,
                author=author.group(1),
                published_at=published_at,
                text=html_to_text(body.group(1)) if body else "",
            )
        )
    return posts


@dataclass(frozen=True)
class PostFilter:
    """Which posts are buying signals. Cheap: runs before any AI call."""

    keywords: tuple[str, ...]
    hiring_subreddits: frozenset[str] = frozenset()
    hiring_keywords: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()
    max_age: timedelta = timedelta(days=DEFAULT_MAX_AGE_DAYS)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "PostFilter":
        days = config.get("max_age_days") or DEFAULT_MAX_AGE_DAYS
        return cls(
            keywords=tuple(config.get("keywords") or ()),
            hiring_subreddits=frozenset(s.lower() for s in config.get("hiring_subreddits") or ()),
            hiring_keywords=tuple(config.get("hiring_keywords") or ()),
            exclude_keywords=tuple(config.get("exclude_keywords") or ()),
            max_age=timedelta(days=float(days)),
        )

    def matches(self, post: RedditPost, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        if post.published_at and post.published_at < now - self.max_age:
            return False
        text = f"{post.title}\n{post.text}"
        if _FOR_HIRE_TAG.search(post.title) or has_phrase(text, self.exclude_keywords):
            return False
        if post.subreddit.lower() in self.hiring_subreddits:
            # Job boards: "[Hiring]" posts for work we sell; "[For Hire]" are offers.
            return bool(_HIRING_TAG.match(post.title)) and has_phrase(text, self.hiring_keywords)
        return has_phrase(text, self.keywords)


def to_candidate(post: RedditPost, feed: str) -> LeadCandidate:
    """A lead named after the poster. No website: Reddit leads dedupe on the
    post URL, and the contact is the poster's profile."""
    metadata = {
        "subreddit": f"r/{post.subreddit}" if post.subreddit else None,
        "posted_at": post.published_at.isoformat() if post.published_at else None,
        "feed": feed,
    }
    return LeadCandidate.model_validate(
        {
            "company_name": f"u/{post.author}",
            "signal": {
                "source": "social",
                "source_url": post.url,
                "signal_type": "reddit_post",
                "platform": PLATFORM,
                "title": post.title,
                "raw_text": truncate(post.text, RAW_TEXT_LIMIT) or None,
                "metadata": {k: v for k, v in metadata.items() if v},
            },
            "contacts": [
                {
                    "full_name": f"u/{post.author}",
                    "role": "Reddit poster",
                    "other_url": PROFILE_URL.format(author=post.author),
                    "is_primary": True,
                    "found_via": "social:reddit_post",
                }
            ],
        }
    )


class SocialListeningSource(Source):
    name = "social"
    platforms = (PLATFORM,)
    default_config: ClassVar[dict[str, Any]] = {
        "subreddits": [
            "forhire", "startups", "SaaS", "Entrepreneur", "Bubble", "lovable", "SideProject",
        ],
        "keywords": [
            "looking for a developer", "need a developer", "hire a developer",
            "looking for an agency", "bubble developer", "app is broken",
            "stripe checkout", "need help with my app",
        ],
        "hiring_subreddits": ["forhire"],
        "hiring_keywords": [
            "developer", "programmer", "engineer", "app", "website", "web site",
            "landing page", "bubble", "shopify", "wordpress", "webflow", "react",
            "next.js", "flutter", "mvp", "saas", "no-code", "nocode", "stripe",
            "full stack", "fullstack", "frontend", "backend", "ai integration",
        ],
        "exclude_keywords": ["unpaid", "equity only", "rev share", "revenue share", "for exposure"],
        "max_age_days": DEFAULT_MAX_AGE_DAYS,
        "max_posts": DEFAULT_MAX_POSTS,
        "request_delay_seconds": DEFAULT_REQUEST_DELAY,
    }  # fmt: skip
    # Tests replace it so they don't wait between subreddits.
    sleep: ClassVar[Callable[[float], None]] = staticmethod(time.sleep)

    def fetch_subreddit(self, client: httpx.Client, subreddit: str) -> tuple[str, list[RedditPost]]:
        """(feed URL, newest posts). The one place that talks to Reddit."""
        feed = FEED_URL.format(subreddit=subreddit)
        return feed, parse_reddit_atom(get_with_retry(client, feed).content, self.report_error)

    def _feed_failed(self, subreddit: str, exc: Exception) -> None:
        self.report_error(
            f"feed failed: {type(exc).__name__}: {exc}",
            feed=FEED_URL.format(subreddit=subreddit),
            platform=PLATFORM,
        )

    def collect(self, config: dict[str, Any]) -> Iterable[LeadCandidate]:
        if not self.platform_enabled(PLATFORM):
            self.log.info("platform %s is switched off; nothing to read", PLATFORM)
            return
        subreddits = [s.strip().removeprefix("r/") for s in config.get("subreddits") or []]
        if bad := [s for s in subreddits if not _SUBREDDIT.match(s)]:
            self.report_error(f"invalid subreddit names skipped: {', '.join(bad)}")
        subreddits = [s for s in subreddits if _SUBREDDIT.match(s)]
        post_filter = PostFilter.from_config(config)
        if not subreddits or not (post_filter.keywords or post_filter.hiring_subreddits):
            self.report_error("social config has no subreddits or keywords; nothing to read")
            return
        budget = int(config.get("max_posts") or DEFAULT_MAX_POSTS)
        delay = float(config.get("request_delay_seconds") or 0)
        with self.http_client() as client:
            for index, subreddit in enumerate(subreddits):
                if index and delay:
                    type(self).sleep(delay)
                try:
                    feed, posts = self.fetch_subreddit(client, subreddit)
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429:
                        # Rate limited even after backing off: stop asking this run.
                        self.report_error(
                            "Reddit rate limit (429): the remaining subreddits wait "
                            "for the next run",
                            feed=FEED_URL.format(subreddit=subreddit),
                            platform=PLATFORM,
                        )
                        return
                    self._feed_failed(subreddit, exc)
                    continue
                except (httpx.HTTPError, ET.ParseError) as exc:
                    self._feed_failed(subreddit, exc)
                    continue
                self.fetched(PLATFORM)
                fresh = [
                    p
                    for p in posts
                    if post_filter.matches(p) and not self.is_known_url(normalize_url(p.url))
                ]
                self.log.info("r/%s: %d posts, %d new matches", subreddit, len(posts), len(fresh))
                for post in fresh:
                    if budget <= 0:
                        self.log.info("max_posts reached; the rest wait for the next run")
                        return
                    budget -= 1
                    try:
                        yield to_candidate(post, feed)
                    except ValidationError as exc:
                        self.report_error(
                            f"invalid Reddit post: {exc.error_count()} error(s)",
                            url=post.url,
                            platform=PLATFORM,
                        )
