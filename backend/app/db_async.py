"""Async Postgres pool (asyncpg).

Single responsibility: provide a shared connection pool for async API handlers.
Keeps the existing sync psycopg2 codepath in db.py untouched (used by scheduler).

Supabase / pgbouncer note:
    asyncpg + pgbouncer in transaction mode can break prepared statements.
    `statement_cache_size=0` disables the prepared-statement cache, which is
    the standard fix. If you're on direct Postgres (no pgbouncer), you can
    raise this for ~10% speedup.

Usage:
    rows = await db_async.fetch_all("SELECT * FROM cards WHERE token=$1", "BTC")
    row = await db_async.fetch_one("SELECT * FROM users WHERE id=$1", uid)
    await db_async.execute("UPDATE x SET y=$1", val)
"""
import logging
from typing import Any

import asyncpg

from app.config import get_settings

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    """Initialize the pool. Idempotent — safe to call multiple times."""
    global _pool
    if _pool is not None:
        return
    s = get_settings()
    if not s.database_url:
        log.warning("DATABASE_URL not set — async pool disabled")
        return
    # Strip query-string (pgbouncer flags etc.); asyncpg uses positional/keyword args.
    url = s.database_url.split("?", 1)[0]
    try:
        _pool = await asyncpg.create_pool(
            url,
            min_size=s.db_pool_min,
            max_size=s.db_pool_max,
            max_inactive_connection_lifetime=300.0,
            command_timeout=10.0,
            statement_cache_size=0,  # pgbouncer-safe
            server_settings={"application_name": "signal-api"},
        )
        log.info("asyncpg pool ready: min=%d max=%d", s.db_pool_min, s.db_pool_max)
    except Exception as e:
        log.error("asyncpg pool init failed: %s", e)
        _pool = None


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def is_ready() -> bool:
    return _pool is not None


def _require_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_pool() at startup")
    return _pool


async def fetch_one(query: str, *args: Any) -> dict | None:
    """Returns a single row as dict, or None."""
    async with _require_pool().acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None


async def fetch_all(query: str, *args: Any) -> list[dict]:
    """Returns all rows as list of dicts."""
    async with _require_pool().acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(r) for r in rows]


async def fetch_val(query: str, *args: Any) -> Any:
    """Returns the first column of the first row, or None."""
    async with _require_pool().acquire() as conn:
        return await conn.fetchval(query, *args)


async def execute(query: str, *args: Any) -> str:
    """Execute a write/DDL. Returns the asyncpg status string (e.g. 'UPDATE 3')."""
    async with _require_pool().acquire() as conn:
        return await conn.execute(query, *args)


async def health() -> dict:
    """Lightweight health check for /api/health."""
    if _pool is None:
        return {"status": "disabled", "size": 0, "free": 0}
    try:
        async with _pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {
            "status": "ok",
            "size": _pool.get_size(),
            "free": _pool.get_idle_size(),
            "max": _pool.get_max_size(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}
