import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Hosts that never identify a lead's company: a link to them says nothing about
# who the lead is. Subdomains are rejected too (old.reddit.com, uk.linkedin.com).
PLATFORM_DOMAINS = frozenset(
    {
        "reddit.com",
        "redd.it",
        "linkedin.com",
        "lnkd.in",
        "x.com",
        "twitter.com",
        "t.co",
        "facebook.com",
        "fb.com",
        "instagram.com",
        "tiktok.com",
        "youtube.com",
        "youtu.be",
        "github.com",
        "gitlab.com",
        "medium.com",
        "substack.com",
        "producthunt.com",
        "indiehackers.com",
        "betalist.com",
        "news.ycombinator.com",
        "google.com",
        "goo.gl",
        "bit.ly",
        "linktr.ee",
        "wellfound.com",
        "angel.co",
        "remoteok.com",
        "weworkremotely.com",
        "indeed.com",
        "glassdoor.com",
        "crunchbase.com",
        "techcrunch.com",
        "upwork.com",
        "fiverr.com",
        "clutch.co",
        "apify.com",
    }
)

# Hosting platforms where each customer gets a subdomain: acme.myshopify.com is a
# real company, but the bare platform domain is not.
SHARED_HOSTING_DOMAINS = frozenset(
    {
        "myshopify.com",
        "bubbleapps.io",
        "vercel.app",
        "netlify.app",
        "webflow.io",
        "wixsite.com",
        "framer.website",
        "lovable.app",
        "herokuapp.com",
        "wordpress.com",
        "squarespace.com",
    }
)

_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_TRACKING_PARAMS = re.compile(r"^(utm_\w+|ref|ref_src|fbclid|gclid|mc_cid|mc_eid)$", re.I)


def _is_under(host: str, domains: frozenset[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def normalize_domain(value: str | None) -> str | None:
    """Dedupe key for a company: lowercase host, no scheme, www., port or path.

    Returns None when the value has no usable host or points at a platform
    (Reddit, LinkedIn, ...) rather than the company's own site.
    """
    if not value or not value.strip():
        return None
    raw = value.strip()
    if "://" not in raw:
        raw = "http://" + raw.lstrip("/")
    try:
        host = urlsplit(raw).hostname
    except ValueError:
        return None
    if not host:
        return None
    host = host.rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    if not _HOST_RE.match(host):
        return None
    if _is_under(host, PLATFORM_DOMAINS) or host in SHARED_HOSTING_DOMAINS:
        return None
    return host


def normalize_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return None
    email = value.strip().lower()
    local, _, domain = email.rpartition("@")
    if not local or not domain or " " in email:
        return None
    return email


def email_domain(email: str) -> str:
    return email.rpartition("@")[2]


def normalize_url(value: str) -> str:
    """Canonical form of a signal's source_url: lowercase scheme and host, no
    fragment, no tracking params, no trailing slash. Path case is kept
    (Reddit and many job boards use case-sensitive ids)."""
    parts = urlsplit(value.strip())
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    netloc = f"{host}:{parts.port}" if parts.port else host
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING_PARAMS.match(k)
        ]
    )
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, query, ""))
