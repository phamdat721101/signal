"""trading_signal_engine — produce `card_type='trading_signal'` cards
and execute them safely on SoDex perps.

Two responsibilities, both single-purpose:

  1. `build_signal_card(symbol)` — pure dict builder. Joins existing
     verdict logic (signal_engine), spot price (price_feed), and 7d
     volatility (volatility.compute_sigma_7d) into a single card dict.
     No DB writes.

  2. `safe_execute(card, user_address)` — risk-capped wrapper around
     `sodex_client.place_perps_order`. Enforces (a) global kill-switch,
     (b) per-call notional/leverage caps, (c) symbol whitelist,
     (d) per-user daily-execute cap. Persists the result via
     `db.insert_trade`. Returns `{order_id, status, qty, avg_price}` or
     a structured error dict.

SOLID notes:
  - sodex_client owns wire mechanism (signing, HTTP). This module owns
    business policy (caps, mark→qty conversion, persistence).
  - No new DB schema required: reuses existing `trades` table which
    already has `sodex_order_id` + `execution_type` columns.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app import db
from app.config import get_settings
from app.price_feed import get_price
from app.sodex_client import (
    POS_LONG,
    POS_SHORT,
    SIDE_BUY,
    SIDE_SELL,
    SODEX_QTY_RULES,
    SODEX_SYMBOL_IDS,
    TARGET_ASSETS,
    TIF_IOC,
    TYPE_MARKET,
    format_quantity,
    get_sodex_client,
    to_sodex_symbol,
    to_sodex_symbol_id,
)
from app.volatility import compute_sigma_7d

logger = logging.getLogger(__name__)

# CoinGecko IDs for our 10 curated assets. Kept here (not imported from
# signal_engine) so the trading-signal pipeline has no dependency on the
# legacy TRACKED_ASSETS map. Single source of truth for this module.
_COINGECKO_IDS: dict[str, str] = {
    "BTC":  "bitcoin",
    "ETH":  "ethereum",
    "SOL":  "solana",
    "AVAX": "avalanche-2",
    "SUI":  "sui",
    "ARB":  "arbitrum",
    "OP":   "optimism",
    "LINK": "chainlink",
    "INIT": "initia",
    "ATOM": "cosmos",
}

# Bulk-mark-price cache. One CoinGecko call per scheduler tick covers all
# 10 symbols → free-tier-friendly. Tuple = (epoch_seconds, dict[sym, info]).
_marks_cache: tuple[float, dict[str, dict[str, float]]] = (0.0, {})
_MARKS_TTL = 90  # seconds


def _bulk_fetch_marks() -> dict[str, dict[str, float]]:
    """One-shot CoinGecko query for all curated assets.

    Returns `{SYM: {price, change_24h, volume_24h, market_cap}}`. Empty
    dict if the call fails — caller falls back to price_feed.get_price.
    """
    global _marks_cache
    now = time.time()
    if now - _marks_cache[0] < _MARKS_TTL and _marks_cache[1]:
        return _marks_cache[1]
    try:
        from app import http_client
        ids = ",".join(_COINGECKO_IDS.values())
        r = http_client.get(
            "https://api.coingecko.com/api/v3/simple/price",
            service="coingecko",
            params={
                "ids": ids,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true",
            },
        )
        if not r:
            return _marks_cache[1] or {}
        data = r.json()
        id_to_sym = {v: k for k, v in _COINGECKO_IDS.items()}
        out: dict[str, dict[str, float]] = {}
        for cg_id, vals in data.items():
            sym = id_to_sym.get(cg_id)
            if not sym or "usd" not in vals:
                continue
            out[sym] = {
                "price": float(vals["usd"]),
                "change_24h": float(vals.get("usd_24h_change") or 0.0),
                "volume_24h": float(vals.get("usd_24h_vol") or 0.0),
                "market_cap": float(vals.get("usd_market_cap") or 0.0),
            }
        if out:
            _marks_cache = (now, out)
        return out
    except Exception as e:
        logger.warning("trading_signal: CoinGecko bulk fetch failed: %s", e)
        return _marks_cache[1] or {}


def _get_mark(symbol: str) -> dict[str, float] | None:
    """Mark + 24h context for one curated symbol. CG bulk first, then
    DexScreener fallback (last-ditch — `price_feed.get_price` returns
    `price_usd` rather than `price`, so we normalise here).
    """
    bulk = _bulk_fetch_marks()
    if symbol in bulk:
        return bulk[symbol]
    legacy = get_price(symbol)
    if not legacy:
        return None
    return {
        "price": float(legacy.get("price_usd") or 0.0),
        "change_24h": float(legacy.get("change_24h") or 0.0),
        "volume_24h": float(legacy.get("volume_24h") or 0.0),
        "market_cap": float(legacy.get("market_cap") or 0.0),
    }

# Default risk-band multipliers when σ_7d is unavailable.
_FALLBACK_SIGMA = 0.03           # ~3%/day implied
# Target = entry × (1 + 2σ_7d); Stop = entry × (1 − σ_7d). Asymmetric on
# purpose: we want positive expected value with 2:1 RR before fees.
_TARGET_K = 2.0
_STOP_K = 1.0


# ─── (1) Pure card builder ──────────────────────────────────────────────


def _verdict_from_signal(symbol: str, change_24h: float = 0.0) -> tuple[str, int, str]:
    """Return (verdict, confidence, reason).

    Uses the legacy `signal_engine` if it exposes a per-symbol API; else
    falls back to a simple 24h-momentum heuristic (≥1% → APE, ≤−1% →
    FADE, else weak APE/FADE biased by sign). This keeps cards
    actionable instead of defaulting every one to FADE/HOLD.
    """
    try:
        from app.signal_engine import compute_signal_for_symbol  # type: ignore
        result = compute_signal_for_symbol(f"{symbol}/USD")
        if result:
            return (result.get("verdict", "APE"),
                    int(result.get("confidence", 50)),
                    result.get("reason", ""))
    except Exception as e:
        logger.debug("signal_engine.compute_signal_for_symbol unavailable for %s: %s", symbol, e)
    # Momentum fallback. Confidence floor 35, ceiling 85.
    abs_chg = abs(change_24h)
    confidence = int(max(35, min(85, 50 + abs_chg * 2)))
    if change_24h >= 0:
        return ("APE", confidence, f"24h momentum +{change_24h:.2f}%")
    return ("FADE", confidence, f"24h momentum {change_24h:.2f}%")


def build_signal_card(symbol: str) -> Optional[dict[str, Any]]:
    """Symbol (e.g. "BTC") → card dict ready for `db.insert_card`.

    Returns None if essential data (mark price) is missing — never
    insert a half-formed card.
    """
    symbol = symbol.upper()
    if symbol not in TARGET_ASSETS:
        return None

    mark_info = _get_mark(symbol)
    if not mark_info or not mark_info.get("price"):
        logger.info("trading_signal: no price for %s, skipping", symbol)
        return None
    mark = float(mark_info["price"])
    if mark <= 0:
        return None

    sigma = compute_sigma_7d(symbol) or _FALLBACK_SIGMA
    sigma = max(0.005, min(0.20, sigma))  # clamp 0.5%–20% daily

    change_24h = float(mark_info.get("change_24h") or 0.0)
    verdict, confidence, reason = _verdict_from_signal(symbol, change_24h)
    is_long = verdict.upper() in {"APE", "BUY", "LONG"}
    direction = "LONG" if is_long else "SHORT"

    if is_long:
        target = mark * (1 + _TARGET_K * sigma)
        stop = mark * (1 - _STOP_K * sigma)
    else:
        target = mark * (1 - _TARGET_K * sigma)
        stop = mark * (1 + _STOP_K * sigma)

    s = get_settings()
    risk_label = f"${s.sodex_max_order_usd:.0f} · {s.sodex_max_leverage}x · IOC"
    sodex_pair = to_sodex_symbol(symbol) or f"{symbol}-USD (not listed)"

    return {
        "token_symbol": symbol,
        "token_name": symbol,
        "chain": "valuechain",
        "card_type": "trading_signal",
        "hook": f"{direction} {symbol} @ ${mark:,.2f}",
        "verdict": "APE" if is_long else "FADE",
        "verdict_reason": reason or f"σ7d={sigma*100:.2f}% · model={verdict}",
        "risk_level": "MID",
        "risk_score": min(95, max(5, 100 - confidence)),
        "confidence": confidence,
        "price": mark,
        "price_change_24h": float(mark_info.get("change_24h") or 0.0),
        "volume_24h": float(mark_info.get("volume_24h") or 0.0),
        "market_cap": float(mark_info.get("market_cap") or 0.0),
        "trade_plan": {
            "entry": f"${mark:,.2f}",
            "target": f"${target:,.2f}",
            "stop": f"${stop:,.2f}",
            "position_size": risk_label,
        },
        "metrics": [
            {"emoji": "📈", "label": "σ7d", "value": f"{sigma*100:.2f}%", "sentiment": "neutral"},
            {"emoji": "🎯", "label": "Target", "value": f"{((target/mark)-1)*100:+.1f}%", "sentiment": "bullish" if is_long else "bearish"},
            {"emoji": "🛑", "label": "Stop", "value": f"{((stop/mark)-1)*100:+.1f}%", "sentiment": "bearish" if is_long else "bullish"},
            {"emoji": "⚡", "label": "Venue", "value": f"SoDex perps · {sodex_pair}", "sentiment": "neutral"},
        ],
        "volatility_7d_sigma": sigma,
    }


def build_all_signal_cards() -> list[dict[str, Any]]:
    cards = []
    for sym in TARGET_ASSETS:
        c = build_signal_card(sym)
        if c:
            cards.append(c)
    return cards


def _has_recent_card(symbol: str, *, max_age_minutes: int = 8) -> bool:
    """Dedupe: skip insert if a fresh trading_signal card for this symbol
    already exists. Mirrors lp_advisory cadence guarantee.
    """
    conn = db._get_read_conn() if hasattr(db, "_get_read_conn") else db._get_conn()
    if not conn:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM cards
               WHERE card_type = 'trading_signal'
                 AND token_symbol = %s
                 AND created_at > NOW() - (%s || ' minutes')::interval
               LIMIT 1""",
            (symbol, str(max_age_minutes)),
        )
        return cur.fetchone() is not None


