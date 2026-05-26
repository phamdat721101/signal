"""Flap Hidden Gems on X-Layer.

Single file because the curve math, the ABI fragment, the data fetcher and the
scoring rule all describe one bounded responsibility: "turn Flap on-chain state
into a gem candidate". Splitting them earlier would be premature.

Pipeline:
  1. Seed the candidate list from xlayer.taxed.fun/v2/board (cheap, off-chain).
  2. Read the canonical state from the Portal contract via getTokenV7.
  3. Compute progress (CDPV2 bonding curve), score, dedupe.

Used by scheduler._flap_scan_job and by the /api/ticker-flap endpoint.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

ONE_E18 = 10**18
DEFAULT_PORTAL_XLAYER = "0xb30D8c4216E1f21F27444D2FfAee3ad577808678"  # v4.12.1 mainnet

# Minimal ABI: only the methods we actually call. Keeps the file self-contained.
FLAP_PORTAL_ABI = [{
    "inputs": [{"name": "token", "type": "address"}],
    "name": "getTokenV7",
    "outputs": [{
        "components": [
            {"name": "status", "type": "uint8"},
            {"name": "reserve", "type": "uint256"},
            {"name": "circulatingSupply", "type": "uint256"},
            {"name": "price", "type": "uint256"},
            {"name": "tokenVersion", "type": "uint8"},
            {"name": "r", "type": "uint256"},
            {"name": "h", "type": "uint256"},
            {"name": "k", "type": "uint256"},
            {"name": "dexSupplyThresh", "type": "uint256"},
            {"name": "quoteTokenAddress", "type": "address"},
            {"name": "nativeToQuoteSwapEnabled", "type": "bool"},
            {"name": "extensionID", "type": "bytes32"},
            {"name": "taxRate", "type": "uint256"},
            {"name": "pool", "type": "address"},
            {"name": "progress", "type": "uint256"},
            {"name": "lpFeeProfile", "type": "uint8"},
            {"name": "dexId", "type": "uint8"},
        ],
        "name": "state",
        "type": "tuple",
    }],
    "stateMutability": "view",
    "type": "function",
}]
TOKEN_STATUS_TRADABLE = 1


@dataclass
class FlapGem:
    symbol: str
    name: str
    address: str
    price_usd: float
    market_cap_usd: float
    progress: float
    tax_rate_bps: int
    age_hours: float
    score: int
    signals: list[str] = field(default_factory=list)
    chain: str = "xlayer"
    risk: int = 50


# ── Curve math (CDPV2 from Flap docs, Python port) ──────────────────────────
class CDPV2:
    """Bonding curve. Params come from the chain via getTokenV7(r, h, k)."""

    def __init__(self, r: float, h: float = 0.0, k: float | None = None):
        self.r = r
        self.h = h
        self.k = k if k is not None else 1e9 * r

    def estimate_reserve(self, supply: float) -> float:
        # eth_required = k / (h + 1e9 - s) - r
        denom = 1e9 + self.h - supply
        if denom <= 0:
            return float("inf")
        return self.k / denom - self.r

    def progress(self, supply: float, dex_supply_thresh: float) -> float:
        req = self.estimate_reserve(dex_supply_thresh)
        cur = self.estimate_reserve(supply)
        if req <= 0:
            return 0.0
        return max(0.0, min(1.0, cur / req))


# ── Sources ─────────────────────────────────────────────────────────────────
async def _seed_taxed_fun_board() -> list[dict]:
    """Pull the X-Layer board. Returns [{address, age_hours, name, symbol}, ...]."""
    from app.config import get_settings
    url = get_settings().flap_taxed_fun_board_url or "https://xlayer.taxed.fun/v2/board"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers={
                "Accept": "*/*",
                "Origin": "https://flap.sh",
                "Referer": "https://flap.sh/",
                "User-Agent": "Mozilla/5.0 KineticBot/1.0",
            })
            if r.status_code != 200:
                logger.warning("flap: taxed.fun board returned %d", r.status_code)
                return []
            data = r.json()
    except Exception as e:
        logger.warning("flap: taxed.fun board fetch failed: %s", e)
        return []

    # taxed.fun shape: {newlyCreated: {coins: [...]}, trending: {coins: [...]}, ...}
    # Be defensive — accept any top-level group with a `coins` array, plus
    # the older flat shapes we previously expected.
    items: list = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for v in data.values():
            if isinstance(v, dict) and isinstance(v.get("coins"), list):
                items.extend(v["coins"])
        if not items:
            items = data.get("tokens") or data.get("data") or data.get("items") or []
    seeds: list[dict] = []
    now = time.time()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        addr = it.get("tokenAddress") or it.get("address") or it.get("token") or it.get("contract")
        if not isinstance(addr, str) or not addr.startswith("0x"):
            continue
        created = it.get("createdAt") or it.get("created_at") or it.get("timestamp") or it.get("ts")
        age_hours = None
        if isinstance(created, (int, float)) and created > 0:
            ts = created if created < 2e10 else created / 1000  # epoch s vs ms
            age_hours = max(0.0, (now - ts) / 3600)
        seeds.append({
            "address": addr.lower(),
            "age_hours": age_hours,
            "name": it.get("name"),
            "symbol": it.get("symbol"),
        })
    # dedupe + cap to 30 (matches DEXScreener bulk endpoint cap downstream)
    seen: set[str] = set()
    unique = []
    for s in seeds:
        if s["address"] in seen:
            continue
        seen.add(s["address"])
        unique.append(s)
    return unique[:30]


def _get_portal():
    """web3 + Portal contract instance, or (None, None) if not configured."""
    from app.config import get_settings
    s = get_settings()
    portal_addr = s.flap_portal_xlayer_address or DEFAULT_PORTAL_XLAYER
    rpc_url = s.xlayer_mainnet_json_rpc_url or s.xlayer_testnet_json_rpc_url
    if not portal_addr or not rpc_url:
        return None, None
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 8}))
    portal = w3.eth.contract(address=Web3.to_checksum_address(portal_addr), abi=FLAP_PORTAL_ABI)
    return w3, portal


def read_portal_state(token_address: str) -> dict | None:
    """Read getTokenV7 for one token. Sync; safe to call from worker thread."""
    _w3, portal = _get_portal()
    if not portal:
        return None
    try:
        from web3 import Web3
        s = portal.functions.getTokenV7(Web3.to_checksum_address(token_address)).call()
        keys = ["status", "reserve", "circulatingSupply", "price", "tokenVersion",
                "r", "h", "k", "dexSupplyThresh", "quoteTokenAddress", "nativeToQuoteSwapEnabled",
                "extensionID", "taxRate", "pool", "progress", "lpFeeProfile", "dexId"]
        return dict(zip(keys, s))
    except Exception as e:
        logger.debug("flap: getTokenV7 failed for %s: %s", token_address, e)
        return None


# ── Scoring ─────────────────────────────────────────────────────────────────
def _score(state: dict, age_hours: float | None, okb_usd: float) -> FlapGem | None:
    """Return a FlapGem or None. Hard filters first, then soft scoring with floor 50."""
    if state.get("status") != TOKEN_STATUS_TRADABLE:
        return None
    progress = float(state.get("progress", 0)) / ONE_E18
    if progress < 0.30:
        return None
    tax_rate = int(state.get("taxRate", 0))
    if tax_rate >= 1500:  # 15%+ is hard reject (predatory)
        return None

    score = 10  # Tradable baseline
    signals: list[str] = []

    # Progress band — the key Flap-only signal
    pct = int(progress * 100)
    if progress >= 0.90:
        score += 45; signals.append(f"🚨 {pct}% — graduation imminent")
    elif progress >= 0.70:
        score += 35; signals.append(f"🎯 {pct}% TO DEX")
    elif progress >= 0.50:
        score += 25; signals.append(f"📈 {pct}% to DEX")
    else:
        score += 15; signals.append(f"📊 {pct}% to DEX")

    # Tax shape
    if tax_rate == 0:
        score += 5; signals.append("🆓 No tax")
    elif tax_rate <= 300:
        score += 10; signals.append(f"💎 {tax_rate/100:.0f}% tax")
    elif tax_rate <= 500:
        score += 5; signals.append(f"💰 {tax_rate/100:.0f}% tax")
    elif tax_rate <= 999:
        score -= 10; signals.append(f"⚠️ {tax_rate/100:.0f}% tax")
    else:
        score -= 25; signals.append(f"⚠️ {tax_rate/100:.0f}% tax (high)")

    # Age (only when known from taxed.fun board)
    if age_hours is None:
        score += 5
    elif 1 <= age_hours <= 7 * 24:
        score += 10; signals.append(f"⏱ {int(age_hours)}h old")
    elif age_hours <= 30 * 24:
        score += 5; signals.append(f"📆 {int(age_hours/24)}d old")

    # Verified-by-Portal contract is implicit; small bonus
    score += 5

    if score < 50:
        return None

    price_usd = (float(state.get("price", 0)) / ONE_E18) * okb_usd
    circ = float(state.get("circulatingSupply", 0)) / ONE_E18
    return FlapGem(
        symbol=(state.get("symbol") or state["address"][:6]).upper()[:10],
        name=(state.get("name") or state.get("symbol") or "Flap Token")[:30],
        address=state["address"],
        price_usd=price_usd,
        market_cap_usd=price_usd * circ,
        progress=progress,
        tax_rate_bps=tax_rate,
        age_hours=age_hours or 0.0,
        score=min(100, score),
        signals=signals[:4],
        risk=max(20, 100 - score),
    )


def _recent_gem_symbols(hours: int = 6) -> set[str]:
    """6h dedupe — reuses the same helper as gem_scanner."""
    try:
        from app.db import get_recent_gem_symbols
        return get_recent_gem_symbols(hours)
    except Exception:
        return set()


def _get_okb_usd() -> float:
    """OKB price in USD. Reuses price_feed; defaults to 50 if oracle silent."""
    try:
        from app.price_feed import get_okb_usd
        return get_okb_usd()
    except Exception:
        return 50.0


# ── Main entry ──────────────────────────────────────────────────────────────
async def scan_for_flap_gems(limit: int = 5) -> list[FlapGem]:
    """Seed via taxed.fun, read truth from Portal, score, dedupe."""
    _w3, portal = _get_portal()
    if not portal:
        logger.warning("flap_scanner: Portal/RPC not configured; skipping")
        return []

    seeds = await _seed_taxed_fun_board()
    if not seeds:
        return []

    recent = _recent_gem_symbols(hours=6)
    okb_usd = _get_okb_usd()

    # Fan-out the on-chain reads via thread executor (web3.py is sync).
    loop = asyncio.get_event_loop()
    addresses = [s["address"] for s in seeds]
    states = await asyncio.gather(*[
        loop.run_in_executor(None, read_portal_state, addr)
        for addr in addresses
    ])

    age_by_addr = {s["address"]: s["age_hours"] for s in seeds}
    name_by_addr = {s["address"]: s.get("name") for s in seeds}
    sym_by_addr = {s["address"]: s.get("symbol") for s in seeds}

    gems: list[FlapGem] = []
    for addr, state in zip(addresses, states):
        if not state:
            continue
        # Inject metadata and address into state for the scorer
        state["address"] = addr
        if name_by_addr.get(addr):
            state["name"] = name_by_addr[addr]
        if sym_by_addr.get(addr):
            state["symbol"] = sym_by_addr[addr]
        sym_upper = (state.get("symbol") or "").upper()
        if sym_upper and sym_upper in recent:
            continue
        gem = _score(state, age_by_addr.get(addr), okb_usd)
        if gem:
            gems.append(gem)

    gems.sort(key=lambda g: g.score, reverse=True)
    return gems[:limit]
