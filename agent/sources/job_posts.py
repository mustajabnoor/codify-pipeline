"""Job postings: companies hiring for work we sell (Bubble, Shopify, React,
full-stack, mobile...). Boards: RemoteOK's JSON API and RSS feeds in We Work
Remotely's format ("Company: Position" titles).

Config (source_configs.config):
  remoteok          bool       read https://remoteok.com/api
  rss_feeds         [url]      WWR-style RSS feeds
  title_keywords    [str]      keep a post if its title has one (board tags are
                               too noisy to match on; they go in metadata)
  exclude_keywords  [str]      drop a post if its title or text has one
  max_age_days      int        drop older posts (default 30)
  job_titles        [str]      search queries for the Apify job actors (later)
"""

import html
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar

import httpx
from pydantic import ValidationError

from agent.core.http import get_with_retry
from agent.core.models import LeadCandidate
from agent.core.normalize import company_domain_from_text
from agent.core.text import fix_mojibake, html_to_text, truncate
from agent.sources.base import ErrorReporter, Source

REMOTEOK_API = "https://remoteok.com/api"
# RemoteOK appends an anti-spam line with a per-requester tag to every post.
_REMOTEOK_SPAM_LINE = re.compile(r"Please mention the word\b.*", re.S)
RAW_TEXT_LIMIT = 8000
DEFAULT_MAX_AGE_DAYS = 30


@dataclass(frozen=True)
class JobPost:
    board: str
    company: str
    title: str
    url: str
    description_html: str = ""
    posted_at: datetime | None = None
    tags: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)  # location, salary, ...


def _clean(value: Any) -> str:
    return html.unescape(str(value or "")).strip()


def _aware(value: datetime) -> datetime:
    # A feed date without an offset is taken as UTC so it compares with now().
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _report(report: ErrorReporter | None, message: str, **context: Any) -> None:
    if report:
        report(message, **context)


