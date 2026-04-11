import logging
import os
import time
from collections import defaultdict
import httpx
from app.config import get_settings
from app.error_tracker import error_tracker

logger = logging.getLogger(__name__)

price_history: dict[str, list[tuple[float, float]]] = defaultdict(list)
signal_metadata: dict[int, dict] = {}
MAX_HISTORY = 100

# Dynamic asset registry: address → symbol
# Users can add custom pairs via API. Address is deterministic from symbol.
TRACKED_ASSETS: dict[str, str] = {
    "0x0000000000000000000000000000000000000001": "BTC/USD",
    "0x0000000000000000000000000000000000000002": "ETH/USD",
    "0x0000000000000000000000000000000000000003": "INIT/USD",
}

# CoinGecko ID mapping for price fetching. Extensible.
COINGECKO_IDS: dict[str, str] = {
    "BTC/USD": "bitcoin",
    "ETH/USD": "ethereum",
    "INIT/USD": "initia",
    "SOL/USD": "solana",
    "AVAX/USD": "avalanche-2",
    "DOGE/USD": "dogecoin",
    "LINK/USD": "chainlink",
    "MATIC/USD": "matic-network",
    "DOT/USD": "polkadot",
    "ATOM/USD": "cosmos",
    "TIA/USD": "celestia",
    "SEI/USD": "sei-network",
    "SUI/USD": "sui",
    "APT/USD": "aptos",
    "ARB/USD": "arbitrum",
    "OP/USD": "optimism",
    "INJ/USD": "injective-protocol",
}

ORACLE_PAIRS: dict[str, str] = {sym: sym for sym in COINGECKO_IDS}


def _symbol_to_address(symbol: str) -> str:
    """Deterministic address from symbol string (hash-based)."""
    import hashlib
    h = hashlib.sha256(symbol.encode()).hexdigest()[:40]
    return f"0x{h}"


def add_tracked_asset(symbol: str) -> str:
    """Register a new token pair. Returns its address."""
    symbol = symbol.upper()
    if not symbol.endswith("/USD"):
        symbol = f"{symbol}/USD"
    # Check if already tracked
    for addr, sym in TRACKED_ASSETS.items():
        if sym == symbol:
            return addr
    addr = _symbol_to_address(symbol)
    TRACKED_ASSETS[addr] = symbol
    ORACLE_PAIRS[symbol] = symbol
    logger.info(f"Added tracked asset: {symbol} → {addr}")
    return addr


def remove_tracked_asset(symbol: str) -> bool:
    """Remove a token pair from tracking."""
    symbol = symbol.upper()
    if not symbol.endswith("/USD"):
        symbol = f"{symbol}/USD"
    for addr, sym in list(TRACKED_ASSETS.items()):
        if sym == symbol:
            del TRACKED_ASSETS[addr]
            ORACLE_PAIRS.pop(symbol, None)
            price_history.pop(symbol, None)
            logger.info(f"Removed tracked asset: {symbol}")
            return True
    return False

# Timeframe → CoinGecko OHLC days param + display label
TIMEFRAMES = {
    "15m": {"days": "1", "label": "15m candles / 24h horizon"},
    "30m": {"days": "1", "label": "30m candles / 24h horizon"},
    "1h":  {"days": "7", "label": "1h candles / 7d horizon"},
    "4h":  {"days": "30", "label": "4h candles / 30d horizon"},
    "1d":  {"days": "90", "label": "1d candles / 90d horizon"},
}
DEFAULT_TIMEFRAME = "30m"
DEFAULT_TARGET_PCT = 0.015


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
    # Build ids list from tracked assets
    pairs_to_fetch = {sym: COINGECKO_IDS[sym] for sym in
                      set(TRACKED_ASSETS.values()) if sym in COINGECKO_IDS}
    if not pairs_to_fetch:
        return {}
    ids_str = ",".join(set(pairs_to_fetch.values()))
    try:
        resp = httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": ids_str, "vs_currencies": "usd"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        # Reverse lookup: coingecko_id → symbol
        id_to_sym = {cg_id: sym for sym, cg_id in pairs_to_fetch.items()}
        prices = {}
        for cg_id, vals in data.items():
            if cg_id in id_to_sym and "usd" in vals:
                prices[id_to_sym[cg_id]] = vals["usd"]
        if prices:
            logger.info(f"CoinGecko: {len(prices)} pairs")
        return prices
    except Exception as e:
        logger.warning(f"CoinGecko failed: {e}")
        return {}


