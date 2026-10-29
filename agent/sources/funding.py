"""Funding news: startups that just raised pre-seed / seed / Series A money.
Articles come from RSS feeds; Claude (cheap model) reads each one to find the
company, its website, the round and the founders.

Config (source_configs.config):
  rss_feeds       [url]   funding news feeds (RSS 2.0)
  title_keywords  [str]   only articles whose title has one are read by AI
  exclude_keywords [str]  skip titles with these (later rounds, IPOs...)
  rounds          [str]   keep these rounds (pre-seed, seed, series a, ...)
  max_age_days    int     ignore older articles (default 7)
  max_articles    int     AI reads at most this many articles per run (default 40)
"""

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar

import httpx
from pydantic import ValidationError

from agent.ai.client import AIError
from agent.ai.schemas import FundingExtraction
from agent.core.feeds import FeedItem, parse_feed
from agent.core.http import get_with_retry
from agent.core.models import LeadCandidate
from agent.core.normalize import company_domain_from_text, normalize_domain, normalize_url
from agent.core.text import has_phrase, html_to_text, truncate
from agent.sources.base import Source

# Bump with a new prompt file; recorded on each signal.
FUNDING_EXTRACT_PROMPT = "funding_extract_v1"
ARTICLE_LIMIT = 8000
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_MAX_ARTICLES = 40
_DOMAIN_IN_TEXT = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.I)


def is_candidate_article(item: FeedItem, config: dict[str, Any], now: datetime) -> bool:
    """Cheap filter before any AI call: recent, funding wording in the title,
    no excluded wording (later rounds, IPOs...)."""
    max_age = timedelta(days=int(config.get("max_age_days") or DEFAULT_MAX_AGE_DAYS))
    if item.published_at and item.published_at < now - max_age:
        return False
    if not has_phrase(item.title, config.get("title_keywords") or ()):
        return False
    return not has_phrase(item.title, config.get("exclude_keywords") or ())


def verified_domain(extraction: FundingExtraction, text: str) -> str | None:
    """The company's domain, only if the article itself shows it: the website
    Claude read must appear in the article's links or text; otherwise fall back
    to a link whose host contains the company name. Never a guess."""
    domains_in_text = {d for m in _DOMAIN_IN_TEXT.findall(text) if (d := normalize_domain(m))}
    claimed = normalize_domain(extraction.website)
    if claimed and claimed in domains_in_text:
        return claimed
    return company_domain_from_text(extraction.company_name or "", text)


def to_candidate(
    item: FeedItem, feed: str, extraction: FundingExtraction, rounds: Iterable[str]
) -> LeadCandidate | None:
    """None when the article isn't one company's round in a wanted stage."""
    if not extraction.is_single_announcement or not extraction.company_name:
        return None
    if extraction.round not in set(rounds):
        return None
    text = html_to_text(item.html)
    domain = verified_domain(extraction, text)
    currency = (extraction.currency or "").upper() or None
    amount = Decimal(str(extraction.amount)) if extraction.amount else None
    found_via = "funding:funding_round"
    metadata = {
        "feed": feed,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        "round": extraction.round,
        "amount": float(amount) if amount else None,
        "currency": currency,
        "investors": extraction.investors,
        "ai_prompts": {"extract": FUNDING_EXTRACT_PROMPT},
    }
    return LeadCandidate.model_validate(
        {
            "company_name": extraction.company_name.strip(),
            "website": f"https://{domain}" if domain else None,
            "industry": extraction.industry,
            "country": extraction.country,
            "city": extraction.city,
            "description": extraction.description,
            "tech_stack": sorted({t.strip().lower() for t in extraction.tech_stack if t.strip()}),
            # leads.funding_amount has no currency column: only USD is stored
            # there; other currencies stay in signal metadata.
            "funding_amount": amount if currency == "USD" else None,
            "funding_round": extraction.round,
            "funding_date": item.published_at.date() if item.published_at else None,
            "signal": {
                "source": "funding",
                "source_url": item.url,
                "signal_type": "funding_round",
                "title": item.title,
                "raw_text": truncate(text, ARTICLE_LIMIT) or None,
                "metadata": {k: v for k, v in metadata.items() if v not in (None, [], "")},
            },
            "contacts": [
                {"full_name": f.name.strip(), "role": f.role, "found_via": found_via}
                for f in extraction.founders
                if f.name.strip()
            ],
        }
    )


def article_brief(item: FeedItem) -> str:
    published = item.published_at.date().isoformat() if item.published_at else "unknown"
    text = truncate(html_to_text(item.html), ARTICLE_LIMIT)
    head = f"Title: {item.title}\nURL: {item.url}\nPublished: {published}"
    return f"{head}\n\n<article>\n{text}\n</article>"


class FundingNewsSource(Source):
    name = "funding"
    needs_ai = True
    default_config: ClassVar[dict[str, Any]] = {
        "rss_feeds": [],
        "title_keywords": [
            "raises", "raised", "secures", "closes", "lands", "funding", "pre-seed",
            "seed", "series a", "investment", "backed",
        ],
        "exclude_keywords": [
            "series b", "series c", "series d", "series e", "ipo", "acquires",
            "acquired", "acquisition", "layoffs", "fund i", "new fund",
        ],
        "rounds": ["pre-seed", "seed", "series a"],
        "max_age_days": DEFAULT_MAX_AGE_DAYS,
        "max_articles": DEFAULT_MAX_ARTICLES,
    }  # fmt: skip

    def collect(self, config: dict[str, Any]) -> Iterable[LeadCandidate]:
        assert self.ai is not None, "run_source refuses needs_ai sources without AI"
        feeds = config.get("rss_feeds") or []
        if not feeds:
            self.report_error("funding config has no rss_feeds; nothing to read")
            return
        rounds = config.get("rounds") or self.default_config["rounds"]
        budget = int(config.get("max_articles") or DEFAULT_MAX_ARTICLES)
        now = datetime.now(UTC)
        with self.http_client() as client:
            for feed in feeds:
                try:
                    items = parse_feed(get_with_retry(client, feed).content, self.report_error)
                except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                    self.report_error(f"feed failed: {type(exc).__name__}: {exc}", feed=feed)
                    continue
                fresh = [
                    i
                    for i in items
                    if is_candidate_article(i, config, now)
                    and not self.is_known_url(normalize_url(i.url))
                ]
                self.log.info("%s: %d articles, %d new to read", feed, len(items), len(fresh))
                for item in fresh:
                    if budget <= 0:
                        self.log.info("max_articles reached; the rest wait for the next run")
                        return
                    budget -= 1
                    try:
                        extraction = self.ai.run(
                            "funding_extract",
                            FUNDING_EXTRACT_PROMPT,
                            article_brief(item),
                            FundingExtraction,
                        )
                    except AIError as exc:
                        self.report_error(f"article extraction failed: {exc}", url=item.url)
                        continue
                    try:
                        candidate = to_candidate(item, feed, extraction, rounds)
                    except ValidationError as exc:
                        self.report_error(
                            f"invalid funding item: {exc.error_count()} error(s)", url=item.url
                        )
                        continue
                    if candidate is None:
                        self.log.debug(
                            "skipped %s: %s / %s",
                            item.url,
                            extraction.is_single_announcement,
                            extraction.round,
                        )
                        continue
                    yield candidate
