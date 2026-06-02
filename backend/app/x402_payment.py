from x402.http import HTTPFacilitatorClient, FacilitatorConfig, CreateHeadersAuthProvider
from x402.http.types import PaymentOption, RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer
from x402.extensions.bazaar import bazaar_resource_server_extension, declare_discovery_extension, OutputConfig

from app.config import get_settings


def _build_cdp_auth_provider():
    """Build CDP JWT auth provider for facilitator requests."""
    settings = get_settings()
    if not settings.cdp_api_key_id or not settings.cdp_api_key_secret:
        return None

    from cdp.auth.utils.jwt import generate_jwt, JwtOptions

    def create_headers():
        host = "api.cdp.coinbase.com"
        base = {"api_key_id": settings.cdp_api_key_id, "api_key_secret": settings.cdp_api_key_secret}

        def bearer(method, path):
            token = generate_jwt(JwtOptions(**base, request_method=method, request_host=host, request_path=path, expires_in=120))
            return {"Authorization": f"Bearer {token}"}

        return {
            "verify": bearer("POST", "/platform/v2/x402/verify"),
            "settle": bearer("POST", "/platform/v2/x402/settle"),
            "supported": bearer("GET", "/platform/v2/x402/supported"),
        }

    return CreateHeadersAuthProvider(create_headers)


def get_x402_middleware_args() -> tuple[dict, x402ResourceServer] | tuple[None, None]:
    settings = get_settings()

    if not settings.x402_receiver_address:
        return (None, None)

    try:
        import signal as _sig

        class _Timeout(Exception):
            pass

        def _handler(signum, frame):
            raise _Timeout()

        old = _sig.signal(_sig.SIGALRM, _handler)
        _sig.alarm(10)  # 10s timeout for facilitator connection
        try:
            facilitator = HTTPFacilitatorClient(FacilitatorConfig(
                url=settings.x402_facilitator_url,
                auth_provider=_build_cdp_auth_provider(),
            ))
        finally:
            _sig.alarm(0)
            _sig.signal(_sig.SIGALRM, old)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"x402 facilitator init failed (skipping): {e}")
        return (None, None)

    server = x402ResourceServer(facilitator)
    server.register(settings.x402_network, ExactEvmServerScheme())
    server.register_extension(bazaar_resource_server_extension)

    pay_to = settings.x402_receiver_address
    network = settings.x402_network

    def route(price: str, description: str, output_example: dict) -> RouteConfig:
        return RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=pay_to, price=price, network=network)],
            mime_type="application/json",
            description=description,
            extensions=declare_discovery_extension(
                input={"limit": "10"},
                output=OutputConfig(example=output_example),
            ),
        )

    routes = {
        "GET /api/v2/agent/decisions": route(
            "$0.001",
            "AI crypto trading signals with on-chain verifiable 60.8% accuracy across 5,816+ resolved predictions. Multi-agent technical+sentiment+fundamentals analysis returns APE/FADE/HOLD verdicts with confidence score, entry, target, stop, reasoning, and per-token track record.",
            {"decisions": [{"token": "BTC", "action": "APE", "confidence": 85, "entry": 104250.5, "target": 105814.3, "stop": 102686.7, "reasoning": "Bullish EMA crossover + RSI momentum", "track_record": {"win_rate": 68.5, "sample_size": 42}}], "total": 1},
        ),
        "GET /api/v2/agent/prices": route(
            "$0.001",
            "Real-time aggregated cryptocurrency spot prices from CoinGecko + DexScreener with source attribution and confidence scoring. Pass comma-separated symbols (e.g. BTC,ETH,SOL).",
            {"prices": [{"symbol": "BTC", "price": 104250.5, "source": "coingecko"}]},
        ),
        "GET /api/v2/agent/pools": route(
            "$0.005",
            "DeFi LP pool advisory ranked by APY and TVL with impermanent-loss risk scoring across multiple chains and protocols. Returns curated APE/FADE recommendations for liquidity provision opportunities.",
            {"pools": [{"pair": "ETH/USDC", "apy": 12.5, "tvl": 5000000, "risk_score": 35}], "total": 1},
        ),
        "GET /api/v2/agent/lp-recipes": route(
            "$0.005",
            "Concentrated-LP recipe for any pool card with volatility-based price range, tick math, Token-A→Token-B derivation, pool-share, and 24h fee projection. Three presets (Conservative/Balanced/Aggressive) map to k·σ_7d bands. Returns ZAP-ready X Layer V4 ticks for supported pairs and a deep-link for everything else.",
            {"preset": "balanced", "sigma_7d": 0.042, "min_price": 1850.0, "max_price": 2100.0, "ticks": [-720, 720], "amount_a": 1.0, "token_b_amount": 1924.5, "pool_share_pct": 0.0001, "est_fee_24h_usd": 0.045, "supported": True, "dex_link": "https://defillama.com/yields/pool/abc"},
        ),
        "GET /api/v2/agent/track-record": route(
            "$0.01",
            "Historical prediction accuracy and per-token win rates from 5,816+ on-chain resolved predictions. Includes overall accuracy, per-token breakdown, sample size, and average PnL.",
            {"overall": {"total": 5816, "wins": 3534, "win_rate": 60.8}, "per_token": {"BTC": {"total": 42, "wins": 29, "win_rate": 69.0, "avg_pnl": 1.42}}},
        ),
        "GET /api/v2/agent/context": route(
            "$0.01",
            "Macro market context fused from SoSoValue institutional data: BTC/ETH ETF net flows, macro economic event calendar, sector rotation signals, breaking news, plus the AI oracle's current market mood. Refreshed every 30 seconds.",
            {"sosovalue": {"etf_flows": {"btc_net_flow_24h": 150000000}, "macro_events": [], "hot_news": []}, "oracle_mood": "bullish"},
        ),
        "GET /api/v2/agent/macro-deck": route(
            "$0.02",
            "Daily Macro Trading Desk cards: ETF flow signals, macro event catalysts, and momentum streak alerts. Institutional-grade research distilled into actionable APE/FADE predictions with conviction scoring.",
            {"cards": [{"token_symbol": "BTC", "card_type": "macro_desk", "hook": "$186M ETF inflow today", "verdict": "APE"}], "total": 3},
        ),
        "GET /api/v2/agent/whale-alerts": route(
            "$0.005",
            "Real-time BTC treasury whale alerts: detects when MicroStrategy, Tesla, and other public companies change their Bitcoin holdings. Event-driven signals with directional bias.",
            {"alerts": [{"token_symbol": "BTC", "hook": "MicroStrategy bought 5,000 BTC", "verdict": "APE"}], "total": 1},
        ),
        "GET /api/v2/agent/index-battles": route(
            "$0.01",
            "Weekly sector index battle matchups from SoSoValue SSI protocol: MAG7 vs Meme, DeFi vs AI, L1 vs L2. Sector rotation intelligence for portfolio allocation decisions.",
            {"battles": [{"token_symbol": "MAG7vMEME", "card_type": "index_battle", "hook": "MAG7 vs Meme — which wins?", "verdict": "APE"}], "total": 2},
        ),
    }

    return (routes, server)


def build_x402_info(price_usd: str) -> dict:
    settings = get_settings()
    return {
        "x402": True,
        "price": price_usd,
        "network": settings.x402_network,
        "pay_to": settings.x402_receiver_address,
        "facilitator": settings.x402_facilitator_url,
    }
