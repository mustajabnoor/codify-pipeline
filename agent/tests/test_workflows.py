"""The scheduled GitHub Actions workflows: each source has one, runnable on a
schedule and by hand, with the secrets it needs (CLAUDE.md §9)."""

from pathlib import Path

import pytest

from agent.sources.registry import SOURCES

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
SCHEDULED = {"job_posting": "job-posting.yml", "funding": "funding.yml"}


def read(name: str) -> str:
    return (WORKFLOWS / name).read_text()


@pytest.mark.parametrize(("source", "file"), sorted(SCHEDULED.items()))
def test_source_workflow(source: str, file: str) -> None:
    text = read(file)
    assert source in SOURCES
    assert "schedule:" in text and "- cron:" in text
    assert "workflow_dispatch:" in text
    assert f"group: source-{source}" in text
    assert "uses: ./.github/workflows/run-source.yml" in text
    assert f"source: {source}" in text
    assert "secrets: inherit" in text


def test_shared_run_step() -> None:
    text = read("run-source.yml")
    assert "workflow_call:" in text
    assert "uv sync --locked" in text
    assert 'python -m agent run "${{ inputs.source }}"' in text
    for secret in (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "ANTHROPIC_API_KEY",
        "SLACK_WEBHOOK_URL",
    ):
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in text


def test_daily_summary_runs_after_the_sources() -> None:
    text = read("daily-summary.yml")
    assert '- cron: "15 4 * * *"' in text and "workflow_dispatch:" in text
    assert "python -m agent summary" in text
    for secret in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SLACK_WEBHOOK_URL"):
        assert f"secrets.{secret}" in text
    # The summary is posted after the last morning source run starts.
    source_minutes = [
        int(hour) * 60 + int(minute)
        for file in SCHEDULED.values()
        for minute, hour in [read(file).split('- cron: "')[1].split()[:2]]
    ]
    assert max(source_minutes) < 4 * 60 + 15
