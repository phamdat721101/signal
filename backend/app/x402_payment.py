from x402.http import HTTPFacilitatorClient, FacilitatorConfig, CreateHeadersAuthProvider
from x402.http.types import PaymentOption, RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

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

    facilitator = HTTPFacilitatorClient(FacilitatorConfig(
        url=settings.x402_facilitator_url,
        auth_provider=_build_cdp_auth_provider(),
    ))
    server = x402ResourceServer(facilitator)
    server.register(settings.x402_network, ExactEvmServerScheme())

    pay_to = settings.x402_receiver_address
    network = settings.x402_network

    def route(price: str, description: str) -> RouteConfig:
        return RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=pay_to, price=price, network=network)],
            mime_type="application/json",
            description=description,
        )

    routes = {
        "GET /api/v2/agent/decisions": route("$0.001", "AI trading decisions with confidence scores and track record"),
        "GET /api/v2/agent/prices": route("$0.001", "Real-time aggregated crypto prices from multiple sources"),
        "GET /api/v2/agent/pools": route("$0.005", "LP pool advisory opportunities with yield analysis"),
        "GET /api/v2/agent/track-record": route("$0.01", "Historical prediction accuracy and win rates per token"),
        "GET /api/v2/agent/context": route("$0.01", "Market macro context including ETF flows and sentiment"),
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
