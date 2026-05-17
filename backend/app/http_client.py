"""Shared HTTP client with retry + circuit breaker.

Single responsibility: outbound HTTP for all integrations.
Reuses error_tracker.CircuitBreaker so per-service health is tracked centrally.

Usage (sync, existing scheduler / content_engine):
    r = http_client.get("https://api.coingecko.com/...", service="coingecko")
    if r is None: return  # logged + breaker recorded; caller decides fallback

Usage (async, new API handlers):
    r = await http_client.aget("https://api.sosovalue.com/...", service="sosovalue")

A `None` return means: permanent failure for this attempt (retries exhausted
or circuit open). The error is already logged + tracked. Callers degrade
gracefully rather than raising.
"""
import asyncio
import logging
import time
from typing import Any

import httpx

from app.error_tracker import error_tracker

log = logging.getLogger(__name__)

_RETRY_STATUSES = (429, 500, 502, 503, 504)
_RETRYABLE_EXC = (httpx.TimeoutException, httpx.NetworkError)

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=5.0)
_DEFAULT_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)

_sync: httpx.Client | None = None
_async: httpx.AsyncClient | None = None


def _sync_client() -> httpx.Client:
    global _sync
    if _sync is None:
        _sync = httpx.Client(
            timeout=_DEFAULT_TIMEOUT,
            limits=_DEFAULT_LIMITS,
            headers={"User-Agent": "Signal-API/1.0"},
        )
    return _sync


def _async_client() -> httpx.AsyncClient:
    global _async
    if _async is None:
        _async = httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            limits=_DEFAULT_LIMITS,
            headers={"User-Agent": "Signal-API/1.0"},
        )
    return _async


def _backoff(attempt: int, retry_after: str | None) -> float:
    base = 0.5 * (2 ** attempt)
    if retry_after:
        try:
            return max(base, float(retry_after))
        except ValueError:
            pass
    return base


def _open_breaker_or_none(service: str):
    """Return breaker if request may proceed, else None (circuit open)."""
    breaker = error_tracker.get_breaker(service, threshold=5, cooldown=60.0)
    if breaker.is_open:
        log.warning("[%s] circuit open, skipping request", service)
        return None
    return breaker


def _track_failure(service: str, breaker, code: str, message: str, ctx: dict) -> None:
    breaker.record_failure()
    error_tracker.track(code, f"{service}: {message}", {**ctx, "service": service})


def request_sync(
    method: str,
    url: str,
    *,
    service: str,
    retries: int = 3,
    expected_status: tuple[int, ...] = (200, 201),
    **kwargs: Any,
) -> httpx.Response | None:
    """Sync HTTP with retry+breaker. Returns Response on success, None on permanent failure."""
    breaker = _open_breaker_or_none(service)
    if breaker is None:
        return None

    client = _sync_client()
    for attempt in range(retries + 1):
        try:
            r = client.request(method, url, **kwargs)
            if r.status_code in expected_status:
                breaker.record_success()
                return r
            if r.status_code in _RETRY_STATUSES and attempt < retries:
                wait = _backoff(attempt, r.headers.get("Retry-After"))
                log.warning("[%s] %d retry %d/%d in %.1fs", service, r.status_code, attempt + 1, retries, wait)
                time.sleep(wait)
                continue
            _track_failure(service, breaker, f"HTTP_{r.status_code}",
                           f"{method} {url} -> {r.status_code}",
                           {"url": url, "status": r.status_code, "body": r.text[:200]})
            return None
        except _RETRYABLE_EXC as e:
            if attempt < retries:
                wait = _backoff(attempt, None)
                log.warning("[%s] %s retry %d/%d in %.1fs", service, type(e).__name__, attempt + 1, retries, wait)
                time.sleep(wait)
                continue
            _track_failure(service, breaker, "HTTP_NETWORK", f"{type(e).__name__}: {e}", {"url": url})
            return None
    return None


async def request_async(
    method: str,
    url: str,
    *,
    service: str,
    retries: int = 3,
    expected_status: tuple[int, ...] = (200, 201),
    **kwargs: Any,
) -> httpx.Response | None:
    """Async HTTP with retry+breaker. Same contract as request_sync."""
    breaker = _open_breaker_or_none(service)
    if breaker is None:
        return None

    client = _async_client()
    for attempt in range(retries + 1):
        try:
            r = await client.request(method, url, **kwargs)
            if r.status_code in expected_status:
                breaker.record_success()
                return r
            if r.status_code in _RETRY_STATUSES and attempt < retries:
                wait = _backoff(attempt, r.headers.get("Retry-After"))
                log.warning("[%s] %d retry %d/%d in %.1fs", service, r.status_code, attempt + 1, retries, wait)
                await asyncio.sleep(wait)
                continue
            _track_failure(service, breaker, f"HTTP_{r.status_code}",
                           f"{method} {url} -> {r.status_code}",
                           {"url": url, "status": r.status_code, "body": r.text[:200]})
            return None
        except _RETRYABLE_EXC as e:
            if attempt < retries:
                wait = _backoff(attempt, None)
                log.warning("[%s] %s retry %d/%d in %.1fs", service, type(e).__name__, attempt + 1, retries, wait)
                await asyncio.sleep(wait)
                continue
            _track_failure(service, breaker, "HTTP_NETWORK", f"{type(e).__name__}: {e}", {"url": url})
            return None
    return None


# Convenience wrappers
def get(url: str, *, service: str, **kwargs) -> httpx.Response | None:
    return request_sync("GET", url, service=service, **kwargs)


def post(url: str, *, service: str, **kwargs) -> httpx.Response | None:
    return request_sync("POST", url, service=service, **kwargs)


async def aget(url: str, *, service: str, **kwargs) -> httpx.Response | None:
    return await request_async("GET", url, service=service, **kwargs)


async def apost(url: str, *, service: str, **kwargs) -> httpx.Response | None:
    return await request_async("POST", url, service=service, **kwargs)


def close_sync() -> None:
    global _sync
    if _sync:
        _sync.close()
        _sync = None


async def close_async() -> None:
    global _async
    if _async:
        await _async.aclose()
        _async = None
