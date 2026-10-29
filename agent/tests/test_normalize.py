import pytest

from agent.core.normalize import (
    company_domain_from_text,
    normalize_domain,
    normalize_email,
    normalize_url,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.Acme.com/about?x=1", "acme.com"),
        ("http://acme.com:8080", "acme.com"),
        ("acme.com/pricing", "acme.com"),
        ("WWW.ACME.COM", "acme.com"),
        ("//acme.com", "acme.com"),
        ("https://shop.acme.co.uk/", "shop.acme.co.uk"),
        ("https://acme.com.", "acme.com"),
        ("https://user:pw@acme.com", "acme.com"),
        ("https://bücher.de", "xn--bcher-kva.de"),
        ("brightloop.myshopify.com", "brightloop.myshopify.com"),
        ("acme.bubbleapps.io/version-test", "acme.bubbleapps.io"),
    ],
)
def test_normalize_domain(value: str, expected: str) -> None:
    assert normalize_domain(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "localhost",
        "not a domain",
        "http://",
        "https://www.reddit.com/r/startups/comments/x",
        "old.reddit.com",
        "https://www.linkedin.com/company/acme",
        "https://uk.linkedin.com/in/someone",
        "github.com/acme",
        "myshopify.com",
        "https://-bad-.com",
        "https://boards.greenhouse.io/acme/jobs/1",
        "acme.breezy.hr",
        "https://jobs.lever.co/acme",
        "acme.jobs.personio.de",
    ],
)
def test_normalize_domain_rejects(value: str | None) -> None:
    assert normalize_domain(value) is None


def test_normalize_email() -> None:
    assert normalize_email("  Dana@Acme.COM ") == "dana@acme.com"
    assert normalize_email("no-at-sign") is None
    assert normalize_email("@acme.com") is None
    assert normalize_email(None) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "HTTPS://Example.com/Jobs/ABC/?utm_source=x&id=7#apply",
            "https://example.com/Jobs/ABC?id=7",
        ),
        ("https://example.com/", "https://example.com"),
        ("https://example.com/a?ref=hn&q=", "https://example.com/a?q="),
        ("http://example.com:8080/x", "http://example.com:8080/x"),
    ],
)
def test_normalize_url(value: str, expected: str) -> None:
    assert normalize_url(value) == expected


@pytest.mark.parametrize(
    ("company", "text", "expected"),
    [
        ("Carrot", "https://c212.net/x and https://get-carrot.com/about", "get-carrot.com"),
        ("Vested, Inc.", "URL: https://vested.co (https://vested.co/)", "vested.co"),
        # Careers subdomain -> main domain; shortest host wins over most linked.
        ("Proxify AB", "http://career.proxify.io http://career.proxify.io", "proxify.io"),
        ("Coinbase", "www.coinbase.com/careers https://app.coinbase.com/a https://app.coinbase.com/b",
         "coinbase.com"),
        # Multi-word names match joined or by a distinctive first word.
        ("Sanctuary Computer", "https://sanctuary.computer/work", "sanctuary.computer"),
        ("Salesloft Inc", "Apply at https://salesloft.com/company/careers/.", "salesloft.com"),
        # ATS pages, unrelated sites and generic first words never count.
        ("Carrot", "https://carrot.breezy.hr/p/1 https://www.dol.gov", None),
        ("Remote Labs", "https://remote.com", None),
        ("AI", "https://ai.com", None),
        ("Acme", None, None),
    ],
)  # fmt: skip
def test_company_domain_from_text(company: str, text: str | None, expected: str | None) -> None:
    assert company_domain_from_text(company, text) == expected
