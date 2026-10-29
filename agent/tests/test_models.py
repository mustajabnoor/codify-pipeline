from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent.core.models import LeadCandidate, LeadSource

from .conftest import make_candidate


def test_domain_derived_from_website() -> None:
    c = make_candidate(website="https://www.Acme.com/careers")
    assert c.domain == "acme.com"
    assert c.source is LeadSource.JOB_POSTING


def test_platform_website_has_no_domain() -> None:
    c = make_candidate(website="https://www.reddit.com/user/someone")
    assert c.domain is None


def test_source_url_must_be_http() -> None:
    with pytest.raises(ValidationError):
        make_candidate(url="ftp://example.com/x")


def test_source_url_is_normalized() -> None:
    c = make_candidate(url="https://Jobs.example.com/1/?utm_campaign=x#top")
    assert c.signal.source_url == "https://jobs.example.com/1"


def test_contact_email_lowercased_and_validated() -> None:
    c = make_candidate(contacts=[{"email": " Dana@Acme.com "}])
    assert c.emails == ["dana@acme.com"]
    with pytest.raises(ValidationError):
        make_candidate(contacts=[{"email": "nope"}])


def test_email_status_requires_email() -> None:
    with pytest.raises(ValidationError):
        make_candidate(contacts=[{"full_name": "X", "email_status": "valid"}])


def test_only_one_primary_contact() -> None:
    with pytest.raises(ValidationError):
        make_candidate(
            contacts=[
                {"email": "a@acme.com", "is_primary": True},
                {"email": "b@acme.com", "is_primary": True},
            ]
        )


def test_unknown_source_rejected() -> None:
    with pytest.raises(ValidationError):
        make_candidate(source="upwork")


def test_rows_are_json_ready() -> None:
    c = LeadCandidate.model_validate(
        {
            "company_name": "Acme",
            "website": "acme.com",
            "funding_amount": "1500000",
            "funding_date": "2026-10-01",
            "signal": {
                "source": "funding",
                "source_url": "https://n.example.com/a",
                "signal_type": "funding_round",
            },
            "contacts": [{"email": "a@acme.com", "is_primary": True}],
        }
    )
    assert c.funding_amount == Decimal("1500000")
    row = c.lead_row()
    assert row["first_source"] == "funding"
    assert row["status"] == "new"
    assert row["domain"] == "acme.com"
    assert row["funding_date"] == "2026-10-01"
    assert "signal" not in row and "contacts" not in row

    lead_id = uuid4()
    assert c.signal_row(lead_id)["lead_id"] == str(lead_id)
    assert c.contact_rows(lead_id)[0]["is_primary"] is True
    assert c.contact_rows(lead_id, allow_primary=False)[0]["is_primary"] is False
