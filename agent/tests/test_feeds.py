from datetime import UTC, datetime
from pathlib import Path

from agent.core.feeds import parse_feed

SAMPLE = (Path(__file__).parent / "fixtures" / "funding" / "sample_feed.rss").read_bytes()


def test_parse_wordpress_feed() -> None:
    errors: list[tuple[str, dict[str, str]]] = []
    items = parse_feed(SAMPLE, lambda message, **context: errors.append((message, context)))

    assert len(items) == 7  # the item without a link is skipped
    acme = items[0]
    assert acme.title == "Acme AI Raises $3M in Seed Funding"
    assert acme.url == "https://news.example.com/2026/10/acme-ai-raises-3m/"
    assert acme.published_at == datetime(2026, 10, 28, 9, tzinfo=UTC)
    assert acme.categories == ("Seed", "AI")
    # content:encoded (full article) wins over the description summary.
    assert "scheduling agents for clinics" in acme.html
    assert items[1].title == "Bolt Robotics closes €2.5M pre-seed round"
    assert errors == []


def test_bad_date_is_reported_and_description_is_the_fallback() -> None:
    xml = (
        "<rss><channel><item><title>T</title><link>https://x.example.com/1</link>"
        "<pubDate>someday soon</pubDate><description>&lt;p&gt;Summary only.&lt;/p&gt;"
        "</description></item></channel></rss>"
    )
    errors: list[tuple[str, dict[str, str]]] = []
    (item,) = parse_feed(xml, lambda message, **context: errors.append((message, context)))
    assert item.published_at is None
    assert item.html == "<p>Summary only.</p>"
    assert errors == [("bad pubDate in feed item", {"url": "https://x.example.com/1"})]


def test_dates_without_offset_are_utc() -> None:
    xml = (
        "<rss><channel><item><title>T</title><link>https://x.example.com/1</link>"
        "<pubDate>Wed, 28 Oct 2026 07:31:13 -0000</pubDate></item></channel></rss>"
    )
    (item,) = parse_feed(xml)
    assert item.published_at == datetime(2026, 10, 28, 7, 31, 13, tzinfo=UTC)
