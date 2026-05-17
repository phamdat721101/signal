"""Agent API entrypoint — paid x402 surface, port 8002.

Single responsibility: serve the /api/v2/agent/* router behind x402 payment
gating, with Bazaar discovery extension declared. Reuses 100% of the data
layer (db_async, http_client, agent_api router) — nothing duplicated.

Runs as its own uvicorn process so an agent-side outage cannot break the
consumer Feed app on :8001.

Bazaar listing: automatic. The CDP Facilitator catalogs the resource on
first successful settle (no separate registration). See:
    https://docs.cdp.coinbase.com/x402/bazaar
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app import db_async, x402_settler
from app.agent_api import router as agent_router
from app.config import get_settings
from app.x402_payment import get_x402_middleware_args

# ─── Logging (mirror main.py — same format, request-id contextvar) ──────
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


_LOG_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
logging.basicConfig(level=get_settings().log_level, format=_LOG_FORMAT)
for h in logging.getLogger().handlers:
    h.addFilter(_RequestIdFilter())
logger = logging.getLogger("agent_main")


# ─── x402 setup (built once at startup) ─────────────────────────────────
# Resource server + per-route configs. Matches against (METHOD, path).
_x402_routes: dict[str, object] | None = None
_x402_server = None


def _build_resource_url(request: Request) -> str:
    """Public URL of the resource being paid for — required for Bazaar indexing."""
    base = (get_settings().x402_public_base_url or "").rstrip("/")
    if base:
        return f"{base}{request.url.path}"
    # Fall back to the request URL (works when behind a single reverse proxy)
    return str(request.url).split("?")[0]


async def _reconcile_loop():
    """Background task: reconcile stuck pending settlements every 60s."""
    while True:
        try:
            await asyncio.sleep(60)
            if _x402_server is not None:
                n = await x402_settler.reconcile_pending(_x402_server)
                if n:
                    logger.info("reconciled %d stuck settlements", n)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning("reconcile loop error: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _x402_routes, _x402_server
    logger.info("Starting Signal Agent API | network=%s", get_settings().network)
    await db_async.init_pool()
    _x402_routes, _x402_server = get_x402_middleware_args()
    if _x402_server is None:
        logger.warning("x402 not configured — endpoints will serve UNPAID")
    else:
        try:
            await asyncio.to_thread(_x402_server.initialize)
            logger.info("x402 server initialized; %d routes priced", len(_x402_routes or {}))
        except Exception as e:
            logger.error("x402 initialize failed: %s — endpoints will serve UNPAID", e)
            _x402_server = None
    reconciler = asyncio.create_task(_reconcile_loop())
    try:
        yield
    finally:
        reconciler.cancel()
        await db_async.close_pool()
        from app import http_client
        await http_client.close_async()
        http_client.close_sync()
        logger.info("Shutting down")


app = FastAPI(title="Signal Agent API (x402)", lifespan=lifespan)


@app.middleware("http")
async def request_id_and_log(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = _request_id_ctx.set(rid)
    start = time.monotonic()
    try:
        response = await call_next(request)
    finally:
        _request_id_ctx.reset(token)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    response.headers["x-request-id"] = rid
    if request.url.path != "/api/health":
        logger.info("%s %s -> %d (%dms)", request.method, request.url.path, response.status_code, elapsed_ms)
    return response


app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ─── x402 gating middleware ─────────────────────────────────────────────
# Pattern: missing/invalid x-payment header -> 402; valid -> proceed and
# settle async post-response. Settle outcome is persisted by x402_settler.

def _route_key(request: Request) -> str:
    return f"{request.method} {request.url.path}"


def _serialize_settle_resp(resp) -> str:
    """Encode SettleResponse for the x-payment-response header."""
    data = {
        "success": resp.success,
        "transaction": resp.transaction,
        "network": resp.network,
        "payer": resp.payer,
    }
    return base64.b64encode(json.dumps(data).encode()).decode()


@app.middleware("http")
async def x402_gate(request: Request, call_next):
    if _x402_server is None or not _x402_routes:
        return await call_next(request)  # disabled / fail-open

    route_cfg = _x402_routes.get(_route_key(request))
    if route_cfg is None:
        return await call_next(request)  # not a paid route

    from x402.schemas.payments import PaymentPayload  # local import — heavy SDK

    requirements = _x402_server.build_payment_requirements(
        route_cfg.accepts[0],
        extensions=list(route_cfg.extensions.keys()) if route_cfg.extensions else None,
    )

    x_payment = request.headers.get("x-payment")
    if not x_payment:
        # 402 challenge — Bazaar uses the resource URL to index this route
        challenge = _x402_server.create_payment_required_response(
            requirements,
            resource={"url": _build_resource_url(request), "type": "http"},
            extensions=route_cfg.extensions,
        )
        return JSONResponse(status_code=402, content=challenge.model_dump(mode="json", by_alias=True))

    # Decode + verify
    try:
        payload_dict = x402_settler.decode_payment_header(x_payment)
        payload = PaymentPayload.model_validate(payload_dict)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": "invalid_x_payment", "detail": str(e)[:200]})

    matched = _x402_server.find_matching_requirements(requirements, payload)
    if matched is None:
        return JSONResponse(status_code=402, content={"error": "payment_requirements_mismatch"})

    payload_hash = x402_settler.hash_payload(x_payment)
    try:
        verify_resp = await asyncio.to_thread(_x402_server.verify_payment, payload, matched)
    except Exception as e:
        logger.warning("verify exception: %s", e)
        return JSONResponse(status_code=502, content={"error": "facilitator_unavailable"})

    if not verify_resp.is_valid:
        return JSONResponse(status_code=402, content={
            "error": "payment_invalid",
            "reason": verify_resp.invalid_reason,
            "message": verify_resp.invalid_message,
        })

    # Persist intent before delivering data — survives crash mid-settle
    await x402_settler.record_pending(
        payload_hash,
        resource=_build_resource_url(request),
        network=matched.network,
        payer=verify_resp.payer,
        amount=matched.amount,
    )

    response = await call_next(request)

    # Settle in background — don't block the response
    asyncio.create_task(
        x402_settler.settle_async(_x402_server, payload, matched, payload_hash)
    )
    response.headers["x-request-id"] = response.headers.get("x-request-id", "-")
    return response


# ─── Mount the agent router (paid endpoints) ────────────────────────────
app.include_router(agent_router)


# ─── Public meta + health ───────────────────────────────────────────────
_SKILL_MD = """# Signal Trading Intelligence API (x402)