def generate_trading_signals() -> list[dict[str, Any]]:
    """Scheduler entry-point. Generate + persist trading_signal cards
    for the 10 target assets, deduped against rows from the last 8 min.
    Returns the list of inserted card payloads (id-stamped).
    """
    inserted: list[dict[str, Any]] = []
    for sym in TARGET_ASSETS:
        try:
            if _has_recent_card(sym):
                continue
            card = build_signal_card(sym)
            if not card:
                continue
            card_id = db.insert_card(card)
            if card_id and card_id > 0:
                card["id"] = card_id
                inserted.append(card)
        except Exception as e:
            logger.warning("trading_signal: %s gen failed: %s", sym, e)
    if inserted:
        logger.info("trading_signal: inserted %d cards (%s)",
                    len(inserted), ",".join(c["token_symbol"] for c in inserted))
    return inserted


# ─── (2) Safe execute (risk-capped order placement) ─────────────────────


class ExecuteError(Exception):
    """Raised on guard violations. `code` matches the API's HTTP detail."""
    def __init__(self, code: str, http_status: int = 422, **extra):
        super().__init__(code)
        self.code = code
        self.http_status = http_status
        self.extra = extra


def _count_user_executes_24h(user_address: str) -> int:
    """Count successful sodex executes by user in the last 24h.
    Reuses the existing `trades` table — no schema change.
    """
    conn = db._get_read_conn() if hasattr(db, "_get_read_conn") else db._get_conn()
    if not conn:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) FROM trades
               WHERE user_address = %s
                 AND sodex_order_id IS NOT NULL
                 AND created_at > NOW() - INTERVAL '24 hours'""",
            (user_address,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0


def _existing_trade_for(card_id: int, user_address: str) -> Optional[dict]:
    conn = db._get_read_conn() if hasattr(db, "_get_read_conn") else db._get_conn()
    if not conn:
        return None
    from psycopg2.extras import RealDictCursor
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """SELECT id, sodex_order_id, status FROM trades
               WHERE card_id = %s AND user_address = %s AND sodex_order_id IS NOT NULL
               LIMIT 1""",
            (card_id, user_address),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def safe_execute(card: dict, user_address: str) -> dict[str, Any]:
    """Execute a trading-signal card on SoDex perps with all risk guards.

    Raises ExecuteError on any guard violation. Returns a result dict on
    success: `{order_id, status, qty, avg_price, trade_id}`.
    """
    s = get_settings()

    # Guard 1: global kill-switch.
    if not s.sodex_trading_enabled:
        raise ExecuteError("trading_disabled", http_status=503)

    # Guard 2: card type.
    if (card.get("card_type") or "") != "trading_signal":
        raise ExecuteError("not_a_trading_signal", http_status=422)

    # Guard 3: symbol whitelist + SoDex listing.
    symbol = (card.get("token_symbol") or "").upper()
    if symbol not in TARGET_ASSETS:
        raise ExecuteError("symbol_not_supported", http_status=422, symbol=symbol)
    sodex_symbol_id = to_sodex_symbol_id(symbol)
    if sodex_symbol_id is None:
        raise ExecuteError("symbol_not_listed_on_sodex", http_status=422, symbol=symbol)
    sodex_pair = to_sodex_symbol(symbol) or f"{symbol}-USD"

    # Guard 4: idempotency — one execute per (card, user).
    prior = _existing_trade_for(int(card["id"]), user_address)
    if prior:
        raise ExecuteError(
            "already_executed",
            http_status=409,
            order_id=prior["sodex_order_id"],
            trade_id=prior["id"],
        )

    # Guard 5: per-user daily cap.
    used = _count_user_executes_24h(user_address)
    if used >= s.sodex_daily_executes_per_user:
        raise ExecuteError(
            "daily_cap_reached",
            http_status=429,
            limit=s.sodex_daily_executes_per_user,
            used=used,
        )

    # Side from verdict (APE = long, FADE = short).
    is_long = (card.get("verdict") or "APE").upper() == "APE"
    side = SIDE_BUY if is_long else SIDE_SELL
    pos_side = POS_LONG if is_long else POS_SHORT

    mark = float(card.get("price") or 0)
    if mark <= 0:
        raise ExecuteError("missing_mark_price", http_status=422)

    notional = float(s.sodex_max_order_usd)
    rules = SODEX_QTY_RULES.get(symbol)
    min_notional = float(rules["min_notional"]) if rules else 10.0
    if notional < min_notional:
        raise ExecuteError("notional_below_min", http_status=422,
                           min_notional=min_notional, configured=notional)
    raw_qty = notional / mark
    qty_str = format_quantity(symbol, raw_qty)
    if not qty_str:
        raise ExecuteError("qty_below_step", http_status=422,
                           mark=mark, notional=notional, raw_qty=raw_qty)

    client = get_sodex_client()
    if client is None:
        raise ExecuteError("sodex_disabled", http_status=503)

    # Pre-flight: align leverage. Best-effort; failure here is logged
    # but we still try to place the order (SoDex may already be at the
    # right leverage for this account).
    try:
        client.update_leverage(s.sodex_account_id, sodex_symbol_id, s.sodex_max_leverage)
    except Exception as e:
        logger.warning("update_leverage failed (non-fatal): %s", e)

    resp = client.place_perps_order(
        account_id=s.sodex_account_id,
        symbol_id=sodex_symbol_id,
        side=side,
        quantity=qty_str,
        price="0",
        time_in_force=TIF_IOC,
        order_type=TYPE_MARKET,
        position_side=pos_side,
        cl_ord_id=f"kn_{int(card['id'])}_{int(time.time())}",
    )
    if not resp or resp.get("code") not in (0, "0", None):
        logger.error("sodex order rejected: %s", resp)
        raise ExecuteError("sodex_rejected", http_status=502, raw=resp)

    data = resp.get("data") if isinstance(resp, dict) else None
    order_id = ""
    if isinstance(data, dict):
        order_id = str(data.get("orderID") or data.get("order_id") or data.get("clOrdID") or "")
    elif isinstance(data, list) and data:
        first = data[0] or {}
        order_id = str(first.get("orderID") or first.get("clOrdID") or "")
    order_id = order_id or f"kn_{int(card['id'])}_{int(time.time())}"

    trade_id = db.insert_trade({
        "card_id": int(card["id"]),
        "user_address": user_address,
        "token_symbol": symbol,
        "token_name": card.get("token_name") or symbol,
        "entry_price": mark,
        "amount_usd": notional,
        "token_amount": float(qty_str),
        "tx_hash": "",
        "status": "open",
    })
    # Stamp sodex_order_id + execution_type (additive — only new code path).
    try:
        conn = db._get_conn()
        if conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE trades SET sodex_order_id=%s, execution_type='sodex_perps' WHERE id=%s",
                    (order_id, trade_id),
                )
    except Exception as e:
        logger.error("trades.sodex_order_id update failed for trade=%s: %s", trade_id, e)

    return {
        "order_id": order_id,
        "status": "open",
        "qty": qty_str,
        "avg_price": str(mark),
        "trade_id": trade_id,
        "symbol": sodex_pair,
        "side": "long" if is_long else "short",
    }
