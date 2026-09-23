"""Shared HTTP helper. Retries network faults, never retries 4xx."""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

TIMEOUT = httpx.Timeout(45.0, connect=15.0)
HEADERS = {"User-Agent": "pv-agent/3.0 (pharmacovigilance research; contact via repo)"}


class SourceUnavailable(RuntimeError):
    """A source could not be reached or returned something unusable."""


@retry(
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.NetworkError)),
    wait=wait_exponential(min=1, max=8),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _request(method: str, url: str, **kw: Any) -> httpx.Response:
    with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as client:
        return client.request(method, url, **kw)


def _send(method: str, url: str, **kw: Any) -> httpx.Response:
    try:
        r = _request(method, url, **kw)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise SourceUnavailable(f"{url}: {exc}") from exc
    if r.status_code == 404:
        raise NotFound(url)
    if r.status_code != 200:
        raise SourceUnavailable(f"{url}: http {r.status_code}")
    return r


class NotFound(SourceUnavailable):
    """404. Callers usually treat this as 'no record' rather than 'service down'."""


def get_json(url: str, params: dict[str, Any] | None = None) -> Any:
    r = _send("GET", url, params=params)
    try:
        return r.json()
    except ValueError as exc:
        raise SourceUnavailable(f"{url}: non-JSON response") from exc


def post_json(url: str, body: dict[str, Any]) -> Any:
    r = _send("POST", url, json=body)
    try:
        return r.json()
    except ValueError as exc:
        raise SourceUnavailable(f"{url}: non-JSON response") from exc


def get_bytes(url: str, timeout: float = 90.0) -> bytes:
    try:
        with httpx.Client(timeout=timeout, headers=HEADERS, follow_redirects=True) as client:
            r = client.get(url)
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise SourceUnavailable(f"{url}: {exc}") from exc
    if r.status_code == 404:
        raise NotFound(url)
    if r.status_code != 200:
        raise SourceUnavailable(f"{url}: http {r.status_code}")
    return r.content
