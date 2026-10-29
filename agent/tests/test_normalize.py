import pytest

from agent.core.normalize import normalize_domain, normalize_email, normalize_url


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
