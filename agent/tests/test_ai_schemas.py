"""Claude's JSON output -> pydantic models: what is accepted and what is rejected."""

import json
from typing import Any

import anthropic
import pytest
from pydantic import BaseModel, ValidationError

from agent.ai.schemas import Assessment, Draft, Extraction, FundingExtraction
from agent.core.models import SIGN_OFF, LeadAssessment, OutreachDraft

from .conftest import make_candidate

SCORE_JSON = {
    "fit_score": 8,
    "score_reason": "Funded startup hiring a Bubble developer on contract.",
    "service_fit": ["bubble", "mvp"],
    "pain_point": "hiring a Bubble developer for a 6-week contract",
}


def score(**overrides: Any) -> str:
    return json.dumps({**SCORE_JSON, **overrides})


def test_assessment_parses() -> None:
    parsed = Assessment.model_validate_json(score())
    assert parsed.fit_score == 8
    assert [s.value for s in parsed.service_fit] == ["bubble", "mvp"]


@pytest.mark.parametrize(
    "bad",
    [
        {"fit_score": 0},
        {"fit_score": 11},
        {"fit_score": "high"},
        {"service_fit": []},
        {"service_fit": ["wordpress_plugins"]},
        {"pain_point": None},
    ],
)
def test_assessment_rejects(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Assessment.model_validate_json(score(**bad))


def test_assessment_requires_every_field() -> None:
    with pytest.raises(ValidationError):
        Assessment.model_validate_json(json.dumps({"fit_score": 5}))


def draft(body: str, channel: str = "email") -> str:
    return json.dumps({"subject": "Your Bubble role", "body": body, "best_channel": channel})


def test_draft_accepts_product_names() -> None:
    parsed = Draft.model_validate_json(
        draft("Hi, we've built on Bubble.io for 5+ years. Worth a look?")
    )
    assert parsed.best_channel.value == "email"


@pytest.mark.parametrize(
    "body",
    [
        " ".join(["word"] * 101),
        "Hi, see our work at https://codify-labs.com - worth a look?",
        "Hi, see www.codify-labs.com for examples.",
    ],
)
def test_draft_rejects_long_bodies_and_links(body: str) -> None:
    with pytest.raises(ValidationError):
        Draft.model_validate_json(draft(body))


def test_draft_rejects_unknown_channel() -> None:
    with pytest.raises(ValidationError):
        Draft.model_validate_json(draft("Hi, worth a look?", channel="carrier_pigeon"))


def test_extraction_allows_nulls_but_not_missing_fields() -> None:
    nulls = {
        "industry": None,
        "country": None,
        "city": None,
        "company_size": None,
        "description": None,
        "tech_stack": [],
        "people": [{"name": "Dana Lee", "role": None}],
    }
    assert Extraction.model_validate_json(json.dumps(nulls)).people[0].name == "Dana Lee"
    with pytest.raises(ValidationError):
        Extraction.model_validate_json(json.dumps({"industry": "saas"}))


def _walk(schema: Any) -> list[dict[str, Any]]:
    if isinstance(schema, dict):
        return [schema, *(n for v in schema.values() for n in _walk(v))]
    if isinstance(schema, list):
        return [n for v in schema for n in _walk(v)]
    return []


@pytest.mark.parametrize("model", [Extraction, Assessment, Draft, FundingExtraction])
def test_api_schema_is_strict(model: type[BaseModel]) -> None:
    """Structured outputs need additionalProperties: false on every object and
    reject numeric/length constraints; those must be checked client-side."""
    nodes = _walk(anthropic.transform_schema(model))
    objects = [n for n in nodes if n.get("type") == "object"]
    assert objects and all(o.get("additionalProperties") is False for o in objects)
    assert not any({"minimum", "maximum", "maxLength", "minLength"} & n.keys() for n in nodes)


def test_lead_row_carries_score_and_rejects_low_fit() -> None:
    assessment = LeadAssessment.model_validate_json(score(fit_score=3))
    outreach = OutreachDraft(channel="linkedin", subject="s", body="b")
    candidate = make_candidate().model_copy(update={"assessment": assessment, "outreach": outreach})
    row = candidate.lead_row()
    assert row["fit_score"] == 3
    assert row["status"] == "rejected"
    assert row["service_fit"] == ["bubble", "mvp"]
    assert row["best_channel"] == "linkedin"
    assert "assessment" not in row and "outreach" not in row

    good = candidate.model_copy(
        update={"assessment": assessment.model_copy(update={"fit_score": 4})}
    )
    assert good.lead_row()["status"] == "new"


def test_draft_body_always_ends_with_sign_off() -> None:
    outreach = OutreachDraft(channel="email", subject="s", body="Hi, worth a look?  ")
    assert outreach.draft_body == f"Hi, worth a look?\n\n{SIGN_OFF}"
    assert "Not relevant? Reply 'no'" in outreach.draft_body


def funding(**overrides: Any) -> str:
    base: dict[str, Any] = {
        "is_single_announcement": True,
        "company_name": "Acme AI",
        "website": None,
        "round": "seed",
        "amount": 3000000,
        "currency": "USD",
        "investors": [],
        "founders": [{"name": "Jane Roe", "role": "CEO"}],
        "industry": None,
        "country": None,
        "city": None,
        "description": None,
        "tech_stack": [],
    }
    return json.dumps({**base, **overrides})


def test_funding_extraction_parses() -> None:
    parsed = FundingExtraction.model_validate_json(funding())
    assert (parsed.round, parsed.amount, parsed.founders[0].name) == ("seed", 3000000, "Jane Roe")
    roundup = FundingExtraction.model_validate_json(
        funding(is_single_announcement=False, company_name=None, round=None, amount=None)
    )
    assert roundup.company_name is None


@pytest.mark.parametrize("bad", [{"round": "series z"}, {"round": "Seed"}, {"founders": None}])
def test_funding_extraction_rejects(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        FundingExtraction.model_validate_json(funding(**bad))
