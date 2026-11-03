"""Source platforms: the boards, feeds and APIs a source collects from.

The list, with each platform's on/off switch and last run, is the
source_platforms table (supabase/migrations/*_source_platforms.sql). Code
only needs to know which host belongs to which platform; a test checks that
every key here exists in that migration.
"""

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from agent.core.models import RunStatus

# Host (without www.) -> source_platforms.key. Subdomains match too.
PLATFORM_HOSTS: dict[str, str] = {
    "remoteok.com": "remoteok",
    "weworkremotely.com": "weworkremotely",
    "eu-startups.com": "eu_startups",
    "techfundingnews.com": "tech_funding_news",
    "news.crunchbase.com": "crunchbase_news",
    "reddit.com": "reddit",
}

# Longest host first, so news.crunchbase.com wins over a crunchbase.com entry.
_BY_LENGTH = sorted(PLATFORM_HOSTS.items(), key=lambda item: -len(item[0]))
ERROR_LIMIT = 500


def platform_for_url(url: str) -> str | None:
    """The platform a feed or item URL belongs to, or None if unknown."""
    host = (urlsplit(url.strip()).hostname or "").lower().removeprefix("www.")
    for known, key in _BY_LENGTH:
        if host == known or host.endswith(f".{known}"):
            return key
    return None


@dataclass
class PlatformRun:
    """What one platform did in a run; written to its source_platforms row."""

    key: str
    items_seen: int = 0
    leads_new: int = 0
    # Its feed / API answered at least once this run.
    fetched: bool = False
    errors: list[str] = field(default_factory=list)
    fatal: str | None = None  # the run stopped before finishing

    @property
    def status(self) -> RunStatus:
        if self.fatal:
            return RunStatus.FAILED
        if not self.errors:
            return RunStatus.SUCCESS
        return RunStatus.PARTIAL if self.fetched else RunStatus.FAILED

    @property
    def error(self) -> str | None:
        message = self.fatal or (self.errors[0] if self.errors else None)
        return message[:ERROR_LIMIT] if message else None
