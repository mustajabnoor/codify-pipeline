import logging
from collections.abc import Iterable
from decimal import Decimal
from types import TracebackType
from typing import Any, Self
from uuid import UUID

from agent.core.db import Repository
from agent.core.models import RunError, RunStats, RunStatus
from agent.core.platforms import PlatformRun

log = logging.getLogger(__name__)


class RunRecorder:
    """Writes one agent_runs row per run: opened on enter, closed on exit with
    counts, errors and token usage - also when the run raises."""

    def __init__(self, repo: Repository, source: str) -> None:
        self.repo = repo
        self.source = source
        self.stats = RunStats()
        self.status = RunStatus.RUNNING
        self.run_id: UUID | None = None
        # Per platform (RemoteOK, EU-Startups...): set by track_platforms.
        self.platforms: dict[str, PlatformRun] = {}

    def track_platforms(self, keys: Iterable[str]) -> None:
        """Record these platforms' results in source_platforms when the run ends."""
        for key in keys:
            self.platforms.setdefault(key, PlatformRun(key))

    def platform_fetched(self, key: str) -> None:
        if run := self.platforms.get(key):
            run.fetched = True

    def count_item(self, platform: str | None, *, new_lead: bool) -> None:
        if platform and (run := self.platforms.get(platform)):
            run.items_seen += 1
            run.leads_new += int(new_lead)

    def __enter__(self) -> Self:
        self.run_id = self.repo.start_run(self.source)
        log.info("run started: source=%s run_id=%s", self.source, self.run_id)
        return self

    def record_error(self, message: str, **context: Any) -> None:
        log.warning("%s %s", message, context or "")
        self.stats.errors.append(RunError(message=message, context=context))
        # Errors tied to a platform (its feed failed, one of its items failed)
        # count against it; run-wide ones (config, enrichment) don't.
        if (platform := context.get("platform")) and (run := self.platforms.get(platform)):
            run.errors.append(message)

    def add_tokens(self, tokens: int, cost: Decimal | float = 0) -> None:
        self.stats.tokens_used += tokens
        self.stats.cost_estimate += Decimal(str(cost))

    def _final_status(self, crashed: bool) -> RunStatus:
        if crashed:
            return RunStatus.FAILED
        if not self.stats.errors:
            return RunStatus.SUCCESS
        handled = self.stats.leads_new + self.stats.leads_updated + self.stats.leads_skipped
        return RunStatus.PARTIAL if handled else RunStatus.FAILED

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc is not None:
            self.record_error(f"{type(exc).__name__}: {exc}", fatal=True)
            for run in self.platforms.values():
                run.fatal = f"{type(exc).__name__}: {exc}"
        self.status = self._final_status(crashed=exc is not None)
        try:
            self.repo.finish_run(self.run_id, self.source, self.status, self.stats)
        except Exception:
            log.exception("could not write agent_runs row for run %s", self.run_id)
        if self.platforms:
            try:
                self.repo.record_platform_runs(list(self.platforms.values()))
            except Exception:
                log.exception("could not update source_platforms for run %s", self.run_id)
        s = self.stats
        log.info(
            "run finished: source=%s status=%s seen=%d new=%d updated=%d skipped=%d errors=%d "
            "tokens=%d cost=$%.4f",
            self.source, self.status, s.items_seen, s.leads_new, s.leads_updated,
            s.leads_skipped, len(s.errors), s.tokens_used, s.cost_estimate,
        )  # fmt: skip
        return False