def fetch_prices() -> dict[str, float]:
    prices = fetch_oracle_prices()
    if not prices:
        prices = fetch_coingecko_fallback()
    if not prices:
        error_tracker.track("PRICE_FETCH_FAILED", "Both Oracle and CoinGecko price feeds unavailable")
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


def _classify_pattern(crossover_bull: bool, crossover_bear: bool, is_bull: bool) -> str:
    if crossover_bull:
        return "Golden Cross"
    if crossover_bear:
        return "Death Cross"
    return "Bullish Momentum" if is_bull else "Bearish Momentum"


def _build_analysis(symbol: str, pattern: str, rsi_val: float, curr_diff: float, current_price: float, is_bull: bool, confidence: int, target_price: float, stop_loss: float, timeframe_label: str = "30m candles / 24h horizon") -> str:
    direction = "bullish" if is_bull else "bearish"
    action = "BUY" if is_bull else "SELL"
    ema_pct = abs(curr_diff / current_price) * 100 if current_price else 0

    # RSI interpretation
    if rsi_val > 70:
        rsi_reading = f"RSI(14) is elevated at {rsi_val:.0f}, suggesting strong upward pressure but caution for reversal"
    elif rsi_val > 60:
        rsi_reading = f"RSI(14) at {rsi_val:.0f} confirms {direction} momentum with room to run"
    elif rsi_val < 30:
        rsi_reading = f"RSI(14) is depressed at {rsi_val:.0f}, indicating oversold conditions"
    elif rsi_val < 40:
        rsi_reading = f"RSI(14) at {rsi_val:.0f} shows weakness, supporting bearish bias"
    else:
        rsi_reading = f"RSI(14) at {rsi_val:.0f} in neutral zone, direction driven by EMA crossover"

    # Pattern-specific reasoning
    if pattern == "Golden Cross":
        trigger = f"EMA(5) crossed above EMA(10) by {ema_pct:.3f}%, triggering a {pattern} — a classic {direction} reversal signal"
    elif pattern == "Death Cross":
        trigger = f"EMA(5) crossed below EMA(10) by {ema_pct:.3f}%, triggering a {pattern} — a classic {direction} reversal signal"
    else:
        trigger = f"EMA(5) {'above' if is_bull else 'below'} EMA(10) by {ema_pct:.3f}%, showing sustained {direction} momentum"

    return (
        f"{action} {symbol} | {trigger}. "
        f"{rsi_reading}. "
        f"Chart: {timeframe_label}. "
        f"Entry ${current_price:,.2f} → Target ${target_price:,.2f} / Stop ${stop_loss:,.2f} (1:1 R:R). "
        f"Confidence {confidence}% based on EMA divergence strength + RSI distance from equilibrium. "
        f"Auto-resolves in 24h with market price."
    )


def generate_signals(prices: dict[str, float], assets: list[str] | None = None,
                     target_pct: float = DEFAULT_TARGET_PCT, timeframe: str = DEFAULT_TIMEFRAME) -> list[dict]:
    """
    Signal generation using EMA crossover + RSI confirmation.
    Optional filters: assets, target_pct (P/L %), timeframe.
    """
    tf_label = TIMEFRAMES.get(timeframe, TIMEFRAMES[DEFAULT_TIMEFRAME])["label"]
    signals = []
    for asset_addr, symbol in TRACKED_ASSETS.items():
        if assets and symbol not in assets:
            continue

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
            trend_pct = curr_diff / current_price if current_price else 0
            if abs(trend_pct) < 0.001:
                continue
            crossover_bull = trend_pct > 0.001
            crossover_bear = trend_pct < -0.001

        is_bull = crossover_bull
        rsi_val = rsi(closes) or 50

        if is_bull and rsi_val > 75:
            continue
        if not is_bull and rsi_val < 25:
            continue

        ema_strength = min(abs(curr_diff / current_price) * 2000, 40) if current_price else 0
        rsi_score = abs(rsi_val - 50) / 50 * 30
        confidence = int(min(95, max(50, 25 + ema_strength + rsi_score)))

        # target_pct from user input (default 1.5%)
        target_price = current_price * (1 + target_pct) if is_bull else current_price * (1 - target_pct)
        stop_loss = current_price * (1 - target_pct) if is_bull else current_price * (1 + target_pct)

        entry_wei = int(current_price * 1e18)
        target_wei = int(target_price * 1e18)

        pattern = _classify_pattern(crossover_bull, crossover_bear, is_bull)
        analysis = _build_analysis(symbol, pattern, rsi_val, curr_diff, current_price, is_bull, confidence, target_price, stop_loss, tf_label)

        signals.append({
            "asset": asset_addr,
            "isBull": is_bull,
            "confidence": confidence,
            "targetPrice": target_wei,
            "entryPrice": entry_wei,
            "symbol": symbol,
            "currentPrice": current_price,
            "pattern": pattern,
            "analysis": analysis,
            "timeframe": tf_label,
            "stopLoss": int(stop_loss * 1e18),
        })
        direction = "BULL" if is_bull else "BEAR"
        logger.info(
            f"Signal: {symbol} {direction} [{pattern}] conf={confidence}% "
            f"RSI={rsi_val:.0f} EMA={curr_diff:+.2f} price=${current_price:,.2f} "
            f"target=${target_price:,.2f}"
        )

    return signals


