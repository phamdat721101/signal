"""LP Advisory Engine — generates position recommendations from DeFiLlama pools."""
import logging
from app.content_engine import _fetch_llama_pools
from app import db

logger = logging.getLogger(__name__)


def _compute_action(pool: dict) -> tuple[str, int, str]:
    """Determine ENTER/EXIT/HOLD with confidence and reasoning."""
    apy = pool.get("apy", 0)
    il = abs(pool.get("il7d") or 0)
    apy_base = pool.get("apyBase") or 0
    fee_apr = apy_base

    if apy > 15 and il < 1:
        confidence = min(85, 50 + int(apy / 2))
        return "ENTER", confidence, f"High APY ({apy:.1f}%) with minimal IL ({il:.2f}%). Fee income dominates."
    if il > fee_apr and il > 2:
        confidence = min(80, 40 + int(il * 5))
        return "EXIT", confidence, f"IL ({il:.2f}%) exceeds fee income ({fee_apr:.1f}%). Position losing value."
    confidence = max(30, 50 - int(il * 10))
    return "HOLD", confidence, f"Moderate APY ({apy:.1f}%) with manageable IL ({il:.2f}%). Monitor closely."


def _pool_to_advisory(pool: dict) -> dict:
    """Transform a DeFiLlama pool into an advisory dict."""
    action, confidence, reasoning = _compute_action(pool)
    return {
        "pool_id": pool.get("pool", ""),
        "dex": pool.get("project", "unknown"),
        "chain": pool.get("chain", "unknown"),
        "token_pair": pool.get("symbol", "???"),
        "action": action,
        "confidence": confidence,
        "expected_apr": round(pool.get("apy", 0), 2),
        "il_risk_score": min(100, int(abs(pool.get("il7d") or 0) * 20)),
        "reasoning": reasoning,
    }


def generate_lp_advisories(limit: int = 5) -> list[dict]:
    """Produce LP advisory decisions and store as pool cards."""
    try:
        pools = _fetch_llama_pools()
        if not pools:
            return []
        advisories = [_pool_to_advisory(p) for p in pools[:limit]]
        for adv in advisories:
            db.insert_card({
                "token_symbol": adv["token_pair"],
                "token_name": f"{adv['dex']} LP",
                "chain": adv["chain"],
                "hook": f"{adv['action']}: {adv['reasoning'][:80]}",
                "roast": "",
                "verdict": adv["action"],
                "verdict_reason": adv["reasoning"],
                "risk_score": adv["il_risk_score"],
                "price": adv["expected_apr"],
                "card_type": "pool",
                "source": "lp_advisory",
            })
        logger.info(f"Generated {len(advisories)} LP advisories")
        return advisories
    except Exception as e:
        logger.error(f"LP advisory generation failed: {e}")
        return []
