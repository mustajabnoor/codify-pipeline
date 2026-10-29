import re
from collections import Counter
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
        # Applicant tracking / form / scheduling hosts linked from job posts.
        "greenhouse.io",
        "lever.co",
        "workable.com",
        "ashbyhq.com",
        "breezy.hr",
        "bamboohr.com",
        "recruitee.com",
        "teamtailor.com",
        "myworkdayjobs.com",
        "smartrecruiters.com",
        "jobvite.com",
        "applytojob.com",
        "icims.com",
        "jobs.personio.de",
        "typeform.com",
        "calendly.com",
        "notion.site",
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
_URL_IN_TEXT = re.compile(r"(?:https?://|\bwww\.)[^\s<>\"'()\[\]]+", re.I)
# Dropped from company names before matching them against hosts.
_LEGAL_SUFFIXES = frozenset(
    {"inc", "llc", "ltd", "limited", "corp", "corporation", "co", "plc", "gmbh", "ag",
     "sa", "sas", "bv", "pty", "pvt", "llp", "the"}
)  # fmt: skip
# Too generic to identify a company on their own.
_GENERIC_WORDS = frozenset(
    {"remote", "global", "digital", "group", "company", "tech", "technologies", "labs",
     "software", "solutions", "systems", "health", "media", "studio", "agency", "app"}
)  # fmt: skip
# Careers-site subdomains map to the company's main domain.
_CAREERS_PREFIX = re.compile(r"^(careers?|jobs|apply|join|work)\.(?=[^.]+\.[^.]+)")
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


def _company_slugs(company: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", company.lower()) if w not in _LEGAL_SUFFIXES]
    slugs = ["".join(words)]
    if len(words) > 1 and len(words[0]) >= 4 and words[0] not in _GENERIC_WORDS:
        slugs.append(words[0])
    return [s for s in slugs if len(s) >= 3]


def company_domain_from_text(company: str, text: str | None) -> str | None:
    """Guess a company's own domain from links in text about it (a job post).

    Only hosts that contain the company's name are accepted (Carrot ->
    get-carrot.com, never a news site or job board it links to), so it returns
    None rather than guess: a wrong domain would merge two companies' leads.
    Careers subdomains count as the main domain (jobs.carrot.com ->
    carrot.com). Among matches the shortest host wins (carrot.com over
    app.carrot.com), then the most linked.
    """
    slugs = _company_slugs(company)
    if not text or not slugs:
        return None
    hits: Counter[str] = Counter()
    for url in _URL_IN_TEXT.findall(text):
        host = normalize_domain(url.rstrip(".,;:!?"))
        if host and any(slug in re.sub(r"[.-]", "", host) for slug in slugs):
            hits[_CAREERS_PREFIX.sub("", host)] += 1
    if not hits:
        return None
    return min(hits, key=lambda h: (h.count("."), -hits[h], h))


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
