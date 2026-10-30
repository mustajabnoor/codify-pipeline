"""CLI: python -m agent run <source> [--dry-run]

Exit codes: 0 success (or partial: some items failed, see agent_runs.errors),
1 run failed, 2 usage / configuration error.
"""

import argparse
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from agent.ai.assess import Assessor
from agent.ai.client import AIClient, ClaudeAI
from agent.core.config import Settings
from agent.core.db import DryRunRepository, Repository, SupabaseRepository
from agent.core.errors import AgentError, FatalRunError
from agent.core.log import setup_logging
from agent.core.models import RunError, RunStats, RunStatus
from agent.core.pipeline import process_candidate
from agent.core.runs import RunRecorder
from agent.core.slack import SlackNotifier
from agent.enrich.enricher import Enricher
from agent.enrich.providers import Hunter, MillionVerifier
from agent.sources.base import Source
from agent.sources.registry import SOURCES, get_source
from agent.summary import build_summary, summary_payload

log = logging.getLogger("agent")

# Called after a real run that failed or partly failed: (source, status, stats).
RunNotify = Callable[[str, str, RunStats], None]


def build_repository(settings: Settings, *, dry_run: bool) -> Repository:
    if not dry_run:
        return SupabaseRepository.from_settings(settings)
    if settings.has_supabase:
        log.info("dry run: reading from Supabase for dedupe, no writes")
        return DryRunRepository(reader=SupabaseRepository.from_settings(settings))
    log.warning("dry run: no Supabase credentials, dedupe is in-memory only")
    return DryRunRepository()


def build_enricher(
    settings: Settings, repo: Repository, run: RunRecorder, *, dry_run: bool, enrich: bool
) -> Enricher | None:
    """Contact finding for scored leads. Real runs enrich when HUNTER_API_KEY is
    set; dry runs only with --enrich, so testing a source spends no credits."""
    if dry_run and not enrich:
        log.info("dry run: no contact search (add --enrich to spend lookup credits)")
        return None
    if settings.missing("hunter_api_key"):
        log.warning("enrichment off: missing HUNTER_API_KEY; leads are saved without contacts")
        return None
    assert settings.hunter_api_key
    verifier = None
    if settings.missing("millionverifier_api_key"):
        log.warning("verification off: missing MILLIONVERIFIER_API_KEY; emails stay unverified")
    else:
        assert settings.millionverifier_api_key
        verifier = MillionVerifier(settings.millionverifier_api_key.get_secret_value())
    return Enricher(
        Hunter(settings.hunter_api_key.get_secret_value()),
        verifier,
        is_blocked=lambda email: repo.is_do_not_contact(domains=[], emails=[email]),
        report_error=run.record_error,
    )


def build_assessor(
    settings: Settings,
    run: RunRecorder,
    *,
    dry_run: bool,
    no_ai: bool,
    ai: AIClient | None,
    enricher: Enricher | None = None,
) -> Assessor | None:
    """AI scoring is required for real runs, so no unscored lead reaches the
    database. Dry runs skip it when asked (--no-ai) or when there is no key."""
    if no_ai:
        log.info("AI off (--no-ai): leads are not scored, drafted or enriched")
        return None
    if ai is None:
        if dry_run and settings.missing("anthropic_api_key"):
            log.warning("dry run: no Anthropic key, leads are not scored, drafted or enriched")
            return None
        ai = ClaudeAI.from_settings(settings)  # raises MissingConfigError without a key
    return Assessor(ai, run.add_tokens, enricher)


def run_source(
    name: str,
    *,
    settings: Settings,
    repo: Repository,
    dry_run: bool,
    no_ai: bool = False,
    enrich: bool = False,
    ai: AIClient | None = None,
    enricher: Enricher | None = None,
    notify: RunNotify | None = None,
) -> RunStatus:
    """Run one source. After a real run that failed or partly failed, `notify`
    is called with the source, status and counts (the Slack alert). `enrich`
    turns contact search on for a dry run; `ai` and `enricher` replace the
    real clients (tests)."""
    source_cls = get_source(name)
    if source_cls.dry_run_only and not dry_run:
        raise AgentError(f"source {name!r} is dev-only; use --dry-run")
    if no_ai and not dry_run:
        raise AgentError("--no-ai is for dry runs only; real runs always score leads")

    run = RunRecorder(repo, name)
    try:
        configs = repo.get_source_configs(name)
        if configs and not any(c.enabled for c in configs):
            log.info("source %s is disabled in source_configs; nothing to do", name)
            return RunStatus.SUCCESS
        config_dicts = [c.config for c in configs if c.enabled] or [source_cls.default_config]
        with run:
            if enricher is None and not no_ai:
                enricher = build_enricher(settings, repo, run, dry_run=dry_run, enrich=enrich)
            _collect(
                name, source_cls, config_dicts, settings, repo, run, dry_run, no_ai, ai, enricher
            )
    except BaseException as exc:
        if run.status is RunStatus.RUNNING:  # failed before the run row was opened
            run.record_error(f"{type(exc).__name__}: {exc}", fatal=True)
            run.status = RunStatus.FAILED
        if notify and not dry_run:
            notify(name, run.status.value, run.stats)
            exc.alerted = True  # type: ignore[attr-defined]  # main() won't alert again
        raise
    if notify and not dry_run and run.status in (RunStatus.FAILED, RunStatus.PARTIAL):
        notify(name, run.status.value, run.stats)
    return run.status


