"""API clients for contact finding (Hunter.io) and email verification
(MillionVerifier). Error messages never include the request URL: MillionVerifier
takes its key as a query parameter, and errors end up in agent_runs.errors."""

import logging
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from agent.core.http import http_client, request_with_retry
from agent.core.models import EmailStatus

log = logging.getLogger(__name__)

HUNTER_URL = "https://api.hunter.io/v2"
MILLIONVERIFIER_URL = "https://api.millionverifier.com/api/v3/"
# Seconds MillionVerifier may spend on one address before answering "unknown".
VERIFY_TIMEOUT = 20
DOMAIN_SEARCH_LIMIT = 10  # one credit covers up to 10 results


class EnrichError(Exception):
    """One lookup failed for this lead; the next lead is tried normally."""


class ProviderStopped(EnrichError):
    """Key rejected or credits used up: every later call would fail too."""


class Person(BaseModel):
    """One person with an email, as Hunter returns them."""

    email: str
    first_name: str | None = None
    last_name: str | None = None
    position: str | None = None
    seniority: str | None = None  # junior / senior / executive
    department: str | None = None
    type: str | None = None  # personal / generic
    confidence: int | None = None
    linkedin: str | None = None
    twitter: str | None = None
    phone_number: str | None = None

    @property
    def full_name(self) -> str | None:
        name = " ".join(p.strip() for p in (self.first_name, self.last_name) if p and p.strip())
        return name or None


class Verification(BaseModel):
    status: EmailStatus
    result: str  # MillionVerifier's own verdict, kept on the signal


# MillionVerifier `result` -> our email_status. "error" means no verdict.
VERDICTS = {
    "ok": EmailStatus.VALID,
    "catch_all": EmailStatus.CATCH_ALL,
    "unknown": EmailStatus.RISKY,
    "disposable": EmailStatus.INVALID,
    "invalid": EmailStatus.INVALID,
}


def _get(client: httpx.Client, provider: str, url: str, params: dict[str, str]) -> Any:
    try:
        response = request_with_retry(client, "GET", url, params=params, label=provider)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        detail = _hunter_error(exc.response)
        message = f"{provider} returned HTTP {status}" + (f": {detail}" if detail else "")
        if status in (401, 403, 429):
            raise ProviderStopped(message) from None
        raise EnrichError(message) from None
    except httpx.HTTPError as exc:
        raise EnrichError(f"{provider} request failed: {type(exc).__name__}") from None
    try:
        return response.json()
    except ValueError:
        raise EnrichError(f"{provider} returned invalid JSON") from None


def _hunter_error(response: httpx.Response) -> str | None:
    try:
        errors = response.json().get("errors") or []
        return "; ".join(str(e.get("details") or e.get("id")) for e in errors) or None
    except (ValueError, AttributeError):
        return None


class Hunter:
    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = http_client(transport)
        self._client.headers["X-API-KEY"] = api_key

    def domain_search(self, domain: str) -> list[Person]:
        """People with an email at `domain`, most senior first. One credit when
        anything is found."""
        params = {"domain": domain, "limit": str(DOMAIN_SEARCH_LIMIT)}
        data = _get(self._client, "Hunter", f"{HUNTER_URL}/domain-search", params)
        people = []
        for row in (data.get("data") or {}).get("emails") or []:
            row = {**row, "email": row.get("value")}
            try:
                people.append(Person.model_validate(row))
            except ValidationError:
                log.debug("Hunter: skipping unreadable result for %s", domain)
        return people

    def email_finder(self, domain: str, full_name: str) -> Person | None:
        """The most likely email of a named person. One credit when found."""
        params = {"domain": domain, "full_name": full_name}
        try:
            data = _get(self._client, "Hunter", f"{HUNTER_URL}/email-finder", params)
        except EnrichError as exc:
            # 451: the person asked Hunter not to process their data.
            if "HTTP 451" in str(exc):
                return None
            raise
        row = data.get("data") or {}
        if not row.get("email"):
            return None
        return Person.model_validate({**row, "confidence": row.get("score")})


class MillionVerifier:
    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        self._key = api_key
        self._client = http_client(transport)

    def verify(self, email: str) -> Verification | None:
        """The verifier's verdict, or None when it couldn't decide (no status
        is ever set without one)."""
        params = {"api": self._key, "email": email, "timeout": str(VERIFY_TIMEOUT)}
        data = _get(self._client, "MillionVerifier", MILLIONVERIFIER_URL, params)
        if error := data.get("error"):
            # Errors come back as HTTP 200 with `error` set.
            stop = ("apikey", "credits", "suspended", "not_found")
            if any(word in str(error).lower() for word in stop):
                raise ProviderStopped(f"MillionVerifier: {error}")
            raise EnrichError(f"MillionVerifier: {error}")
        result = str(data.get("result") or "")
        status = VERDICTS.get(result)
        return Verification(status=status, result=result) if status else None
