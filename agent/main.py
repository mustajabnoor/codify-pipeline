"""CLI: python -m agent run <source> [--dry-run]

Exit codes: 0 success (or partial: some items failed, see agent_runs.errors),
1 run failed, 2 usage / configuration error.
"""

import argparse
import logging

from agent.ai.assess import Assessor
from agent.ai.client import AIClient, ClaudeAI
from agent.core.config import Settings
from agent.core.db import DryRunRepository, Repository, SupabaseRepository
from agent.core.errors import AgentError, FatalRunError
from agent.core.log import setup_logging
from agent.core.models import RunStatus
from agent.core.pipeline import process_candidate
from agent.core.runs import RunRecorder
from agent.sources.registry import SOURCES, get_source

log = logging.getLogger("agent")


def build_repository(settings: Settings, *, dry_run: bool) -> Repository:
    if not dry_run:
        return SupabaseRepository.from_settings(settings)
    if settings.has_supabase:
        log.info("dry run: reading from Supabase for dedupe, no writes")
        return DryRunRepository(reader=SupabaseRepository.from_settings(settings))
    log.warning("dry run: no Supabase credentials, dedupe is in-memory only")
    return DryRunRepository()


def build_assessor(
    settings: Settings, run: RunRecorder, *, dry_run: bool, no_ai: bool, ai: AIClient | None
) -> Assessor | None:
    """AI scoring is required for real runs, so no unscored lead reaches the
    database. Dry runs skip it when asked (--no-ai) or when there is no key."""
    if no_ai:
        log.info("AI off (--no-ai): leads are not scored or drafted")
        return None
    if ai is None:
        if dry_run and settings.missing("anthropic_api_key"):
            log.warning("dry run: no Anthropic key, leads are not scored or drafted")
            return None
        ai = ClaudeAI.from_settings(settings)  # raises MissingConfigError without a key
    return Assessor(ai, run.add_tokens)


def run_source(
    name: str,
    *,
    settings: Settings,
    repo: Repository,
    dry_run: bool,
    no_ai: bool = False,
    ai: AIClient | None = None,
) -> RunStatus:
    source_cls = get_source(name)
    if source_cls.dry_run_only and not dry_run:
        raise AgentError(f"source {name!r} is dev-only; use --dry-run")
    if no_ai and not dry_run:
        raise AgentError("--no-ai is for dry runs only; real runs always score leads")

    configs = repo.get_source_configs(name)
    if configs and not any(c.enabled for c in configs):
        log.info("source %s is disabled in source_configs; nothing to do", name)
        return RunStatus.SUCCESS
    config_dicts = [c.config for c in configs if c.enabled] or [source_cls.default_config]

    with RunRecorder(repo, name) as run:
        # Inside the recorder so a missing key is logged as a failed run.
        settings.require(*source_cls.required_settings, scope=name)
        assess = build_assessor(settings, run, dry_run=dry_run, no_ai=no_ai, ai=ai)
        source = source_cls(settings, report_error=run.record_error)
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
    return run.status


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
    commands.add_parser("sources", help="list available sources")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    if args.command == "sources":
        for name in sorted(SOURCES):
            print(name)
        return 0

    settings = Settings()
    try:
        repo = build_repository(settings, dry_run=args.dry_run)
        status = run_source(
            args.source, settings=settings, repo=repo, dry_run=args.dry_run, no_ai=args.no_ai
        )
    except AgentError as exc:
        log.error("%s", exc)
        return 2
    except Exception:
        log.exception("run failed")
        return 1
    return 1 if status is RunStatus.FAILED else 0
