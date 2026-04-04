import logging
import time
from collections import defaultdict
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

# Rolling price history: asset -> list of (timestamp, price)
price_history: dict[str, list[tuple[float, float]]] = defaultdict(list)
MAX_HISTORY = 50

# Known assets to track (address -> symbol)
TRACKED_ASSETS = {
    "0x0000000000000000000000000000000000000001": "BTC/USD",
    "0x0000000000000000000000000000000000000002": "ETH/USD",
    "0x0000000000000000000000000000000000000003": "INIT/USD",
}

# Oracle currency pair mapping
ORACLE_PAIRS = {
    "BTC/USD": "BTC/USD",
    "ETH/USD": "ETH/USD",
    "INIT/USD": "INIT/USD",
}


def fetch_oracle_prices() -> dict[str, float]:
    """Fetch prices from Initia Slinky oracle."""
    settings = get_settings()
    url = f"{settings.lcd_url}/slinky/oracle/v1/prices"
    prices = {}
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("prices", []):
            pair = item.get("currency_pair", {})
            key = f"{pair.get('Base', '')}/{pair.get('Quote', '')}"
            price_str = item.get("price", {}).get("price", "0")
            if price_str and price_str != "0":
                # Oracle prices are in 8-decimal format
                prices[key] = int(price_str) / 1e8
        logger.info(f"Oracle prices fetched: {len(prices)} pairs")
    except Exception as e:
        logger.warning(f"Oracle fetch failed: {e}")
    return prices


def fetch_coingecko_fallback() -> dict[str, float]:
    """Fallback: fetch from CoinGecko public API."""
    try:
        resp = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "bitcoin,ethereum,initia", "vs_currencies": "usd"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        prices = {}
        if "bitcoin" in data:
            prices["BTC/USD"] = data["bitcoin"]["usd"]
        if "ethereum" in data:
            prices["ETH/USD"] = data["ethereum"]["usd"]
        if "initia" in data:
            prices["INIT/USD"] = data["initia"]["usd"]
        logger.info(f"CoinGecko fallback prices: {prices}")
        return prices
    except Exception as e:
        logger.warning(f"CoinGecko fallback failed: {e}")
        return {}


def fetch_prices() -> dict[str, float]:
    """Fetch prices from oracle, fall back to CoinGecko."""
    prices = fetch_oracle_prices()
    if not prices:
        prices = fetch_coingecko_fallback()
    return prices


def update_price_history(prices: dict[str, float]):
    """Append new prices to rolling history."""
    now = time.time()
    for pair, price in prices.items():
        history = price_history[pair]
        history.append((now, price))
        if len(history) > MAX_HISTORY:
            price_history[pair] = history[-MAX_HISTORY:]


def generate_signals(prices: dict[str, float]) -> list[dict]:
    """
    Momentum algorithm:
    - Bullish if last 3 prices ascending with >2% move
    - Bearish if last 3 prices descending with >2% move
    - Confidence = clamp(abs(pct_change) * 1000, 50, 95)
    """
    signals = []
    for asset_addr, symbol in TRACKED_ASSETS.items():
        oracle_key = ORACLE_PAIRS.get(symbol, symbol)
        history = price_history.get(oracle_key, [])
        current_price = prices.get(oracle_key)

        if current_price is None or len(history) < 3:
            continue

        recent = [h[1] for h in history[-3:]]
        delta_pct = (recent[-1] - recent[0]) / recent[0] if recent[0] != 0 else 0

        if abs(delta_pct) < 0.02:
            continue  # Not enough movement

        is_bull = delta_pct > 0
        ascending = all(recent[i] <= recent[i + 1] for i in range(len(recent) - 1))
        descending = all(recent[i] >= recent[i + 1] for i in range(len(recent) - 1))

        if (is_bull and not ascending) or (not is_bull and not descending):
            continue  # Not a clean trend

        confidence = int(min(95, max(50, abs(delta_pct) * 1000)))
        target_mult = 1.05 if is_bull else 0.95
        target_price = current_price * target_mult

        # Convert to 18-decimal wei format
        entry_wei = int(current_price * 1e18)
        target_wei = int(target_price * 1e18)

        signals.append({
            "asset": asset_addr,
            "isBull": is_bull,
            "confidence": confidence,
            "targetPrice": target_wei,
            "entryPrice": entry_wei,
            "symbol": symbol,
            "currentPrice": current_price,
        })
        logger.info(f"Signal generated: {symbol} {'BULL' if is_bull else 'BEAR'} conf={confidence} price={current_price}")

    return signals


