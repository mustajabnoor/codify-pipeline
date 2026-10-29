from collections.abc import Callable

import httpx
import pytest

from agent.core.http import USER_AGENT, get_with_retry, http_client

URL = "https://api.example.com/items"


def client_for(*responses: httpx.Response | Exception) -> tuple[httpx.Client, list[str]]:
    queue = list(responses)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return http_client(httpx.MockTransport(handler)), seen


def recorder() -> tuple[list[float], Callable[[float], None]]:
    sleeps: list[float] = []
    return sleeps, sleeps.append


def test_retries_rate_limits_and_server_errors() -> None:
    client, seen = client_for(
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(503),
        httpx.Response(200, json={"ok": True}),
    )
    sleeps, sleep = recorder()
    response = get_with_retry(client, URL, sleep=sleep)
    assert response.json() == {"ok": True}
    assert sleeps == [0.0, 2.0]  # Retry-After honored, then exponential backoff
    assert seen == [USER_AGENT] * 3


def test_retries_network_errors() -> None:
    client, _ = client_for(httpx.ConnectError("boom"), httpx.Response(200))
    sleeps, sleep = recorder()
    assert get_with_retry(client, URL, sleep=sleep).status_code == 200
    assert sleeps == [1.0]


def test_gives_up_after_max_attempts() -> None:
    client, seen = client_for(*(httpx.Response(500) for _ in range(3)))
    sleeps, sleep = recorder()
    with pytest.raises(httpx.HTTPStatusError):
        get_with_retry(client, URL, sleep=sleep)
    assert len(seen) == 3 and sleeps == [1.0, 2.0]


def test_client_errors_are_not_retried() -> None:
    client, seen = client_for(httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        get_with_retry(client, URL, sleep=lambda _: None)
    assert len(seen) == 1


def test_retry_after_is_capped() -> None:
    client, _ = client_for(
        httpx.Response(429, headers={"Retry-After": "3600"}), httpx.Response(200)
    )
    sleeps, sleep = recorder()
    get_with_retry(client, URL, sleep=sleep)
    assert sleeps == [60.0]
