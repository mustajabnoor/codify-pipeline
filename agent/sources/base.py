import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Collection, Iterable
from typing import Any, ClassVar

import httpx

from agent.ai.assess import Assessor
from agent.core.config import Settings
from agent.core.http import http_client
from agent.core.models import LeadCandidate
from agent.core.platforms import platform_for_url

ErrorReporter = Callable[..., None]
# Whether a source URL is already stored as a signal (lets a source skip
# known items before spending AI tokens on them).
KnownUrl = Callable[[str], bool]
# Called with a platform key once its feed / API answered.
Fetched = Callable[[str], None]


class Source(ABC):
    """A collector. Subclasses set `name`, list the Settings fields they need in
    `required_settings`, and turn one source_configs entry into candidates."""

    name: ClassVar[str]
    required_settings: ClassVar[tuple[str, ...]] = ()
    # Used when source_configs has no row for this source (e.g. dry run, no DB).
    default_config: ClassVar[dict[str, Any]] = {}
    # Dev/test sources that must never write to the real database.
    dry_run_only: ClassVar[bool] = False
    # Sources that need AI just to read their items (e.g. news articles).
    needs_ai: ClassVar[bool] = False
    # source_platforms keys this collector reads; each can be switched off in
    # the dashboard. Feeds from hosts that aren't a known platform are still
    # read (platform unknown, no switch).
    platforms: ClassVar[tuple[str, ...]] = ()
    # Tests set an httpx.MockTransport here; None means real network.
    transport: ClassVar[httpx.BaseTransport | None] = None

    def __init__(
        self,
        settings: Settings,
        report_error: ErrorReporter | None = None,
        *,
        ai: Assessor | None = None,
        is_known_url: KnownUrl | None = None,
        enabled_platforms: Collection[str] | None = None,
        on_fetched: Fetched | None = None,
    ) -> None:
        self.settings = settings
        self.log = logging.getLogger(f"agent.sources.{self.name}")
        self._report_error = report_error
        self.ai = ai
        self.is_known_url = is_known_url or (lambda _url: False)
        # None: every platform is on (no switches known, e.g. a dry run without a DB).
        self.enabled_platforms = None if enabled_platforms is None else set(enabled_platforms)
        self._on_fetched = on_fetched

    def platform_enabled(self, platform: str | None) -> bool:
        if platform is None or self.enabled_platforms is None:
            return True
        return platform in self.enabled_platforms

    def feed_platform(self, feed: str) -> tuple[str | None, bool]:
        """(platform key, whether to read the feed). Logs a skip."""
        platform = platform_for_url(feed)
        if platform is None:
            self.log.warning("%s: not a known source platform; can't be switched off", feed)
        enabled = self.platform_enabled(platform)
        if not enabled:
            self.log.info("%s: platform %s is switched off; skipped", feed, platform)
        return platform, enabled

    def fetched(self, platform: str | None) -> None:
        """Note that a platform's feed / API answered (its run status)."""
        if platform and self._on_fetched:
            self._on_fetched(platform)

    def http_client(self) -> httpx.Client:
        return http_client(self.transport)

    def report_error(self, message: str, **context: Any) -> None:
        """Record a per-item problem (bad item, parse failure) and carry on.
        It ends up in agent_runs.errors; with `platform`, it also counts
        against that platform's run status."""
        if context.get("platform", "") is None:
            del context["platform"]
        if self._report_error:
            self._report_error(message, **context)
        else:
            self.log.warning("%s %s", message, context)

    @abstractmethod
    def collect(self, config: dict[str, Any]) -> Iterable[LeadCandidate]:
        """Yield candidates. Raise only for source-wide failures (auth, outage);
        skip and log individual items that fail to parse."""