# Recent AI signal tx hashes for explorer tracking
recent_signal_txs: list[dict] = []
MAX_RECENT_TXS = 100


def submit_signals(signals: list[dict]):
    """Submit generated signals on-chain."""
    from app.main import get_chain
    try:
        chain = get_chain()
        for s in signals:
            signal_id, tx_hash = chain.create_signal(
                s["asset"], s["isBull"], s["confidence"],
                s["targetPrice"], s["entryPrice"],
            )
            recent_signal_txs.append({
                "signalId": signal_id, "txHash": tx_hash,
                "symbol": s["symbol"], "isBull": s["isBull"],
                "timestamp": time.time(),
            })
            if len(recent_signal_txs) > MAX_RECENT_TXS:
                recent_signal_txs.pop(0)
            logger.info(f"Signal submitted on-chain: {s['symbol']} tx={tx_hash}")
    except Exception as e:
        logger.error(f"Failed to submit signals: {e}")


def auto_resolve_old_signals():
    """Resolve signals older than the configured timeout."""
    from app.main import get_chain
    settings = get_settings()
    try:
        chain = get_chain()
        count = chain.get_signal_count()
        prices = fetch_prices()
        now = time.time()
        timeout = settings.signal_resolve_timeout_hours * 3600

        for i in range(count):
            signal = chain.get_signal(i)
            if signal["resolved"]:
                continue
            age = now - signal["timestamp"]
            if age < timeout:
                continue

            # Find current price for this asset
            symbol = TRACKED_ASSETS.get(signal["asset"].lower(), "")
            oracle_key = ORACLE_PAIRS.get(symbol, symbol)
            current = prices.get(oracle_key)
            if current is None:
                continue

            exit_wei = int(current * 1e18)
            resolve_tx = chain.resolve_signal(i, exit_wei)
            recent_signal_txs.append({
                "signalId": i, "txHash": resolve_tx,
                "symbol": symbol, "action": "resolve",
                "timestamp": time.time(),
            })
            if len(recent_signal_txs) > MAX_RECENT_TXS:
                recent_signal_txs.pop(0)
            logger.info(f"Auto-resolved signal #{i} at price {current} tx={resolve_tx}")
    except Exception as e:
        logger.error(f"Auto-resolve failed: {e}")


def run_signal_cycle():
    """Full signal generation cycle: fetch → analyze → submit → resolve old."""
    logger.info("Running signal cycle...")
    prices = fetch_prices()
    if not prices:
        logger.warning("No prices available, skipping cycle")
        return

    update_price_history(prices)
    signals = generate_signals(prices)
    if signals:
        submit_signals(signals)
    auto_resolve_old_signals()
    logger.info(f"Signal cycle complete: {len(signals)} new signals")


def get_current_prices() -> dict[str, float]:
    """Return latest known prices (from history or fresh fetch)."""
    prices = fetch_prices()
    if prices:
        update_price_history(prices)
    return prices


def get_price_history_for_asset(symbol: str) -> list[dict]:
    """Return price history for a specific asset."""
    oracle_key = ORACLE_PAIRS.get(symbol, symbol)
    history = price_history.get(oracle_key, [])
    return [{"timestamp": h[0], "price": h[1]} for h in history]
