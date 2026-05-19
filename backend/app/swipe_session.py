"""Swipe-session mirror tables + CRUD.

Mirrors the localStorage queue from frontend/src/hooks/useSwipeSession.ts so the
backend has a recovery surface (resume after crash, ETL, agent-API joins).

Local state on the frontend is the source of truth; this module is best-effort
fire-and-forget. Two tables:

    swipe_sessions(session_id, user_address, started_at, expires_at,
                   start_tx_hash, settle_tx_hash, settled_at)
    swipe_session_queue(session_id, card_id, card_hash, action, score,
                        is_tradeable, asset, entry_wei, target_wei,
                        queued_at, settled)

Idempotency: PRIMARY KEY on (session_id, card_id) — re-queuing the same swipe
inside a session is an upsert.
"""
from __future__ import annotations

import logging
from typing import Any

from app.db import _get_conn

log = logging.getLogger(__name__)

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS swipe_sessions (
    session_id      TEXT PRIMARY KEY,
    user_address    TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    start_tx_hash   TEXT,
    settle_tx_hash  TEXT,
    settled_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS swipe_sessions_user_idx
    ON swipe_sessions (user_address, started_at DESC);

CREATE TABLE IF NOT EXISTS swipe_session_queue (
    session_id    TEXT NOT NULL,
    card_id       INTEGER NOT NULL,
    card_hash     TEXT NOT NULL,
    action        TEXT NOT NULL,
    score         INTEGER NOT NULL,
    is_tradeable  BOOLEAN NOT NULL DEFAULT FALSE,
    asset         TEXT,
    entry_wei     TEXT,
    target_wei    TEXT,
    queued_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    settled       BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (session_id, card_id)
);
CREATE INDEX IF NOT EXISTS swipe_queue_session_idx
    ON swipe_session_queue (session_id, settled);
"""


def init_table() -> None:
    conn = _get_conn()
    if not conn:
        log.warning("swipe_session: DATABASE_URL not set — table init skipped")
        return
    try:
        with conn.cursor() as cur:
            cur.execute(_TABLE_DDL)
        log.info("swipe_session: tables ready")
    finally:
        conn.close()


def start(session_id: str, user_address: str, *, start_tx_hash: str | None = None,
          duration_hours: int = 24) -> None:
    conn = _get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO swipe_sessions (session_id, user_address, expires_at, start_tx_hash)
                VALUES (%s, %s, NOW() + (%s || ' hours')::interval, %s)
                ON CONFLICT (session_id) DO UPDATE
                SET start_tx_hash = COALESCE(EXCLUDED.start_tx_hash, swipe_sessions.start_tx_hash)
                """,
                (session_id, user_address.lower(), str(duration_hours), start_tx_hash),
            )
    finally:
        conn.close()


def queue(session_id: str, swipe: dict[str, Any]) -> None:
    """Upsert one swipe into the session queue. Idempotent on (session_id, card_id)."""
    conn = _get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO swipe_session_queue
                  (session_id, card_id, card_hash, action, score, is_tradeable,
                   asset, entry_wei, target_wei)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id, card_id) DO UPDATE SET
                  card_hash    = EXCLUDED.card_hash,
                  action       = EXCLUDED.action,
                  score        = EXCLUDED.score,
                  is_tradeable = EXCLUDED.is_tradeable,
                  asset        = EXCLUDED.asset,
                  entry_wei    = EXCLUDED.entry_wei,
                  target_wei   = EXCLUDED.target_wei,
                  queued_at    = NOW()
                """,
                (
                    session_id,
                    int(swipe.get("card_id", 0)),
                    swipe.get("card_hash", ""),
                    "ape" if swipe.get("is_bull") else "fade",
                    int(swipe.get("score", 0)),
                    bool(swipe.get("is_tradeable", False)),
                    swipe.get("asset"),
                    str(swipe.get("entry_wei", "0")),
                    str(swipe.get("target_wei", "0")),
                ),
            )
    finally:
        conn.close()


def settle(session_id: str, settle_tx_hash: str) -> None:
    """Mark session settled and all its queue rows settled. Idempotent."""
    conn = _get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE swipe_sessions
                   SET settle_tx_hash = COALESCE(settle_tx_hash, %s),
                       settled_at = COALESCE(settled_at, NOW())
                 WHERE session_id = %s
                """,
                (settle_tx_hash, session_id),
            )
            cur.execute(
                "UPDATE swipe_session_queue SET settled = TRUE WHERE session_id = %s",
                (session_id,),
            )
    finally:
        conn.close()


def get(session_id: str) -> dict | None:
    conn = _get_conn()
    if not conn:
        return None
    try:
        from psycopg2.extras import RealDictCursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM swipe_sessions WHERE session_id = %s",
                (session_id,),
            )
            sess = cur.fetchone()
            if not sess:
                return None
            cur.execute(
                """
                SELECT card_id, card_hash, action, score, is_tradeable,
                       asset, entry_wei, target_wei, queued_at, settled
                  FROM swipe_session_queue
                 WHERE session_id = %s
                 ORDER BY queued_at
                """,
                (session_id,),
            )
            queue_rows = [dict(r) for r in cur.fetchall()]
        result = dict(sess)
        result["queue"] = queue_rows
        return result
    finally:
        conn.close()
