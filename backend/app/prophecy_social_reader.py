"""Prophecy.social on-chain reader — Somnia mainnet (5031) RPC primary, HTTP fallback.

SOLID:
- SRP: this module owns ONE concern — translating Prophecy.social market data
  into typed Python objects. No card generation, no swipe logic, no chain
  writes. Read-only.
- OCP: ABI loaded from `app/abis/prophecy_market.json`; swap function names
  by editing that JSON, no code changes here.
- DIP: depends on `http_client` (centralized retry + circuit breaker) and
  on web3 lazy-init helpers; no direct httpx and no cross-module imports.

Cross-chain note: the rest of Kinetic writes to Somnia testnet 50312. THIS
module only reads from Somnia mainnet 5031 (where Prophecy lives). The
mainnet RPC URL comes from `settings.somnia_mainnet_rpc`.

Graceful degradation:
- Missing config (no `prophecy_market_address`) → skip RPC path, try HTTP.
- RPC error / web3 unavailable                  → fall back to HTTP.
- HTTP also fails                               → return empty / None.

Caching:
- Open-markets list: TTL = `settings.prophecy_cache_ttl_seconds` (default 15 min).
- Single market by id: 60s for open, infinite for resolved (resolved is immutable).
- Resolution receipt: infinite (post-resolution data is immutable).
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Iterator, Optional

from app import http_client
from app.config import get_settings

log = logging.getLogger(__name__)

_ABI_PATH = Path(__file__).resolve().parent / "abis" / "prophecy_market.json"
_IPFS_GATEWAYS = (
    "https://ipfs.io/ipfs/",
    "https://cloudflare-ipfs.com/ipfs/",
    "https://gateway.pinata.cloud/ipfs/",
)


# ─── Types (inline; one file = one module) ────────────────────────────


class ProphecyCategory(IntEnum):
    SPORTS = 0
    CRYPTO = 1
    POLITICS = 2
    CULTURE = 3


class MarketStatus(IntEnum):
    OPEN = 0
    RESOLVING = 1
    RESOLVED = 2


@dataclass(frozen=True)
class ProphecyMarket:
    id: int
    question: str
    creator: str
    category: ProphecyCategory
    deadline: int                       # unix seconds
    resolution_criteria: str
    status: MarketStatus
    yes_pool: int                       # PST raw (assume 18 decimals at consumers)
    no_pool: int
    consensus_threshold: int
    outcome: Optional[bool] = None      # only meaningful when RESOLVED
    receipt_uri: Optional[str] = None

    @property
    def is_resolved(self) -> bool:
        return self.status == MarketStatus.RESOLVED

    @property
    def total_pool(self) -> int:
        return self.yes_pool + self.no_pool

    @property
    def yes_odds(self) -> float:
        t = self.total_pool
        return (self.yes_pool / t) if t > 0 else 0.5

    @property
    def no_odds(self) -> float:
        return 1.0 - self.yes_odds

    @property
    def time_remaining_seconds(self) -> int:
        return max(0, self.deadline - int(time.time()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "creator": self.creator,
            "category": int(self.category),
            "deadline": self.deadline,
            "resolution_criteria": self.resolution_criteria,
            "status": int(self.status),
            "yes_pool": str(self.yes_pool),
            "no_pool": str(self.no_pool),
            "consensus_threshold": self.consensus_threshold,
            "outcome": self.outcome,
            "receipt_uri": self.receipt_uri,
        }


@dataclass(frozen=True)
class ResolutionReceipt:
    market_id: int
    sources: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    agent_votes: list[dict] = field(default_factory=list)
    final_outcome: Optional[bool] = None


# ─── Caching (tiny in-process; Redis deferred per project conventions) ──


_open_cache: tuple[float, list[ProphecyMarket]] | None = None
_market_cache: dict[int, tuple[float, ProphecyMarket]] = {}
_receipt_cache: dict[int, ResolutionReceipt] = {}
_health: dict[str, Any] = {"contract_reachable": None, "api_reachable": None, "last_checked_at": 0}


def _cache_get_open(ttl: float) -> list[ProphecyMarket] | None:
    if _open_cache is None:
        return None
    ts, value = _open_cache
    return value if (time.time() - ts) < ttl else None


def _cache_set_open(value: list[ProphecyMarket]) -> None:
    global _open_cache
    _open_cache = (time.time(), value)


def _cache_get_market(market_id: int) -> ProphecyMarket | None:
    hit = _market_cache.get(market_id)
    if hit is None:
        return None
    ts, value = hit
    # Resolved markets are immutable — skip TTL.
    if value.is_resolved:
        return value
    return value if (time.time() - ts) < 60 else None


def _cache_set_market(value: ProphecyMarket) -> None:
    _market_cache[value.id] = (time.time(), value)


# ─── Web3 init (lazy; tolerates missing dep / config) ────────────────


_w3 = None
_contract = None


def _abi() -> list[dict]:
    return json.loads(_ABI_PATH.read_text())


def _get_contract():
    """Return (w3, contract) or (None, None) if not configured / unavailable."""
    global _w3, _contract
    if _contract is not None:
        return _w3, _contract
    s = get_settings()
    if not s.prophecy_market_address or not s.somnia_mainnet_rpc:
        return None, None
    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(s.somnia_mainnet_rpc, request_kwargs={"timeout": 10}))
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(s.prophecy_market_address),
            abi=_abi(),
        )
        _w3, _contract = w3, contract
        return _w3, _contract
    except Exception as e:                            # noqa: BLE001 — fail-open to HTTP fallback
        log.warning("prophecy_reader: web3 init failed (%s); HTTP fallback only", e)
        return None, None


# ─── Decoders ─────────────────────────────────────────────────────────


def _decode_rpc_market(raw: tuple, market_id: int) -> ProphecyMarket:
    (
        question, creator, category, deadline, criteria,
        status, yes_pool, no_pool, threshold, outcome, receipt_uri,
    ) = raw
    return ProphecyMarket(
        id=market_id,
        question=question,
        creator=creator,
        category=ProphecyCategory(int(category)),
        deadline=int(deadline),
        resolution_criteria=criteria,
        status=MarketStatus(int(status)),
        yes_pool=int(yes_pool),
        no_pool=int(no_pool),
        consensus_threshold=int(threshold),
        outcome=bool(outcome) if int(status) == int(MarketStatus.RESOLVED) else None,
        receipt_uri=receipt_uri or None,
    )


# ─── Public API ───────────────────────────────────────────────────────


def fetch_market(market_id: int) -> Optional[ProphecyMarket]:
    """One market by id. RPC primary, HTTP fallback. None on permanent failure."""
    cached = _cache_get_market(market_id)
    if cached is not None:
        return cached

    _, contract = _get_contract()
    if contract is not None:
        try:
            raw = contract.functions.getMarket(market_id).call()
            m = _decode_rpc_market(raw, market_id)
            _cache_set_market(m)
            _health["contract_reachable"] = True
            _health["last_checked_at"] = int(time.time())
            return m
        except Exception as e:                        # noqa: BLE001
            log.warning("prophecy_reader: getMarket(%d) RPC failed (%s); trying HTTP", market_id, e)
            _health["contract_reachable"] = False

    s = get_settings()
    m = _http_fetch_single_market(s, market_id)
    if m is None:
        _health["api_reachable"] = False
        return None
    _health["api_reachable"] = True
    _health["last_checked_at"] = int(time.time())
    _cache_set_market(m)
    return m


def fetch_open_markets(
    category: Optional[ProphecyCategory] = None,
    limit: int = 50,
) -> list[ProphecyMarket]:
    """Open markets, sorted by deadline asc. Cached for the configured TTL.

    RPC path enumerates `marketCount() - 1 ... 0`, decodes, filters status=OPEN.
    HTTP path hits `/markets?status=open[&category=...]&limit=`.
    """
    s = get_settings()
    cached = _cache_get_open(float(s.prophecy_cache_ttl_seconds))
    if cached is not None:
        return _filter_and_limit(cached, category, limit)

    _, contract = _get_contract()
    markets: list[ProphecyMarket] = []
    if contract is not None:
        try:
            count = int(contract.functions.marketCount().call())
            # Walk newest-first; bound the scan so over-large registries
            # don't blow up the call. limit*4 is a safety margin to find
            # `limit` OPEN markets after status filtering.
            scan = min(count, max(limit * 4, 100))
            for i in range(count - 1, count - 1 - scan, -1):
                if i < 0:
                    break
                try:
                    raw = contract.functions.getMarket(i).call()
                    m = _decode_rpc_market(raw, i)
                    if m.status == MarketStatus.OPEN:
                        markets.append(m)
                except Exception as inner:            # noqa: BLE001 — single-market read should not abort the batch
                    log.debug("prophecy_reader: skip market %d (%s)", i, inner)
            _health["contract_reachable"] = True
        except Exception as e:                        # noqa: BLE001
            log.warning("prophecy_reader: marketCount RPC failed (%s); HTTP fallback", e)
            _health["contract_reachable"] = False
            markets = []

    if not markets:
        markets = _http_fetch_open_markets(s, limit=limit * 2)

    _health["last_checked_at"] = int(time.time())
    _cache_set_open(markets)
    return _filter_and_limit(markets, category, limit)


def fetch_resolution_receipt(market_id: int) -> Optional[ResolutionReceipt]:
    """Resolved-market receipt (sources/findings/agent_votes). Cached forever."""
    if market_id in _receipt_cache:
        return _receipt_cache[market_id]
    market = fetch_market(market_id)
    if market is None or not market.is_resolved or not market.receipt_uri:
        return None

    payload = _fetch_uri_json(market.receipt_uri)
    if payload is None:
        return None
    receipt = ResolutionReceipt(
        market_id=market_id,
        sources=list(payload.get("sources", [])),
        findings=list(payload.get("findings", [])),
        agent_votes=list(payload.get("agent_votes", [])),
        final_outcome=payload.get("final_outcome", market.outcome),
    )
    _receipt_cache[market_id] = receipt
    return receipt


def fetch_recent_resolutions(since_block: int, limit: int = 20) -> list[ProphecyMarket]:
    """Markets that emitted MarketResolved at block >= `since_block`. Used by the relay.

    Only the RPC path supports event scanning. If RPC is unavailable we
    return [] rather than HTTP-paging — the caller (poller) treats empty
    as "advance the cursor when ready" and tries again next tick.
    """
    _, contract = _get_contract()
    if contract is None:
        return []
    try:
        event = contract.events.MarketResolved
        logs = event.get_logs(fromBlock=int(since_block))
    except Exception as e:                            # noqa: BLE001
        log.warning("prophecy_reader: MarketResolved getLogs failed (%s)", e)
        return []
    out: list[ProphecyMarket] = []
    seen: set[int] = set()
    # Newest first, capped at `limit`. Re-fetch the full market so we
    # carry deadline + pools + outcome in one return type.
    for entry in reversed(logs[-limit * 2 :] if limit > 0 else logs):
        try:
            mid = int(entry["args"]["marketId"])
        except Exception:                              # noqa: BLE001
            continue
        if mid in seen:
            continue
        seen.add(mid)
        m = fetch_market(mid)
        if m is not None:
            out.append(m)
        if len(out) >= limit:
            break
    return out


def health_check() -> dict:
    """Snapshot for /api/health. None means 'never tried'."""
    return dict(_health)


# ─── Internals ────────────────────────────────────────────────────────


def _filter_and_limit(
    markets: list[ProphecyMarket],
    category: Optional[ProphecyCategory],
    limit: int,
) -> list[ProphecyMarket]:
    out = [m for m in markets if (category is None or m.category == category)]
    out.sort(key=lambda m: m.deadline)
    return out[:limit]


def _http_fetch_open_markets(s, limit: int) -> list[ProphecyMarket]:
    """Fallback path — parse Prophecy's home-page React-server-component stream.

    Prophecy.social is a Next.js SSR app. The home page server-renders the
    full open-markets list inline as `self.__next_f.push([1,"<json>"])`
    chunks. There's no public REST list endpoint (verified 2026-06-09).
    Concatenating + JSON-decoding the chunks reconstructs the full payload,
    from which we extract every `"markets":[...]` array we find.
    """
    r = http_client.get(s.prophecy_api_base_url, service="prophecy_api")
    if r is None:
        _health["api_reachable"] = False
        return []
    _health["api_reachable"] = True
    return _parse_homepage_markets(r.text)[:limit] if limit > 0 else _parse_homepage_markets(r.text)


def _http_fetch_single_market(s, market_id: int) -> Optional[ProphecyMarket]:
    """Find one market by id from the home-page render. Stable for v1."""
    for m in _http_fetch_open_markets(s, limit=0):           # 0 = unbounded
        if m.id == market_id:
            return m
    return None


def _fetch_uri_json(uri: str) -> dict | None:
    """HTTPS direct, or IPFS via 3-gateway round-robin."""
    if uri.startswith("ipfs://"):
        cid = uri[len("ipfs://") :]
        for gw in _IPFS_GATEWAYS:
            r = http_client.get(gw + cid, service="prophecy_ipfs")
            if r is not None:
                try:
                    return r.json()
                except Exception:                      # noqa: BLE001
                    continue
        return None
    if uri.startswith("http://") or uri.startswith("https://"):
        r = http_client.get(uri, service="prophecy_ipfs")
        if r is None:
            return None
        try:
            return r.json()
        except Exception:                              # noqa: BLE001
            return None
    return None


# Test hook — `tests/test_prophecy_reader.py` resets caches between cases.
def _reset_caches_for_test() -> None:
    global _open_cache, _market_cache, _receipt_cache
    _open_cache = None
    _market_cache = {}
    _receipt_cache = {}


# ─── Homepage RSC parser ─────────────────────────────────────────────
#
# Prophecy.social renders its market feed via Next.js Server Components.
# The home page emits a series of `self.__next_f.push([1,"<chunk>"])` calls
# whose concatenated, JSON-decoded payload contains every `"markets":[...]`
# array the page displays. We treat that as our public read surface until
# either prophecy.social ships a documented REST API or the contract
# addresses are confirmed (Day-0).
#
# The parser is dependency-free and tolerant: malformed chunks are skipped,
# only objects with `marketId` + `question` keys are accepted, and dupes
# across multiple `markets` arrays are de-duplicated by `marketId`.


_NEXT_F_RE = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')

_HOMEPAGE_CATEGORY_MAP: dict[str, ProphecyCategory] = {
    "crypto":      ProphecyCategory.CRYPTO,
    "politics":    ProphecyCategory.POLITICS,
    "sport":       ProphecyCategory.SPORTS,
    "sports":      ProphecyCategory.SPORTS,
    "pop_culture": ProphecyCategory.CULTURE,
    "culture":     ProphecyCategory.CULTURE,
    "technology":  ProphecyCategory.CULTURE,           # collapse — no tech enum value
}


def _parse_homepage_markets(html: str) -> list[ProphecyMarket]:
    """Return every ProphecyMarket found embedded in a Prophecy SSR home page.

    Pure: no I/O, no caching. Test seam — `_http_fetch_open_markets`
    drives this with the live HTTP body.
    """
    blob = _decode_next_f_stream(html)
    if not blob:
        return []
    seen: dict[int, ProphecyMarket] = {}
    for arr_text in _iter_market_arrays(blob):
        try:
            arr = json.loads(arr_text)
        except Exception:                               # noqa: BLE001
            continue
        if not isinstance(arr, list):
            continue
        for item in arr:
            if not isinstance(item, dict):
                continue
            mid = item.get("marketId")
            if not isinstance(mid, int) or "question" not in item:
                continue
            try:
                seen[mid] = _decode_homepage_market(item)
            except Exception as e:                      # noqa: BLE001
                log.debug("prophecy_reader: homepage decode skip mid=%s (%s)", mid, e)
    out = list(seen.values())
    out.sort(key=lambda m: m.deadline)
    return out


def _decode_next_f_stream(html: str) -> str:
    """Concatenate JSON-decoded chunks emitted by `self.__next_f.push`."""
    pieces: list[str] = []
    for raw in _NEXT_F_RE.findall(html):
        try:
            pieces.append(json.loads('"' + raw + '"'))
        except Exception:                               # noqa: BLE001 — best-effort
            continue
    return "".join(pieces)


def _iter_market_arrays(blob: str) -> Iterator[str]:
    """Yield each `[...]` text immediately following a `"markets":` key.

    Walks bracket depth + string quoting to find the matching `]` without
    a full JSON parse of the entire blob.
    """
    needle = '"markets":['
    n = len(blob)
    cursor = 0
    while True:
        idx = blob.find(needle, cursor)
        if idx == -1:
            return
        start = idx + len('"markets":')                 # points at the '['
        depth = 0
        in_str = False
        esc = False
        j = start
        end = -1
        while j < n:
            ch = blob[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == '\\':
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == '[':
                    depth += 1
                elif ch == ']':
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            j += 1
        if end == -1:
            return
        yield blob[start:end + 1]
        cursor = end + 1


def _parse_iso_to_unix(iso: str | None) -> int:
    if not iso:
        return 0
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except Exception:                                   # noqa: BLE001
        return 0


def _decode_homepage_market(p: dict) -> ProphecyMarket:
    """Map the Next.js home-page market shape onto our ProphecyMarket dataclass.

    Verified against live data 2026-06-09: keys observed are `id` (uuid),
    `marketId` (int), `question`, `category`, `status`, `yesPrice`, `noPrice`,
    `volume`, `closeTs` (ISO), `creatorWallet`, `dbOutcome`, `resolutionEndTs`.
    Prices are probabilities in [0, 1]; we scale into PST-decimal-equivalent
    pool integers so `yes_odds` / `total_pool` math downstream is unchanged.
    """
    cat = _HOMEPAGE_CATEGORY_MAP.get((p.get("category") or "").lower(), ProphecyCategory.CULTURE)
    deadline = _parse_iso_to_unix(p.get("closeTs") or p.get("resolutionEndTs"))
    yes = float(p.get("yesPrice") if p.get("yesPrice") is not None else 0.5)
    no  = float(p.get("noPrice")  if p.get("noPrice")  is not None else (1.0 - yes))
    yes_pool = int(max(0.0, min(yes, 1.0)) * 10**18)
    no_pool  = int(max(0.0, min(no,  1.0)) * 10**18)
    status_raw = (p.get("status") or "active").lower()
    if status_raw == "resolved":
        status = MarketStatus.RESOLVED
    elif status_raw in ("resolving", "settling"):
        status = MarketStatus.RESOLVING
    else:
        status = MarketStatus.OPEN
    outcome_raw = p.get("dbOutcome")
    if isinstance(outcome_raw, str):
        outcome = outcome_raw.upper() == "YES"
    elif isinstance(outcome_raw, bool):
        outcome = outcome_raw
    else:
        outcome = None
    # Title composition — Prophecy mixes binary markets ("Will BTC be above
    # $X?") with multi-option events whose per-option markets carry only an
    # option label (e.g. "Up") under a shared `eventName` ("Bitcoin: Up or
    # Down in 20 Minutes?"). Readable title rule:
    #   * if `question` already reads like a question (has '?' or >= 40 chars)
    #     → use it verbatim;
    #   * else compose "<eventName> — <question>" so the swiper sees the full
    #     context instead of the bare option word.
    raw_question = str(p.get("question") or "")
    event_name = str(p.get("eventName") or "")
    if event_name and event_name != raw_question and "?" not in raw_question and len(raw_question) < 40:
        question = f"{event_name} — {raw_question}".strip(" —")
    else:
        question = raw_question or event_name
    return ProphecyMarket(
        id=int(p["marketId"]),
        question=question,
        creator=str(p.get("creatorWallet") or ""),
        category=cat,
        deadline=deadline,
        resolution_criteria=str(p.get("resolutionCriteria") or ""),
        status=status,
        yes_pool=yes_pool,
        no_pool=no_pool,
        consensus_threshold=int(p.get("consensusThreshold") or 3),
        outcome=outcome if status == MarketStatus.RESOLVED else None,
        receipt_uri=None,
    )
