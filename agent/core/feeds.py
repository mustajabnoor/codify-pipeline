"""Generic RSS 2.0 parsing (WordPress-style news feeds and similar)."""

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape

CONTENT_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"

ErrorReporter = Callable[..., None]


@dataclass(frozen=True)
class FeedItem:
    title: str
    url: str
    published_at: datetime | None
    html: str  # full article (content:encoded) when the feed has it, else the summary
    categories: tuple[str, ...] = ()


def parse_date(value: str | None) -> datetime | None:
    """RFC 822 feed date -> aware datetime (UTC when the feed gives no offset).
    Raises ValueError on garbage."""
    if not value or not value.strip():
        return None
    parsed = parsedate_to_datetime(value.strip())
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _text(item: ET.Element, tag: str) -> str:
    return unescape(item.findtext(tag) or "").strip()


def parse_feed(xml: str | bytes, report: ErrorReporter | None = None) -> list[FeedItem]:
    """Items with a title and a link; anything else is skipped. A bad date is
    reported and left empty rather than dropping the item."""
    root = ET.fromstring(xml)
    items = []
    for item in root.iter("item"):
        title = _text(item, "title")
        url = _text(item, "link") or _text(item, "guid")
        if not title or not url.startswith(("http://", "https://")):
            continue
        try:
            published_at = parse_date(item.findtext("pubDate"))
        except (TypeError, ValueError):
            if report:
                report("bad pubDate in feed item", url=url)
            published_at = None
        html = item.findtext(CONTENT_ENCODED) or item.findtext("description") or ""
        categories = tuple(
            t for e in item.findall("category") if (t := unescape(e.text or "").strip())
        )
        items.append(FeedItem(title, url, published_at, html, categories))
    return items
