"""Signal performance report generator.

Reads all on-chain signals, computes ROI, win/loss, and simulates
a $10,000 portfolio investing $100 per trade.
"""
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

TRACKED_ASSETS = {
    "0x0000000000000000000000000000000000000001": "BTC",
    "0x0000000000000000000000000000000000000002": "ETH",
    "0x0000000000000000000000000000000000000003": "INIT",
}

REPORT_DIR = Path(__file__).parent.parent / "reports"
STARTING_BALANCE = 10_000.0
TRADE_SIZE = 100.0


def _pnl_pct(entry: int, exit_: int, is_bull: bool) -> float:
    if entry == 0:
        return 0.0
    pct = ((exit_ - entry) / entry) * 100
    return pct if is_bull else -pct


def generate_report(chain_client, metadata: dict | None = None) -> dict:
    metadata = metadata or {}
    total = chain_client.get_signal_count()
    signals = chain_client.get_signals(0, min(total, 1000)) if total > 0 else []

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

        asset_key = TRACKED_ASSETS.get(s["asset"].lower(), "OTHER")
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
        "simulation": {
            "startingBalance": STARTING_BALANCE,
            "tradeSize": TRADE_SIZE,
            "finalBalance": round(balance, 2),
            "totalReturn": round(balance - STARTING_BALANCE, 2),
            "totalReturnPct": round(((balance - STARTING_BALANCE) / STARTING_BALANCE) * 100, 2),
            "balanceHistory": balance_history,
        },
    }

    # Write to disk
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
