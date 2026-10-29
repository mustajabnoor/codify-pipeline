import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import Any, ClassVar

import httpx

from agent.core.config import Settings
from agent.core.http import http_client
from agent.core.models import LeadCandidate

ErrorReporter = Callable[..., None]


class Source(ABC):
    """A collector. Subclasses set `name`, list the Settings fields they need in
    `required_settings`, and turn one source_configs entry into candidates."""

    name: ClassVar[str]
    required_settings: ClassVar[tuple[str, ...]] = ()
    # Used when source_configs has no row for this source (e.g. dry run, no DB).
    default_config: ClassVar[dict[str, Any]] = {}
    # Dev/test sources that must never write to the real database.
    dry_run_only: ClassVar[bool] = False
    # Tests set an httpx.MockTransport here; None means real network.
    transport: ClassVar[httpx.BaseTransport | None] = None

    def __init__(self, settings: Settings, report_error: ErrorReporter | None = None) -> None:
        self.settings = settings
        self.log = logging.getLogger(f"agent.sources.{self.name}")
        self._report_error = report_error

    def http_client(self) -> httpx.Client:
        return http_client(self.transport)

    def report_error(self, message: str, **context: Any) -> None:
        """Record a per-item problem (bad item, parse failure) and carry on.
        It ends up in agent_runs.errors."""
        if self._report_error:
            self._report_error(message, **context)
        else:
            self.log.warning("%s %s", message, context)

    @abstractmethod
    def collect(self, config: dict[str, Any]) -> Iterable[LeadCandidate]:
        """Yield candidates. Raise only for source-wide failures (auth, outage);
        skip and log individual items that fail to parse."""