# --- TX tracking ---

recent_signal_txs: list[dict] = []
MAX_RECENT_TXS = 100

# In-memory signal store for simulation mode (no chain)
sim_signals: list[dict] = []


def submit_signals(signals: list[dict]) -> list[str]:
    from app.config import get_settings
    errors = []
    settings = get_settings()

    # Simulation mode: store in memory when no chain
    if not settings.contract_address:
        for s in signals:
            signal_id = len(sim_signals)
            tx_hash = f"0x{os.urandom(32).hex()}"
            sim_signals.append({
                "id": signal_id,
                "asset": s["asset"],
                "isBull": s["isBull"],
                "confidence": s["confidence"],
                "targetPrice": str(s["targetPrice"]),
                "entryPrice": str(s["entryPrice"]),
                "exitPrice": "0",
                "timestamp": int(time.time()),
                "resolved": False,
                "creator": "0x0000000000000000000000000000000000000000",
                "symbol": s.get("symbol", ""),
                "pattern": s.get("pattern", ""),
                "analysis": s.get("analysis", ""),
                "timeframe": s.get("timeframe", ""),
                "stopLoss": str(s.get("stopLoss", 0)),
            })
            signal_metadata[signal_id] = {
                "pattern": s.get("pattern", ""),
                "analysis": s.get("analysis", ""),
                "timeframe": s.get("timeframe", ""),
                "stopLoss": str(s.get("stopLoss", 0)),
            }
            recent_signal_txs.append({
                "signalId": signal_id, "txHash": tx_hash,
                "symbol": s["symbol"], "isBull": s["isBull"],
                "confidence": s["confidence"],
                "price": s["currentPrice"],
                "timestamp": time.time(),
            })
            if len(recent_signal_txs) > MAX_RECENT_TXS:
                recent_signal_txs.pop(0)
            logger.info(f"Sim: {s['symbol']} #{signal_id} tx={tx_hash[:16]}...")
        return errors

    from app.main import get_chain
    try:
        chain = get_chain()
        for s in signals:
            try:
                signal_id, tx_hash = chain.create_signal(
                    s["asset"], s["isBull"], s["confidence"],
                    s["targetPrice"], s["entryPrice"],
                )
                signal_metadata[signal_id] = {
                    "pattern": s.get("pattern", ""),
                    "analysis": s.get("analysis", ""),
                    "timeframe": s.get("timeframe", "30m candles / 24h horizon"),
                    "stopLoss": str(s.get("stopLoss", 0)),
                }
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
                msg = f"Submit {s['symbol']} failed: {e}"
                logger.error(msg)
                error_tracker.track("SIGNAL_SUBMIT_FAILED", msg, {"symbol": s["symbol"]})
                errors.append(msg)
    except Exception as e:
        msg = f"Chain client unavailable: {e}"
        logger.error(msg)
        error_tracker.track("CHAIN_CLIENT_ERROR", msg)
        errors.append(msg)
    return errors