def _collect(
    name: str,
    source_cls: type[Source],
    config_dicts: list[dict[str, Any]],
    settings: Settings,
    repo: Repository,
    run: RunRecorder,
    dry_run: bool,
    no_ai: bool,
    ai: AIClient | None,
    enricher: Enricher | None,
) -> None:
    # Inside the recorder so a missing key is logged as a failed run.
    settings.require(*source_cls.required_settings, scope=name)
    assess = build_assessor(settings, run, dry_run=dry_run, no_ai=no_ai, ai=ai, enricher=enricher)
    if source_cls.needs_ai and assess is None:
        raise AgentError(
            f"source {name!r} needs AI to read its items; it can't run with --no-ai "
            "or without an Anthropic key"
        )
    source = source_cls(
        settings,
        report_error=run.record_error,
        ai=assess,
        is_known_url=lambda url: repo.lead_id_for_source_url(url) is not None,
    )
    for config in config_dicts:
        for candidate in source.collect(config):
            run.stats.items_seen += 1
            try:
                process_candidate(candidate, repo, run, assess)
            except FatalRunError:
                raise
            except Exception as exc:
                run.record_error(
                    f"{type(exc).__name__}: {exc}",
                    source_url=candidate.signal.source_url,
                    domain=candidate.domain,
                )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m agent", description=__doc__.splitlines()[0])
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser("run", help="run one source")
    run_cmd.add_argument("source", help=f"one of: {', '.join(sorted(SOURCES))}")
    run_cmd.add_argument(
        "--dry-run", action="store_true", help="no DB writes; print would-be inserts as JSON"
    )
    run_cmd.add_argument(
        "--no-ai", action="store_true", help="dry runs only: skip AI scoring and drafting"
    )
    run_cmd.add_argument(
        "--enrich",
        action="store_true",
        help="dry runs only: also find and verify contacts (spends lookup credits)",
    )
    commands.add_parser("sources", help="list available sources")
    summary_cmd = commands.add_parser("summary", help="post the daily summary to Slack")
    summary_cmd.add_argument(
        "--dry-run", action="store_true", help="print the Slack message instead of posting it"
    )
    # Labels the message as a test; used to check the Slack setup.
    summary_cmd.add_argument("--test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    if args.command == "sources":
        for name in sorted(SOURCES):
            print(name)
        return 0

    settings = Settings()
    if args.command == "summary":
        return run_summary(settings, dry_run=args.dry_run, test=args.test)

    notifier = None if args.dry_run else SlackNotifier.from_settings(settings)
    try:
        repo = build_repository(settings, dry_run=args.dry_run)
        status = run_source(
            args.source,
            settings=settings,
            repo=repo,
            dry_run=args.dry_run,
            no_ai=args.no_ai,
            enrich=args.enrich,
            notify=notifier.run_finished if notifier else None,
        )
    except AgentError as exc:
        log.error("%s", exc)
        _alert_if_never_ran(notifier, args.source, exc)
        return 2
    except Exception as exc:
        log.exception("run failed")
        _alert_if_never_ran(notifier, args.source, exc)
        return 1
    return 1 if status is RunStatus.FAILED else 0


def _alert_if_never_ran(notifier: SlackNotifier | None, source: str, exc: BaseException) -> None:
    """run_source alerts on its own once it starts; this covers failures before
    that, like missing Supabase secrets in GitHub Actions."""
    if notifier and not getattr(exc, "alerted", False) and source in SOURCES:
        stats = RunStats(errors=[RunError(message=f"{type(exc).__name__}: {exc}")])
        notifier.run_finished(source, RunStatus.FAILED.value, stats)


def run_summary(settings: Settings, *, dry_run: bool, test: bool) -> int:
    try:
        reader = SupabaseRepository.from_settings(settings)
        payload = summary_payload(build_summary(reader, datetime.now(UTC)), test=test)
    except AgentError as exc:
        log.error("%s", exc)
        return 2
    if dry_run:
        print(json.dumps(payload, indent=2, default=str))
        return 0
    notifier = SlackNotifier.from_settings(settings)
    if not notifier.enabled:
        log.error("summary: missing required env var(s): SLACK_WEBHOOK_URL")
        return 2
    return 0 if notifier.post(payload) else 1
