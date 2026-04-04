import logging
import time
from collections import defaultdict
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

price_history: dict[str, list[tuple[float, float]]] = defaultdict(list)
MAX_HISTORY = 100

TRACKED_ASSETS = {
    "0x0000000000000000000000000000000000000001": "BTC/USD",
    "0x0000000000000000000000000000000000000002": "ETH/USD",
    "0x0000000000000000000000000000000000000003": "INIT/USD",
}

ORACLE_PAIRS = {
    "BTC/USD": "BTC/USD",
    "ETH/USD": "ETH/USD",
    "INIT/USD": "INIT/USD",
}


def fetch_oracle_prices() -> dict[str, float]:
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
                prices[key] = int(price_str) / 1e8
        if prices:
            logger.info(f"Oracle: {len(prices)} pairs")
    except Exception as e:
        logger.warning(f"Oracle failed: {e}")
    return prices


def fetch_coingecko_fallback() -> dict[str, float]:
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
        if prices:
            logger.info(f"CoinGecko: {prices}")
        return prices
    except Exception as e:
        logger.warning(f"CoinGecko failed: {e}")
        return {}


def fetch_prices() -> dict[str, float]:
    prices = fetch_oracle_prices()
    if not prices:
        prices = fetch_coingecko_fallback()
    return prices


def update_price_history(prices: dict[str, float]):
    now = time.time()
    for pair, price in prices.items():
        history = price_history[pair]
        history.append((now, price))
        if len(history) > MAX_HISTORY:
            price_history[pair] = history[-MAX_HISTORY:]


# --- Technical Indicators ---

def ema(prices: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if len(prices) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(prices[:period]) / period]
    for p in prices[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result


def rsi(prices: list[float], period: int = 14) -> float | None:
    """Relative Strength Index (0-100)."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.0001
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def generate_signals(prices: dict[str, float]) -> list[dict]:
    """
    Signal generation using EMA crossover + RSI confirmation:
    - EMA(5) vs EMA(10) crossover for direction
    - RSI for overbought/oversold confirmation
    - Target: entry ± 1.5% (realistic 24h target)
    - Stop-loss: entry ∓ 1.5% (1:1 risk/reward)
    """
    signals = []
    for asset_addr, symbol in TRACKED_ASSETS.items():
        oracle_key = ORACLE_PAIRS.get(symbol, symbol)
        history = price_history.get(oracle_key, [])
        current_price = prices.get(oracle_key)

        if current_price is None or len(history) < 12:
            continue

        closes = [h[1] for h in history]
        ema_fast = ema(closes, 5)
        ema_slow = ema(closes, 10)

        if len(ema_fast) < 2 or len(ema_slow) < 2:
            continue

        # EMA crossover: fast crosses above slow = bullish
        prev_diff = ema_fast[-2] - ema_slow[-2]
        curr_diff = ema_fast[-1] - ema_slow[-1]
        crossover_bull = prev_diff <= 0 and curr_diff > 0
        crossover_bear = prev_diff >= 0 and curr_diff < 0

        if not crossover_bull and not crossover_bear:
            # No crossover — check trend strength instead
            trend_pct = curr_diff / current_price if current_price else 0
            if abs(trend_pct) < 0.001:
                continue  # No meaningful trend
            crossover_bull = trend_pct > 0.001
            crossover_bear = trend_pct < -0.001

        is_bull = crossover_bull
        rsi_val = rsi(closes) or 50

        # RSI confirmation: don't buy overbought, don't sell oversold
        if is_bull and rsi_val > 75:
            continue
        if not is_bull and rsi_val < 25:
            continue

        # Confidence from RSI distance + EMA strength
        ema_strength = min(abs(curr_diff / current_price) * 2000, 40) if current_price else 0
        rsi_score = abs(rsi_val - 50) / 50 * 30  # 0-30 from RSI
        confidence = int(min(95, max(50, 25 + ema_strength + rsi_score)))

        # Realistic target: ±1.5% (achievable in 24h)
        target_pct = 0.015
        target_price = current_price * (1 + target_pct) if is_bull else current_price * (1 - target_pct)

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
        direction = "BULL" if is_bull else "BEAR"
        logger.info(
            f"Signal: {symbol} {direction} conf={confidence}% "
            f"RSI={rsi_val:.0f} EMA={curr_diff:+.2f} price=${current_price:,.2f} "
            f"target=${target_price:,.2f}"
        )

    return signals


# --- TX tracking ---

recent_signal_txs: list[dict] = []
MAX_RECENT_TXS = 100


def submit_signals(signals: list[dict]):
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
                "confidence": s["confidence"],
                "price": s["currentPrice"],
                "timestamp": time.time(),
            })
            if len(recent_signal_txs) > MAX_RECENT_TXS:
                recent_signal_txs.pop(0)
            logger.info(f"On-chain: {s['symbol']} #{signal_id} tx={tx_hash}")
    except Exception as e:
        logger.error(f"Submit failed: {e}")


def auto_resolve_old_signals():
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
            if now - signal["timestamp"] < timeout:
                continue

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
            logger.info(f"Resolved #{i} at ${current:,.2f} tx={resolve_tx}")
    except Exception as e:
        logger.error(f"Auto-resolve failed: {e}")


def bootstrap_price_history():
    """Fetch real prices to bootstrap history. No fake data."""
    logger.info("Bootstrapping price history from CoinGecko OHLC...")
    try:
        # Fetch 1-day OHLC data (gives ~6 candles for last 24h)
        for coin_id, pair in [("bitcoin", "BTC/USD"), ("ethereum", "ETH/USD"), ("initia", "INIT/USD")]:
            resp = httpx.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc",
                params={"vs_currency": "usd", "days": "1"},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                # OHLC format: [timestamp_ms, open, high, low, close]
                for candle in data[-20:]:  # Last 20 candles
                    ts = candle[0] / 1000
                    close = candle[4]
                    price_history[pair].append((ts, close))
                logger.info(f"  {pair}: {len(data[-20:])} real candles loaded, latest=${data[-1][4]:,.2f}")
            time.sleep(3)
    except Exception as e:
        logger.warning(f"OHLC bootstrap failed: {e}, falling back to spot price")
        prices = fetch_prices()
        if prices:
            update_price_history(prices)


def run_signal_cycle():
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
    logger.info(f"Cycle complete: {len(signals)} signals from {len(prices)} prices")


def get_current_prices() -> dict[str, float]:
    prices = fetch_prices()
    if prices:
        update_price_history(prices)
    return prices


def get_price_history_for_asset(symbol: str) -> list[dict]:
    oracle_key = ORACLE_PAIRS.get(symbol, symbol)
    history = price_history.get(oracle_key, [])
    return [{"timestamp": h[0], "price": h[1]} for h in history]