def auto_resolve_old_signals() -> list[str]:
    settings = get_settings()
    errors = []
    timeout = settings.signal_resolve_timeout_hours * 3600
    now = time.time()

    # Simulation mode
    if not settings.contract_address:
        prices = fetch_prices()
        for s in sim_signals:
            if s["resolved"] or now - s["timestamp"] < timeout:
                continue
            symbol = s.get("symbol", TRACKED_ASSETS.get(s["asset"].lower(), ""))
            current = prices.get(ORACLE_PAIRS.get(symbol, symbol))
            if current is None:
                continue
            s["exitPrice"] = str(int(current * 1e18))
            s["resolved"] = True
            logger.info(f"Sim resolved #{s['id']} at ${current:,.2f}")
        return errors

    from app.main import get_chain
    settings = get_settings()
    errors = []
    try:
        chain = get_chain()
        count = chain.get_signal_count()
        prices = fetch_prices()
        now = time.time()
        timeout = settings.signal_resolve_timeout_hours * 3600

        for i in range(count):
            try:
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
                msg = f"Resolve signal #{i} failed: {e}"
                logger.error(msg)
                error_tracker.track("SIGNAL_RESOLVE_FAILED", msg, {"signal_id": i})
                errors.append(msg)
    except Exception as e:
        msg = f"Auto-resolve failed: {e}"
        logger.error(msg)
        error_tracker.track("AUTO_RESOLVE_ERROR", msg)
        errors.append(msg)
    return errors


def bootstrap_price_history(timeframe: str = DEFAULT_TIMEFRAME):
    """Fetch real prices to bootstrap history. No fake data."""
    days = TIMEFRAMES.get(timeframe, TIMEFRAMES[DEFAULT_TIMEFRAME])["days"]
    logger.info(f"Bootstrapping price history from CoinGecko OHLC (days={days})...")
    try:
        pairs_to_fetch = [(COINGECKO_IDS[sym], sym) for sym in
                          set(TRACKED_ASSETS.values()) if sym in COINGECKO_IDS]
        for coin_id, pair in pairs_to_fetch:
            try:
                resp = httpx.get(
                    f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc",
                    params={"vs_currency": "usd", "days": days},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for candle in data[-20:]:
                        ts = candle[0] / 1000
                        close = candle[4]
                        price_history[pair].append((ts, close))
                    logger.info(f"  {pair}: {len(data[-20:])} real candles loaded, latest=${data[-1][4]:,.2f}")
                else:
                    msg = f"OHLC {coin_id}: HTTP {resp.status_code}"
                    logger.warning(msg)
                    error_tracker.track("OHLC_FETCH_FAILED", msg, {"coin": coin_id, "status": resp.status_code})
                time.sleep(3)
            except Exception as e:
                msg = f"OHLC {coin_id} failed: {e}"
                logger.warning(msg)
                error_tracker.track("OHLC_FETCH_FAILED", msg, {"coin": coin_id})
    except Exception as e:
        msg = f"OHLC bootstrap failed: {e}"
        logger.warning(msg)
        error_tracker.track("BOOTSTRAP_FAILED", msg)
        prices = fetch_prices()
        if prices:
            update_price_history(prices)


def run_signal_cycle(assets: list[str] | None = None, target_pct: float = DEFAULT_TARGET_PCT,
                    timeframe: str = DEFAULT_TIMEFRAME) -> dict:
    logger.info(f"Running signal cycle...{f' assets={assets}' if assets else ''} tf={timeframe} target={target_pct}")
    result = {"success": False, "signals_created": 0, "errors": []}
    try:
        prices = fetch_prices()
        if not prices:
            result["errors"].append("No prices available from Oracle or CoinGecko")
            logger.warning("No prices available, skipping cycle")
            return result

        update_price_history(prices)
        signals = generate_signals(prices, assets, target_pct, timeframe)
        if signals:
            submit_errors = submit_signals(signals)
            result["signals_created"] = len(signals) - len(submit_errors)
            result["errors"].extend(submit_errors)
        resolve_errors = auto_resolve_old_signals()
        result["errors"].extend(resolve_errors)
        result["success"] = len(result["errors"]) == 0
        logger.info(f"Cycle complete: {result['signals_created']} signals from {len(prices)} prices")
    except Exception as e:
        msg = f"Signal cycle crashed: {e}"
        logger.error(msg)
        error_tracker.track("SIGNAL_CYCLE_CRASH", msg)
        result["errors"].append(msg)
    return result


def get_current_prices() -> dict[str, float]:
    prices = fetch_prices()
    if prices:
        update_price_history(prices)
    return prices


def get_price_history_for_asset(symbol: str) -> list[dict]:
    oracle_key = ORACLE_PAIRS.get(symbol, symbol)
    history = price_history.get(oracle_key, [])
    return [{"timestamp": h[0], "price": h[1]} for h in history]
