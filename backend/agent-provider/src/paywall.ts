// Self-contained x402 paywall — multi-rail (Arb Sepolia + GOAT testnet).
//
// Why bypass n-payment v0.18 createPaywall:
//   - Its verify path requires an external facilitator URL with a /verify
//     endpoint. Public x402.org/facilitator does not support Arb Sepolia
//     or GOAT (only base-sepolia, solana-devnet, etc.).
//   - CDP facilitator requires server-side auth that we won't expose to
//     buyers. Self-hosting another sponsor-facilitator process re-introduces
//     unwanted operational footprint ("do_not_repeat_sample_mistake").
//
// Design — buyer-direct settlement, server verify-only:
//   1. GET /api/v2/agent/* without `x-payment-tx` →
//      402 with `payment-required` envelope listing every configured rail
//      under `accepts[]` (per x402 spec — buyer picks one).
//   2. Buyer signs+broadcasts the on-chain payment on whichever rail they
//      hold balance for. Pays gas themselves.
//   3. Retry GET with:
//        x-payment-tx:      <hash>
//        x-payment-network: eip155:<chainId>   ← which rail was paid on
//   4. This middleware:
//        - looks up the rail by `x-payment-network` (falls back to RAILS[0]
//          for legacy clients that don't send the header),
//        - reads the receipt via that rail's viem PublicClient,
//        - validates `Transfer(* → payTo, value ≥ price)` on the rail's token,
//      → next() on success, 402 on failure.
//
// SOLID:
//   - Single responsibility: paywall middleware. No on-chain settlement,
//     no facilitator forwarding, no audit DB.
//   - Open/closed: adding a 3rd rail is one entry in `RAILS`. No middleware
//     edits.
//   - In-process LRU cache (60-s TTL, key = `${network}:${tx}`) so a buyer
//     who replays the same tx for follow-up cards doesn't re-verify on
//     every call. Cross-route reuse blocked.

import type { Request, Response, NextFunction } from 'express';
import {
  createPublicClient, decodeEventLog, defineChain, http, parseAbi,
  type PublicClient,
} from 'viem';
import { arbitrumSepolia } from 'viem/chains';
import { env } from './env.js';
import { TOOLS, type ToolSpec } from './tools.js';
import { log } from './logger.js';

const ERC20_TRANSFER_ABI = parseAbi([
  'event Transfer(address indexed from, address indexed to, uint256 value)',
]);

interface Rail {
  /** CAIP-2 network id (`eip155:<chainId>`). */
  network: string;
  asset: `0x${string}`;
  payTo: `0x${string}`;
  tokenSymbol: string;
  publicClient: PublicClient;
  /** USD micro-cent (microUSDC) → smallest unit of this rail's token. */
  priceWei: (microUsdc: bigint) => bigint;
}

// ─── Rail registry ────────────────────────────────────────────────────────
// Index 0 = default fallback for legacy clients that retry without an
// `x-payment-network` header (preserves backward-compat with existing buyers).
const RAILS: [Rail, ...Rail[]] = [
  // Arb Sepolia — USDC, 6-dec, microUSDC == base unit.
  {
    network: 'eip155:421614',
    asset: '0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d',
    payTo: env.PAY_TO_ADDRESS as `0x${string}`,
    tokenSymbol: 'USDC',
    publicClient: createPublicClient({ chain: arbitrumSepolia, transport: http() }),
    priceWei: (mu) => mu,
  },
];

const DEFAULT_RAIL: Rail = RAILS[0];

// GOAT testnet (additive). Default token = WGBTC, 18-dec, BTC-priced.
// Static USD-per-token rate keeps the hot path RPC-free.
if (env.GOAT_X402_ENABLED) {
  const payTo = (env.GOAT_X402_PAY_TO ?? env.PAY_TO_ADDRESS) as `0x${string}`;
  const goatChain = defineChain({
    id: 48816,
    name: 'GOAT Testnet',
    nativeCurrency: { name: 'BTC', symbol: 'BTC', decimals: 18 },
    rpcUrls: { default: { http: [env.GOAT_X402_RPC_URL] } },
  });
  const decimals = 18;
  // microUSDC * 10^decimals / (1e6 * usdPerToken)
  const factor = 10n ** BigInt(decimals);
  const denom = 1_000_000n * BigInt(Math.round(env.GOAT_X402_TOKEN_USD_PRICE));
  RAILS.push({
    network: 'eip155:48816',
    asset: env.GOAT_X402_TOKEN_ADDRESS as `0x${string}`,
    payTo,
    tokenSymbol: env.GOAT_X402_TOKEN_SYMBOL,
    publicClient: createPublicClient({ chain: goatChain, transport: http() }),
    priceWei: (mu) => {
      const w = (mu * factor) / denom;
      return w < 1n ? 1n : w; // dust floor — never let "$0" pass
    },
  });
  log.info('paywall: GOAT rail enabled', {
    network: 'eip155:48816', token: env.GOAT_X402_TOKEN_SYMBOL,
    asset: env.GOAT_X402_TOKEN_ADDRESS, payTo, usdPerToken: env.GOAT_X402_TOKEN_USD_PRICE,
  });
}

// ─── Cache ────────────────────────────────────────────────────────────────
const _spent: Map<string, { route: string; payer: string; valueWei: bigint; exp: number }> = new Map();
const _TX_REUSE_WINDOW_MS = 60_000;
const _MAX_RECEIPT_RETRIES = 6;
const _RECEIPT_BACKOFF_MS = 1_500;

