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
from agent.core.dedupe import Action
from agent.core.errors import AgentError, FatalRunError
from agent.core.log import setup_logging
from agent.core.models import RunError, RunStats, RunStatus
from agent.core.pipeline import Assess, process_candidate
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
# Leads saved while AI was off that one run scores once it's back on; the
# rest wait for the next run.
BACKLOG_PER_RUN = 20


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
    ai_switched_off: bool = False,
) -> Assessor | None:
    """Real runs score every new lead, unless Claude AI is switched off in the
    dashboard: then leads are saved unscored and scored by a later run. Dry
    runs also skip it when asked (--no-ai) or when there is no key."""
    if ai_switched_off:
        log.info("Claude AI is switched off: leads are saved without score, draft or contact")
        return None
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
        platforms = enabled_platforms(source_cls, repo)
        if source_cls.platforms and platforms is not None and not platforms:
            log.info("every platform of %s is switched off; nothing to do", name)
            return RunStatus.SUCCESS
        ai_switched_off = not repo.ai_enabled()
        if ai_switched_off and source_cls.needs_ai:
            log.info("source %s needs Claude AI to read its items; paused while AI is off", name)
            return RunStatus.SUCCESS
        config_dicts = [c.config for c in configs if c.enabled] or [source_cls.default_config]
        with run:
            run.track_platforms(source_cls.platforms if platforms is None else platforms)
            if enricher is None and not no_ai and not ai_switched_off:
                enricher = build_enricher(settings, repo, run, dry_run=dry_run, enrich=enrich)
            _collect(
                name,
                source_cls,
                config_dicts,
                settings,
                repo,
                run,
                dry_run=dry_run,
                no_ai=no_ai,
                ai=ai,
                enricher=enricher,
                platforms=platforms,
                ai_switched_off=ai_switched_off,
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


def enabled_platforms(source_cls: type[Source], repo: Repository) -> list[str] | None:
    """The source's platforms that are switched on, or None when the switches
    are unknown (no database: every platform is read)."""
    switches = repo.get_platform_switches(source_cls.name)
    if switches is None:
        return None
    for key in source_cls.platforms:
        if key not in switches:
            log.warning("platform %s has no source_platforms row; treated as on", key)
    return [key for key in source_cls.platforms if switches.get(key, True)]


def _collect(
    name: str,
    source_cls: type[Source],
    config_dicts: list[dict[str, Any]],
    settings: Settings,
    repo: Repository,
    run: RunRecorder,
    *,
    dry_run: bool,
    no_ai: bool,
    ai: AIClient | None,
    enricher: Enricher | None,
    platforms: list[str] | None = None,
    ai_switched_off: bool = False,
) -> None:
    # Inside the recorder so a missing key is logged as a failed run.
    settings.require(*source_cls.required_settings, scope=name)
    assess = build_assessor(
        settings,
        run,
        dry_run=dry_run,
        no_ai=no_ai,
        ai=ai,
        enricher=enricher,
        ai_switched_off=ai_switched_off,
    )
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
        enabled_platforms=platforms,
        on_fetched=run.platform_fetched,
    )
    for config in config_dicts:
        for candidate in source.collect(config):
            run.stats.items_seen += 1
            platform = candidate.signal.platform
            try:
                action = process_candidate(candidate, repo, run, assess)
            except FatalRunError:
                raise
            except Exception as exc:
                run.count_item(platform, new_lead=False)
                run.record_error(
                    f"{type(exc).__name__}: {exc}",
                    source_url=candidate.signal.source_url,
                    domain=candidate.domain,
                    **({"platform": platform} if platform else {}),
                )
            else:
                run.count_item(platform, new_lead=action is Action.CREATE_LEAD)
    if assess is not None:
        score_backlog(name, repo, run, assess)


def score_backlog(
    name: str, repo: Repository, run: RunRecorder, assess: Assess, limit: int = BACKLOG_PER_RUN
) -> int:
    """Score, enrich and draft new leads that were saved while Claude AI was
    off (oldest first, up to `limit`). Returns how many were scored; each
    counts as an updated lead. A failure leaves the lead for the next run."""
    pending = repo.unscored_leads(name, limit)
    if pending:
        log.info("scoring %d lead(s) saved while Claude AI was off", len(pending))
    scored = 0
    for stored in pending:
        candidate = stored.candidate
        domains = [candidate.domain] if candidate.domain else []
        if repo.is_do_not_contact(domains=domains, emails=candidate.emails):
            log.info("unscored lead %s is on do_not_contact; not scored", stored.lead_id)
            continue
        try:
            if repo.save_assessment(stored, assess(candidate)):
                scored += 1
                run.stats.leads_updated += 1
        except FatalRunError:
            raise
        except Exception as exc:
            run.record_error(
                f"scoring a saved lead failed: {type(exc).__name__}: {exc}",
                lead_id=str(stored.lead_id),
                source_url=candidate.signal.source_url,
            )
    return scored


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
