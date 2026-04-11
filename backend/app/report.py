"""Signal performance report generator.

Reads on-chain signals, computes ROI, win/loss, and simulates
a $10,000 portfolio investing $100 per trade.
Supports filtering by creator address (user's executed signals only).
"""
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

from app.signal_engine import TRACKED_ASSETS as _TRACKED

REPORT_DIR = Path(__file__).parent.parent / "reports"
STARTING_BALANCE = 10_000.0
TRADE_SIZE = 100.0


def _pnl_pct(entry: int, exit_: int, is_bull: bool) -> float:
    if entry == 0:
        return 0.0
    pct = ((exit_ - entry) / entry) * 100
    return pct if is_bull else -pct


def _fetch_signals(chain_client, creator: str | None = None) -> list[dict]:
    """Fetch signals — all or filtered by creator address."""
    if creator:
        signal_ids = chain_client.get_user_signals(creator)
        return [chain_client.get_signal(sid) for sid in signal_ids]
    total = chain_client.get_signal_count()
    return chain_client.get_signals(0, min(total, 1000)) if total > 0 else []


def generate_report(chain_client, metadata: dict | None = None, creator: str | None = None) -> dict:
    metadata = metadata or {}
    signals = _fetch_signals(chain_client, creator)
    total = len(signals)

    resolved = [s for s in signals if s["resolved"]]
    wins, losses = [], []
    per_asset: dict[str, dict] = {}
    balance = STARTING_BALANCE
    balance_history = [{"trade": 0, "balance": balance}]

    for s in resolved:
        entry = int(s["entryPrice"])
        exit_ = int(s["exitPrice"])
        pct = _pnl_pct(entry, exit_, s["isBull"])
        profit = TRADE_SIZE * (pct / 100)
        balance += profit
        balance_history.append({"trade": len(balance_history), "balance": round(balance, 2)})

        (wins if pct > 0 else losses).append({"id": s["id"], "pct": round(pct, 4)})

        asset_key = _TRACKED.get(s["asset"].lower(), "OTHER").replace("/USD", "")
        if asset_key not in per_asset:
            per_asset[asset_key] = {"total": 0, "wins": 0, "losses": 0, "totalPnl": 0.0}
        pa = per_asset[asset_key]
        pa["total"] += 1
        pa["wins" if pct > 0 else "losses"] += 1
        pa["totalPnl"] = round(pa["totalPnl"] + pct, 4)

    for pa in per_asset.values():
        pa["winRate"] = round((pa["wins"] / pa["total"]) * 100, 1) if pa["total"] > 0 else 0

    all_pcts = [w["pct"] for w in wins] + [l["pct"] for l in losses]
    best = max(all_pcts) if all_pcts else 0
    worst = min(all_pcts) if all_pcts else 0
    avg_roi = round(sum(all_pcts) / len(all_pcts), 4) if all_pcts else 0
    win_rate = round((len(wins) / len(resolved)) * 100, 1) if resolved else 0

    report = {
        "generatedAt": time.time(),
        "totalSignals": total,
        "resolvedSignals": len(resolved),
        "activeSignals": total - len(resolved),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": win_rate,
        "averageRoi": avg_roi,
        "bestTrade": best,
        "worstTrade": worst,
        "perAsset": per_asset,
        "creator": creator,
        "simulation": {
            "startingBalance": STARTING_BALANCE,
            "tradeSize": TRADE_SIZE,
            "finalBalance": round(balance, 2),
            "totalReturn": round(balance - STARTING_BALANCE, 2),
            "totalReturnPct": round(((balance - STARTING_BALANCE) / STARTING_BALANCE) * 100, 2),
            "balanceHistory": balance_history,
        },
    }

    # Write to disk only for global reports
    if not creator:
        REPORT_DIR.mkdir(exist_ok=True)
        report_path = REPORT_DIR / "report.json"
        report_path.write_text(json.dumps(report, indent=2))
        logger.info(f"Report written to {report_path}")

    return report


if __name__ == "__main__":
    from app.chain import ChainClient
    from app.signal_engine import signal_metadata
    r = generate_report(ChainClient(), signal_metadata)
    print(json.dumps(r, indent=2))