const ROUTE_INDEX: Map<string, ToolSpec> = new Map(TOOLS.map((t) => [`/api/v2/agent/${t.name}`, t]));

function buildChallenge(microUsdc: bigint): string {
  const envelope = {
    x402Version: 2,
    accepts: RAILS.map((r) => ({
      scheme: 'exact',
      network: r.network,
      maxAmountRequired: r.priceWei(microUsdc).toString(),
      asset: r.asset,
      payTo: r.payTo,
      tokenSymbol: r.tokenSymbol,
    })),
  };
  return Buffer.from(JSON.stringify(envelope)).toString('base64');
}

function emit402(res: Response, microUsdc: bigint, reason?: string): void {
  res.setHeader('payment-required', buildChallenge(microUsdc));
  res.status(402).json({ error: 'Payment required', protocols: ['x402'], reason });
}

async function waitForReceipt(rail: Rail, hash: `0x${string}`) {
  for (let i = 0; i < _MAX_RECEIPT_RETRIES; i++) {
    try {
      return await rail.publicClient.getTransactionReceipt({ hash });
    } catch {
      await new Promise((r) => setTimeout(r, _RECEIPT_BACKOFF_MS));
    }
  }
  return null;
}

interface VerifyResult {
  ok: boolean;
  reason?: string;
  payer?: string;
  valueWei?: bigint;
}

async function verifyPaymentTx(
  rail: Rail,
  txHash: `0x${string}`,
  routeKey: string,
  minValueWei: bigint,
): Promise<VerifyResult> {
  // Cache key includes network so the same tx hash on different chains
  // (impossible by physics, but cheap defensive coding) doesn't collide.
  const cacheKey = `${rail.network}:${txHash}`;
  const cached = _spent.get(cacheKey);
  if (cached) {
    if (cached.exp < Date.now()) {
      _spent.delete(cacheKey);
    } else if (cached.route === routeKey && cached.valueWei >= minValueWei) {
      return { ok: true, payer: cached.payer, valueWei: cached.valueWei };
    } else {
      return { ok: false, reason: 'tx_already_spent_on_other_route' };
    }
  }

  const receipt = await waitForReceipt(rail, txHash);
  if (!receipt) return { ok: false, reason: 'receipt_unavailable' };
  if (receipt.status !== 'success') return { ok: false, reason: 'tx_reverted' };

  // Find a Transfer log on this rail's token, to=payTo, value≥minValueWei.
  let payer: `0x${string}` | undefined;
  let value: bigint = 0n;
  for (const lg of receipt.logs) {
    if (lg.address.toLowerCase() !== rail.asset.toLowerCase()) continue;
    try {
      const decoded = decodeEventLog({ abi: ERC20_TRANSFER_ABI, topics: lg.topics, data: lg.data });
      if (decoded.eventName !== 'Transfer') continue;
      const { from, to, value: v } = decoded.args as { from: `0x${string}`; to: `0x${string}`; value: bigint };
      if (to.toLowerCase() === rail.payTo.toLowerCase() && v >= minValueWei) {
        payer = from;
        value = v;
        break;
      }
    } catch { /* not a Transfer event we care about */ }
  }
  if (!payer) return { ok: false, reason: 'no_matching_transfer_to_pay_to' };

  _spent.set(cacheKey, {
    route: routeKey,
    payer,
    valueWei: value,
    exp: Date.now() + _TX_REUSE_WINDOW_MS,
  });
  return { ok: true, payer, valueWei: value };
}

export async function paywall(req: Request, res: Response, next: NextFunction): Promise<void> {
  const tool = ROUTE_INDEX.get(req.path);
  if (!tool || req.method !== 'GET') return next();

  const txHash = (req.headers['x-payment-tx'] as string | undefined)?.trim();
  if (!txHash) {
    emit402(res, tool.priceMicroUsdc);
    return;
  }
  if (!/^0x[0-9a-fA-F]{64}$/.test(txHash)) {
    emit402(res, tool.priceMicroUsdc, 'invalid_tx_hash');
    return;
  }

  // Pick rail by network header; fall back to DEFAULT_RAIL (Arb Sepolia)
  // for legacy clients that don't yet send `x-payment-network`.
  const networkHdr = (req.headers['x-payment-network'] as string | undefined)?.trim();
  const rail = (networkHdr && RAILS.find((r) => r.network === networkHdr)) || DEFAULT_RAIL;
  const minValueWei = rail.priceWei(tool.priceMicroUsdc);

  const result = await verifyPaymentTx(rail, txHash as `0x${string}`, req.path, minValueWei);
  if (!result.ok) {
    log.warn('paywall verify failed', {
      path: req.path, network: rail.network, txHash, reason: result.reason,
    });
    emit402(res, tool.priceMicroUsdc, result.reason);
    return;
  }

  // Stamp the request so handlers can audit who paid (and on which rail).
  (req as Request & {
    payment?: { payer?: string; tx: string; valueWei?: bigint; network: string };
  }).payment = {
    payer: result.payer, tx: txHash, valueWei: result.valueWei, network: rail.network,
  };
  next();
}

/** Discovery — exported for /api/health, agent.json, tools/list. */
export const SUPPORTED_RAILS = RAILS.map((r) => ({
  network: r.network, asset: r.asset, scheme: 'exact', tokenSymbol: r.tokenSymbol,
}));
/** Default network advertised in legacy single-network discovery fields. */
export const SUPPORTED_NETWORK = DEFAULT_RAIL.network;
export const SUPPORTED_ASSET = DEFAULT_RAIL.asset;
