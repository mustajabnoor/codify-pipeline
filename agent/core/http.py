"""Shared HTTP client with polite defaults and retry/backoff for every API."""

import logging
import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "codify-pipeline/0.1 (+https://codify-labs.com)"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_ATTEMPTS = 3
MAX_RETRY_AFTER = 60.0
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def http_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
        follow_redirects=True,
        transport=transport,
    )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError):
            return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER)


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    json: Any = None,
    label: str | None = None,
    attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], None] | None = None,
) -> httpx.Response:
    """Request with exponential backoff (1s, 2s, 4s...) on network errors, 429
    and 5xx; honors Retry-After. Raises httpx.HTTPError once attempts run out
    or on any other non-2xx status. `label` replaces the URL in log lines (for
    URLs that are secrets, like a Slack webhook)."""
    shown = label or url
    for attempt in range(1, attempts + 1):
        delay = float(2 ** (attempt - 1))
        try:
            response = client.request(method, url, params=params, json=json)
        except httpx.TransportError as exc:
            if attempt == attempts:
                raise
            log.warning(
                "%s %s failed (%s); retry %d in %.0fs",
                method, shown, type(exc).__name__, attempt, delay,
            )  # fmt: skip
        else:
            if response.status_code not in RETRY_STATUS or attempt == attempts:
                response.raise_for_status()
                return response
            retry_after = _retry_after(response)
            delay = delay if retry_after is None else retry_after
            log.warning(
                "%s %s returned %d; retry %d in %.0fs",
                method, shown, response.status_code, attempt, delay,
            )  # fmt: skip
        (sleep or time.sleep)(delay)
    raise AssertionError("unreachable")


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, str] | None = None,
    attempts: int = MAX_ATTEMPTS,
    sleep: Callable[[float], None] | None = None,
) -> httpx.Response:
    return request_with_retry(client, "GET", url, params=params, attempts=attempts, sleep=sleep)
