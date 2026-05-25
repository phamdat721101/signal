"""XLayerClient — read-only helper for /api/cards/{id}/play.

Single responsibility: encode the calldata bundle the FE needs to summon a card
on X Layer (testnet 1952 / mainnet 196). The contract minting/owning is handled
in chain.py's ChainClient pattern; this module is *read-only* — it does not
broadcast anything, only encodes function calls.

SOLID:
  - One class. One reason to change (X Layer contract ABIs).
  - Tick math matches Solidity TickMath via log(price) / log(1.0001), tick-spacing rounded.
  - No global state. No side effects beyond pure encoding.
  - Lazy web3 import — keeps import cost zero when unused.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Iterable

# Permit2 (canonical Uniswap, same address every chain)
PERMIT2_ADDRESS = "0x000000000022D473030F116dDEE9F6B43aC78BA3"

# Tick spacing for the v4 OKB/USDC pool (matches deployment script).
TICK_SPACING = 60

# Selectors (precomputed — keeps web3 import lazy).
# Stored without 0x prefix; encode_approve / encode_play_card prepend "0x" exactly once.
SEL_APPROVE = "095ea7b3"  # approve(address,uint256)
# playCard(uint256 cardId, uint128 liquidity, uint256 amount0Max, uint256 amount1Max, uint256 deadline)
SEL_PLAY_CARD = "0x4f6c2a17"  # placeholder; recomputed via _selector at runtime if needed


@dataclass(frozen=True)
class PlayBundle:
    card_id: int
    chain_id: int
    tick_lower: int
    tick_upper: int
    router: str
    okb: str
    usdc: str
    amount0_max: int  # OKB max
    amount1_max: int  # USDC max
    liquidity: int    # uint128 — caller-side guesstimate, contract clamps
    calls: list[dict]  # ordered: [approve_okb, approve_usdc, play_card]
    deadline: int


def price_to_tick(price: float) -> int:
    """Solidity TickMath equivalent: tick = floor(log(price) / log(1.0001))."""
    if price <= 0:
        raise ValueError(f"price must be > 0, got {price}")
    return int(math.floor(math.log(price) / math.log(1.0001)))


def round_to_spacing(tick: int, *, ceil: bool, spacing: int = TICK_SPACING) -> int:
    """Round tick to spacing, ceil for upper bound, floor (toward 0) for lower."""
    if ceil:
        return ((tick + spacing - 1) // spacing) * spacing
    return (tick // spacing) * spacing


def compute_card_ticks(entry: float, target: float, stop: float, is_bull: bool) -> tuple[int, int]:
    """Backend mirror of Solidity tick computation.

    For APE (is_bull=True): range is [stopTick, targetTick] (price rises through entry).
    For FADE (is_bull=False): backend swaps so the LP captures fees as price falls.
    Returns (tickLower, tickUpper) with tickLower < tickUpper.
    """
    t_stop = price_to_tick(stop)
    t_target = price_to_tick(target)
    if is_bull:
        lower = round_to_spacing(min(t_stop, t_target), ceil=False)
        upper = round_to_spacing(max(t_stop, t_target), ceil=True)
    else:
        # FADE: short-side range placement. Same arithmetic; direction lives in card.is_bull.
        lower = round_to_spacing(min(t_stop, t_target), ceil=False)
        upper = round_to_spacing(max(t_stop, t_target), ceil=True)
    if upper <= lower:
        upper = lower + TICK_SPACING
    return lower, upper


def _hex32(n: int) -> str:
    """Encode a uint256/int256 as a 32-byte hex word."""
    if n < 0:
        # two's complement for int24/etc inside int256 word
        n = (1 << 256) + n
    return f"{n:064x}"


def _hex_addr(addr: str) -> str:
    """Normalize an EVM address into a 32-byte word (left-padded)."""
    a = addr.lower().replace("0x", "")
    return ("0" * (64 - len(a))) + a


def encode_approve(token: str, spender: str, amount: int) -> dict:
    """Returns {to, data} for ERC20 approve(spender, amount)."""
    data = SEL_APPROVE + _hex_addr(spender) + _hex32(amount)
    return {"to": token, "data": "0x" + data}


def encode_play_card(
    router: str,
    *,
    card_id: int,
    liquidity: int,
    amount0_max: int,
    amount1_max: int,
    deadline: int,
) -> dict:
    """Returns {to, data} for SignalCardRouter.playCard(...).

    The selector is recomputed lazily so we do not pin web3 as an import.
    Web3.keccak(...).hex() returns either '0x...' (web3.py 6.x+) or '...' (5.x);
    we strip the prefix defensively and take EXACTLY 4 bytes (8 hex chars) for
    the function selector, then prepend '0x' once at the data boundary.
    """
    from web3 import Web3

    sig = "playCard(uint256,uint128,uint256,uint256,uint256)"
    raw = Web3.keccak(text=sig).hex()
    if raw.startswith("0x"):
        raw = raw[2:]
    selector = raw[:8]  # 4-byte function selector
    body = (
        _hex32(card_id)
        + _hex32(liquidity)
        + _hex32(amount0_max)
        + _hex32(amount1_max)
        + _hex32(deadline)
    )
    return {"to": router, "data": "0x" + selector + body}


def build_play_bundle(
    *,
    card_id: int,
    chain_id: int,
    entry: float,
    target: float,
    stop: float,
    is_bull: bool,
    router: str,
    okb: str,
    usdc: str,
    okb_usd_price: float,
    suggested_usd: float = 50.0,
    deadline_seconds: int = 3600,
) -> PlayBundle:
    """Assemble the full call bundle the frontend needs to summon a card.

    Calls are ordered: approve OKB → approve USDC → playCard.
    Amounts default to ~$50/$50 split — caller can override post-event.
    """
    lower, upper = compute_card_ticks(entry, target, stop, is_bull)

    amount0_max = int(suggested_usd / max(okb_usd_price, 1e-9) * 10**18)  # OKB has 18 dec
    amount1_max = int(suggested_usd * 10**6)  # USDC has 6 dec

    # Liquidity: contract clamps via amount maxes; this is just a generous upper hint.
    liquidity = 10**24

    deadline = int(time.time()) + deadline_seconds

    calls = [
        encode_approve(okb, router, amount0_max),
        encode_approve(usdc, router, amount1_max),
        encode_play_card(
            router,
            card_id=card_id,
            liquidity=liquidity,
            amount0_max=amount0_max,
            amount1_max=amount1_max,
            deadline=deadline,
        ),
    ]

    return PlayBundle(
        card_id=card_id,
        chain_id=chain_id,
        tick_lower=lower,
        tick_upper=upper,
        router=router,
        okb=okb,
        usdc=usdc,
        amount0_max=amount0_max,
        amount1_max=amount1_max,
        liquidity=liquidity,
        calls=calls,
        deadline=deadline,
    )


def explorer_tx_url(tx_hash: str, chain_id: int) -> str:
    """Public OKLink explorer URL for a tx."""
    base = "https://www.oklink.com/xlayer-test" if chain_id == 1952 else "https://www.oklink.com/xlayer"
    return f"{base}/tx/{tx_hash}"


@dataclass(frozen=True)
class CloseBundle:
    card_id: int
    chain_id: int
    router: str
    calls: list[dict]
    deadline: int


def encode_close_card(
    router: str,
    *,
    card_id: int,
    liquidity: int,
    amount0_min: int,
    amount1_min: int,
    deadline: int,
) -> dict:
    """Returns {to, data} for SignalCardRouterV2.closeCard(...)."""
    from web3 import Web3

    sig = "closeCard(uint256,uint128,uint256,uint256,uint256)"
    raw = Web3.keccak(text=sig).hex()
    if raw.startswith("0x"):
        raw = raw[2:]
    selector = raw[:8]
    body = (
        _hex32(card_id)
        + _hex32(liquidity)
        + _hex32(amount0_min)
        + _hex32(amount1_min)
        + _hex32(deadline)
    )
    return {"to": router, "data": "0x" + selector + body}


def build_close_bundle(
    *,
    card_id: int,
    chain_id: int,
    router: str,
    liquidity: int = 10**24,
    amount0_min: int = 0,
    amount1_min: int = 0,
    deadline_seconds: int = 3600,
) -> CloseBundle:
    """Assemble the close call bundle — single tx, no approvals needed."""
    deadline = int(time.time()) + deadline_seconds
    calls = [
        encode_close_card(
            router,
            card_id=card_id,
            liquidity=liquidity,
            amount0_min=amount0_min,
            amount1_min=amount1_min,
            deadline=deadline,
        )
    ]
    return CloseBundle(
        card_id=card_id,
        chain_id=chain_id,
        router=router,
        calls=calls,
        deadline=deadline,
    )
