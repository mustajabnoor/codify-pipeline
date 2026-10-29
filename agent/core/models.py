from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from agent.core.normalize import normalize_domain, normalize_email, normalize_url

# Enums mirror supabase/migrations/*_enums.sql; change both together.


class LeadSource(StrEnum):
    JOB_POSTING = "job_posting"
    FUNDING = "funding"
    SOCIAL = "social"
    TECH_STACK = "tech_stack"
    GOOGLE_MAPS = "google_maps"
    PRODUCT_LAUNCH = "product_launch"
    AGENCY_PARTNER = "agency_partner"


class LeadStatus(StrEnum):
    NEW = "new"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    CONTACTED = "contacted"
    REPLIED = "replied"
    MEETING = "meeting"
    PROPOSAL = "proposal"
    WON = "won"
    LOST = "lost"
    NURTURE = "nurture"


class EmailStatus(StrEnum):
    UNVERIFIED = "unverified"
    VALID = "valid"
    RISKY = "risky"
    CATCH_ALL = "catch_all"
    INVALID = "invalid"


class Channel(StrEnum):
    EMAIL = "email"
    LINKEDIN = "linkedin"
    X = "x"
    REDDIT_REPLY = "reddit_reply"
    WHATSAPP = "whatsapp"
    PHONE = "phone"
    OTHER = "other"


class Service(StrEnum):
    MVP = "mvp"
    SAAS = "saas"
    AI_INTEGRATION = "ai_integration"
    SHOPIFY = "shopify"
    LANDING_PAGE = "landing_page"
    WEBSITE_3D = "website_3d"
    BUBBLE = "bubble"
    WHITE_LABEL = "white_label"


class OutreachStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
    REPLIED = "replied"
    BOUNCED = "bounced"


class ReplyCategory(StrEnum):
    INTERESTED = "interested"
    NOT_NOW = "not_now"
    UNSUBSCRIBE = "unsubscribe"
    WRONG_PERSON = "wrong_person"
    OTHER = "other"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SignalIn(BaseModel):
    """One buying signal: a job post, funding article, Reddit post, ..."""

    source: LeadSource
    source_url: str
    signal_type: str = Field(min_length=1)
    title: str | None = None
    raw_text: str | None = None
    detected_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source_url")
    @classmethod
    def _url(cls, value: str) -> str:
        if not value.strip().lower().startswith(("http://", "https://")):
            raise ValueError("source_url must be an http(s) URL")
        return normalize_url(value)


class ContactIn(BaseModel):
    full_name: str | None = None
    role: str | None = None
    email: str | None = None
    email_status: EmailStatus = EmailStatus.UNVERIFIED
    phone: str | None = None
    whatsapp: str | None = None
    linkedin_url: str | None = None
    x_url: str | None = None
    other_url: str | None = None
    is_primary: bool = False
    found_via: str | None = None

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        email = normalize_email(value)
        if email is None:
            raise ValueError(f"invalid email: {value!r}")
        return email

    @model_validator(mode="after")
    def _verified_needs_email(self) -> "ContactIn":
        # Only a verifier response may mark an email valid; no email, no status.
        if self.email is None and self.email_status is not EmailStatus.UNVERIFIED:
            raise ValueError("email_status set without an email")
        return self


class LeadCandidate(BaseModel):
    """What every collector yields: one signal about one company, which may or
    may not already be a lead. `domain` is derived from `website` if not given."""

    company_name: str = Field(min_length=1)
    website: str | None = None
    domain: str | None = None
    industry: str | None = None
    country: str | None = None
    city: str | None = None
    company_size: str | None = None
    description: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    funding_amount: Decimal | None = Field(default=None, ge=0)
    funding_round: str | None = None
    funding_date: date | None = None
    signal: SignalIn
    contacts: list[ContactIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derive(self) -> "LeadCandidate":
        self.domain = normalize_domain(self.domain or self.website)
        if sum(c.is_primary for c in self.contacts) > 1:
            raise ValueError("at most one primary contact")
        return self

    @property
    def source(self) -> LeadSource:
        return self.signal.source

    @property
    def emails(self) -> list[str]:
        return [c.email for c in self.contacts if c.email]

    def lead_row(self) -> dict[str, Any]:
        row = self.model_dump(mode="json", exclude={"signal", "contacts"})
        row["first_source"] = self.source.value
        row["status"] = LeadStatus.NEW.value
        return row

    def signal_row(self, lead_id: UUID) -> dict[str, Any]:
        return {**self.signal.model_dump(mode="json"), "lead_id": str(lead_id)}

    def contact_rows(self, lead_id: UUID, *, allow_primary: bool = True) -> list[dict[str, Any]]:
        rows = []
        for contact in self.contacts:
            row = {**contact.model_dump(mode="json"), "lead_id": str(lead_id)}
            if not allow_primary:
                row["is_primary"] = False
            rows.append(row)
        return rows


class SourceConfig(BaseModel):
    """A row of source_configs: keywords, subreddits, cities... for one source."""

    source: LeadSource
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class RunError(BaseModel):
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=_utcnow)


class RunStats(BaseModel):
    items_seen: int = 0
    leads_new: int = 0
    leads_updated: int = 0
    leads_skipped: int = 0
    tokens_used: int = 0
    cost_estimate: Decimal = Decimal("0")
    errors: list[RunError] = Field(default_factory=list)
