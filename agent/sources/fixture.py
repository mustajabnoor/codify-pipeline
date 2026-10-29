import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

from pydantic import ValidationError

from agent.core.models import LeadCandidate
from agent.sources.base import Source

FIXTURE_PATH = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "candidates.json"


class FixtureSource(Source):
    """Dev-only source that replays saved candidates, to exercise the pipeline
    end to end: python -m agent run fixture --dry-run"""

    name = "fixture"
    default_config: ClassVar[dict[str, Any]] = {"path": str(FIXTURE_PATH)}
    dry_run_only = True

    def collect(self, config: dict[str, Any]) -> Iterable[LeadCandidate]:
        items = json.loads(Path(config["path"]).read_text())
        for index, item in enumerate(items):
            try:
                yield LeadCandidate.model_validate(item)
            except ValidationError as exc:
                self.report_error(
                    f"invalid fixture item: {exc.error_count()} error(s)", index=index
                )