AI trading signals with on-chain verifiable accuracy. Paid via x402 / USDC.

## Endpoints
- GET /api/v2/agent/decisions  — $0.001 — APE/FADE verdicts with confidence + track record
- GET /api/v2/agent/prices     — $0.001 — Aggregated real-time prices
- GET /api/v2/agent/pools      — $0.005 — DeFi LP advisory with yield + IL risk
- GET /api/v2/agent/track-record — $0.01 — Historical accuracy per token
- GET /api/v2/agent/context    — $0.01 — Macro context (ETF flows, oracle mood)

## Discovery
Listed on CDP Bazaar. Search:
  GET https://api.cdp.coinbase.com/platform/v2/x402/discovery/search?query=trading+signals
"""


@app.get("/SKILL.md")
@app.get("/.well-known/SKILL.md")
async def skill_md():
    return PlainTextResponse(_SKILL_MD, media_type="text/markdown")


@app.get("/api/health")
async def health():
    s = get_settings()
    settle_summary = {"pending": 0, "settled_24h": 0, "failed_24h": 0}
    if db_async.is_ready():
        try:
            row = await db_async.fetch_one(
                """
                SELECT
                  COUNT(*) FILTER (WHERE status='pending') AS pending,
                  COUNT(*) FILTER (WHERE status='settled' AND settled_at > NOW() - INTERVAL '24 hours') AS settled_24h,
                  COUNT(*) FILTER (WHERE status='failed' AND created_at > NOW() - INTERVAL '24 hours') AS failed_24h
                FROM x402_settlements
                """
            )
            if row:
                settle_summary = {k: row.get(k) or 0 for k in settle_summary}
        except Exception:
            pass  # table may not exist yet on first deploy
    return {
        "status": "ok",
        "service": "agent-api",
        "network": s.network,
        "x402_network": s.x402_network,
        "x402_configured": _x402_server is not None,
        "x402_routes": list((_x402_routes or {}).keys()),
        "db_async": await db_async.health(),
        "settlements": settle_summary,
    }