def parse_remoteok(data: Any, report: ErrorReporter | None = None) -> list[JobPost]:
    """RemoteOK API: a JSON list whose first element is a legal notice. Its text
    fields are double-encoded UTF-8, hence fix_mojibake."""
    if not isinstance(data, list):
        raise ValueError("RemoteOK API did not return a list")
    posts = []
    for item in data:
        if not isinstance(item, dict) or "position" not in item:
            continue  # the legal notice
        try:
            posted_at = _aware(datetime.fromisoformat(item["date"])) if item.get("date") else None
            salary = {k: item[k] for k in ("salary_min", "salary_max") if (item.get(k) or 0) > 0}
            posts.append(
                JobPost(
                    board="remoteok",
                    company=fix_mojibake(_clean(item["company"])),
                    title=fix_mojibake(_clean(item["position"])),
                    url=item["url"],
                    description_html=_REMOTEOK_SPAM_LINE.sub(
                        "", fix_mojibake(item.get("description") or "")
                    ),
                    posted_at=posted_at,
                    tags=tuple(_clean(t).lower() for t in item.get("tags") or []),
                    details={"location": _clean(item.get("location")) or None, **salary},
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            _report(report, f"bad RemoteOK item: {exc!r}", id=item.get("id"))
    return posts


def _text(item: ET.Element, tag: str) -> str:
    return _clean(item.findtext(tag))


def parse_rss(xml: str | bytes, report: ErrorReporter | None = None) -> list[JobPost]:
    """RSS 2.0 job feed with "Company: Position" item titles (We Work Remotely).
    Items without a company in the title are skipped."""
    root = ET.fromstring(xml)
    posts = []
    for item in root.iter("item"):
        company, sep, title = _text(item, "title").partition(": ")
        url = _text(item, "link") or _text(item, "guid")
        if not sep or not company or not title or not url:
            continue
        try:
            pub_date = _text(item, "pubDate")
            posted_at = _aware(parsedate_to_datetime(pub_date)) if pub_date else None
        except (TypeError, ValueError):
            _report(report, "bad pubDate in RSS item", url=url)
            posted_at = None
        # WWR prefixes the country with its flag emoji.
        country = re.sub(r"^[^\w]+", "", _text(item, "country"))
        details = {
            "region": _text(item, "region") or None,
            "country": country or None,
            "employment_type": _text(item, "type") or None,
        }
        posts.append(
            JobPost(
                board="weworkremotely" if "weworkremotely.com" in url else "rss",
                company=company.strip(),
                title=title.strip(),
                url=url,
                description_html=item.findtext("description") or "",
                posted_at=posted_at,
                tags=tuple(
                    t.strip().lower() for t in _text(item, "skills").split(",") if t.strip()
                ),
                details={k: v for k, v in details.items() if v},
            )
        )
    return posts


def _fold(text: str) -> str:
    """Lowercase, with punctuation runs turned into single spaces, so
    "Full-Stack" matches "full stack" and "Next.js" matches "next js"."""
    return re.sub(r"[^a-z0-9+#]+", " ", text.lower()).strip()


def _has_phrase(text: str, phrases: Iterable[str]) -> bool:
    # Phrase must start at a word boundary: "ios" matches "iOS Developer",
    # not "Studios"; "react" still matches "ReactJS".
    return any(re.search(rf"(?<![a-z0-9]){re.escape(p)}", text) for p in map(_fold, phrases) if p)


@dataclass(frozen=True)
class Filters:
    title_keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...] = ()
    max_age: timedelta = timedelta(days=DEFAULT_MAX_AGE_DAYS)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "Filters":
        return cls(
            title_keywords=tuple(config.get("title_keywords") or ()),
            exclude_keywords=tuple(config.get("exclude_keywords") or ()),
            max_age=timedelta(days=int(config.get("max_age_days") or DEFAULT_MAX_AGE_DAYS)),
        )

    def matches(self, post: JobPost, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        if post.posted_at and post.posted_at < now - self.max_age:
            return False
        if not _has_phrase(_fold(post.title), self.title_keywords):
            return False
        text = _fold(f"{post.title} {html_to_text(post.description_html)}")
        return not _has_phrase(text, self.exclude_keywords)


def to_candidate(post: JobPost, feed: str) -> LeadCandidate:
    text = html_to_text(post.description_html)
    domain = company_domain_from_text(post.company, text)
    metadata = {
        "board": post.board,
        "feed": feed,
        "posted_at": post.posted_at.isoformat() if post.posted_at else None,
        "tags": list(post.tags),
        **post.details,
    }
    return LeadCandidate.model_validate(
        {
            "company_name": post.company,
            "website": f"https://{domain}" if domain else None,
            "signal": {
                "source": "job_posting",
                "source_url": post.url,
                "signal_type": "job_post",
                "title": post.title,
                "raw_text": truncate(text, RAW_TEXT_LIMIT) or None,
                "metadata": {k: v for k, v in metadata.items() if v not in (None, [], "")},
            },
        }
    )


Parser = Callable[[httpx.Response, ErrorReporter], list[JobPost]]


class JobPostingsSource(Source):
    name = "job_posting"
    default_config: ClassVar[dict[str, Any]] = {
        "remoteok": True,
        "rss_feeds": [
            "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
            "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
        ],
        "title_keywords": [
            "bubble", "shopify", "react", "next.js", "full stack", "fullstack",
            "mobile developer", "mobile engineer", "mobile app", "flutter", "ios",
            "android", "no-code", "nocode", "webflow", "wordpress", "frontend",
            "front end", "web developer", "app developer", "mvp",
        ],
        "exclude_keywords": ["senior staff", "unpaid", "equity only"],
        "max_age_days": DEFAULT_MAX_AGE_DAYS,
    }  # fmt: skip

    def _feeds(self, config: dict[str, Any]) -> Iterator[tuple[str, Parser]]:
        if config.get("remoteok"):
            yield REMOTEOK_API, lambda r, report: parse_remoteok(r.json(), report)
        for url in config.get("rss_feeds") or []:
            yield url, lambda r, report: parse_rss(r.content, report)

    def collect(self, config: dict[str, Any]) -> Iterable[LeadCandidate]:
        filters = Filters.from_config(config)
        if not filters.title_keywords:
            self.report_error("job_posting config has no title_keywords; nothing would match")
            return
        with self.http_client() as client:
            for feed, parse in self._feeds(config):
                try:
                    posts = parse(get_with_retry(client, feed), self.report_error)
                except (httpx.HTTPError, ValueError, ET.ParseError) as exc:
                    self.report_error(f"feed failed: {type(exc).__name__}: {exc}", feed=feed)
                    continue
                relevant = [p for p in posts if filters.matches(p)]
                self.log.info("%s: %d posts, %d relevant", feed, len(posts), len(relevant))
                for post in relevant:
                    try:
                        yield to_candidate(post, feed)
                    except ValidationError as exc:
                        self.report_error(
                            f"invalid job post: {exc.error_count()} error(s)", url=post.url
                        )
