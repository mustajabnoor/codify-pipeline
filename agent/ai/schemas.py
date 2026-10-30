"""What Claude returns for each AI step. The JSON schema sent to the API is
derived from these models; constraints the API can't express (score range,
word limit, no links) are checked here after the response arrives."""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from agent.core.models import Channel, LeadAssessment

DRAFT_MAX_WORDS = 100
# Links only; bare product names like "Bubble.io" are fine in a first email.
_URL = re.compile(r"https?://|\bwww\.", re.I)


class Person(BaseModel):
    name: str = Field(description="Full name as written in the text.")
    role: str | None = Field(description="Job title or role, if stated.")


class Extraction(BaseModel):
    """Company facts pulled from a signal's text. Null when not stated."""

    industry: str | None = Field(description="Short industry label, e.g. 'fintech', 'e-commerce'.")
    country: str | None = Field(description="Country of the company's headquarters.")
    city: str | None = Field(description="City of the company's headquarters.")
    company_size: str | None = Field(description="Headcount or range as stated, e.g. '11-50'.")
    description: str | None = Field(description="One sentence on what the company does.")
    tech_stack: list[str] = Field(description="Technologies the company uses, lowercase.")
    people: list[Person] = Field(
        description="Named people at the company with a business role (founder, CTO, "
        "hiring manager). Empty when nobody is named."
    )


# Scoring output is stored on the lead as-is, so it lives with the core models.
Assessment = LeadAssessment


class Draft(BaseModel):
    subject: str = Field(description="Email subject line, under 8 words, no clickbait.")
    body: str = Field(
        description="Plain-text message body without greeting name placeholders, "
        "signature or opt-out line; under 100 words."
    )
    best_channel: Channel = Field(description="Best channel to send this message on.")

    @field_validator("body")
    @classmethod
    def _body_rules(cls, value: str) -> str:
        words = len(value.split())
        if words > DRAFT_MAX_WORDS:
            raise ValueError(f"body has {words} words; limit is {DRAFT_MAX_WORDS}")
        if _URL.search(value):
            raise ValueError("body must not contain links in the first email")
        return value.strip()


# Rounds as stored in leads.funding_round and listed in source_configs "rounds".
FundingRound = Literal[
    "pre-seed", "seed", "series a", "series b", "series c+", "grant", "debt", "other"
]  # fmt: skip


class Founder(BaseModel):
    name: str = Field(description="Full name as written in the article.")
    role: str | None = Field(description="Role at the company, e.g. 'CEO and co-founder'.")


class FundingExtraction(BaseModel):
    """One company's funding round, read from a news article."""

    is_single_announcement: bool = Field(
        description="True only if the article announces a funding round raised by one "
        "specific company. False for roundups of several companies, fund launches, "
        "acquisitions, IPOs, and opinion or analysis pieces."
    )
    company_name: str | None = Field(description="The company that raised the money.")
    website: str | None = Field(
        description="The company's own website exactly as linked or written in the "
        "article. Null if the article doesn't give it; never guess."
    )
    round: FundingRound | None = Field(description="Funding round as stated in the article.")
    amount: float | None = Field(description="Amount raised as a plain number, e.g. 5000000.")
    currency: str | None = Field(description="ISO 4217 code of the amount, e.g. 'USD', 'EUR'.")
    investors: list[str] = Field(description="Investors named in the article.")
    founders: list[Founder] = Field(
        description="Founders or executives of the company named in the article."
    )
    industry: str | None = Field(description="Short industry label, e.g. 'fintech'.")
    country: str | None = Field(description="Country of the company's headquarters.")
    city: str | None = Field(description="City of the company's headquarters.")
    description: str | None = Field(description="One sentence on what the company does.")
    tech_stack: list[str] = Field(description="Technologies the article says the company uses.")
