import pytest

from agent.core.db import MemoryRepository
from agent.core.models import RunStatus
from agent.core.runs import RunRecorder


def test_success_row(repo: MemoryRepository) -> None:
    with RunRecorder(repo, "funding") as run:
        run.stats.items_seen = 3
        run.stats.leads_new = 2
        run.add_tokens(1200, 0.0125)
        run.add_tokens(800, 0.0075)
    row = repo.runs[run.run_id]
    assert run.status is RunStatus.SUCCESS
    assert row["status"] == "success"
    assert row["source"] == "funding"
    assert row["items_seen"] == 3 and row["leads_new"] == 2
    assert row["tokens_used"] == 2000
    assert row["cost_estimate"] == "0.0200"
    assert row["finished_at"]


def test_partial_when_some_items_fail(repo: MemoryRepository) -> None:
    with RunRecorder(repo, "funding") as run:
        run.stats.leads_new = 1
        run.record_error("bad item", url="https://x.example.com")
    assert run.status is RunStatus.PARTIAL
    assert repo.runs[run.run_id]["errors"][0]["context"] == {"url": "https://x.example.com"}


def test_failed_when_every_item_fails(repo: MemoryRepository) -> None:
    with RunRecorder(repo, "funding") as run:
        run.record_error("bad item")
    assert run.status is RunStatus.FAILED


def test_row_written_when_run_raises(repo: MemoryRepository) -> None:
    with pytest.raises(ValueError), RunRecorder(repo, "funding") as run:
        raise ValueError("feed returned 500")
    row = repo.runs[run.run_id]
    assert row["status"] == "failed"
    assert row["errors"][0]["message"] == "ValueError: feed returned 500"
    assert row["errors"][0]["context"] == {"fatal": True}


def test_finish_failure_does_not_mask_run(
    repo: MemoryRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object) -> None:
        raise ConnectionError("supabase unreachable")

    monkeypatch.setattr(repo, "finish_run", broken)
    with RunRecorder(repo, "funding") as run:
        run.stats.leads_new = 1
    assert run.status is RunStatus.SUCCESS
