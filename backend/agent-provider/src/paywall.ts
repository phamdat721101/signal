// Self-contained x402 paywall for Arbitrum Sepolia.
//
// Why bypass n-payment v0.18 createPaywall:
//   - Its verify path requires an external facilitator URL with a /verify
//     endpoint. We audited the public x402.org/facilitator and it does NOT
//     support Arbitrum Sepolia (only base-sepolia, solana-devnet, etc.).
//   - CDP facilitator requires server-side auth that we won't expose to
//     buyers. Self-hosting another sponsor-facilitator process re-introduces
//     the operational footprint we just retired with morph-hoodi-facilitator
//     ("do_not_repeat_sample_mistake").
//
// Design — buyer-direct settlement, server verify-only:
//   1. GET /api/v2/agent/* without `x-payment-tx` → 402 with payment-required
//      header (standard x402 envelope, scheme=exact, network=eip155:421614).
//   2. Buyer signs EIP-3009 typed data and submits transferWithAuthorization
//      to the USDC contract themselves (pays ~$0.0001 testnet ETH gas).
//   3. GET retry with `x-payment-tx: <hash>` header.
//   4. This middleware reads the tx receipt via viem, validates:
//        - Tx was successful
//        - Tx was sent to the configured USDC contract
//        - It emitted a Transfer(from=*, to=PAY_TO, value>=PRICE) event
//      → next() on success, 402 on failure.
//
// SOLID:
//   - Single responsibility: paywall middleware. No on-chain settlement,
//     no facilitator forwarding, no audit DB.
//   - In-process LRU cache (60-s TTL keyed by tx hash) so a buyer who
//     replays the same tx hash for follow-up cards doesn't re-verify on
//     every call. Dedupe of recently-spent tx hashes prevents reuse for
//     a different route.

import type { Request, Response, NextFunction } from 'express';
import { createPublicClient, decodeEventLog, http, parseAbi, type PublicClient } from 'viem';
import { arbitrumSepolia } from 'viem/chains';
import { env } from './env.js';
import { TOOLS, type ToolSpec } from './tools.js';
import { log } from './logger.js';

const NETWORK = 'eip155:421614';
const USDC = '0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d' as const; // Arb Sepolia Circle USDC
const ERC20_TRANSFER_ABI = parseAbi([
  'event Transfer(address indexed from, address indexed to, uint256 value)',
]);

const publicClient: PublicClient = createPublicClient({
  chain: arbitrumSepolia,
  transport: http(),
});

// Tx-hash → expiry-epoch-ms. A spent tx hash can re-authorize the same
// (route, payer) for `_TX_REUSE_WINDOW_MS` so polite retries (network
// flake on the GET, etc.) succeed without re-paying. Different routes
// or amounts force a fresh tx.
const _spent: Map<string, { route: string; payer: string; valueMicroUsdc: bigint; exp: number }> = new Map();
const _TX_REUSE_WINDOW_MS = 60_000;
const _MAX_RECEIPT_RETRIES = 6;
const _RECEIPT_BACKOFF_MS = 1_500;

const ROUTE_INDEX: Map<string, ToolSpec> = new Map(TOOLS.map((t) => [`/api/v2/agent/${t.name}`, t]));

function buildChallenge(price: bigint): string {
  const envelope = {
    x402Version: 2,
    accepts: [{
      scheme: 'exact',
      network: NETWORK,
      maxAmountRequired: price.toString(),
      asset: USDC,
      payTo: env.PAY_TO_ADDRESS,
    }],
  };
  return Buffer.from(JSON.stringify(envelope)).toString('base64');
}

function emit402(res: Response, price: bigint, reason?: string): void {
  res.setHeader('payment-required', buildChallenge(price));
  res.status(402).json({ error: 'Payment required', protocols: ['x402'], reason });
}

async function waitForReceipt(hash: `0x${string}`) {
  // Submit→inclusion can take ~2-5 s on Arb Sepolia. Bounded retry so a
  // buyer who immediately retries after sending tx isn't 402'd unfairly.
  for (let i = 0; i < _MAX_RECEIPT_RETRIES; i++) {
    try {
      return await publicClient.getTransactionReceipt({ hash });
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
  valueMicroUsdc?: bigint;
}

async function verifyPaymentTx(
  txHash: `0x${string}`,
  routeKey: string,
  minValue: bigint,
): Promise<VerifyResult> {
  // Cache hit: same tx already validated for the same (route, payer, value)
  // within the reuse window. Block reuse for a *different* route to prevent
  // one $0.001 tx authorizing both /decisions and /pools.
  const cached = _spent.get(txHash);
  if (cached) {
    if (cached.exp < Date.now()) {
      _spent.delete(txHash);
    } else if (cached.route === routeKey && cached.valueMicroUsdc >= minValue) {
      return { ok: true, payer: cached.payer, valueMicroUsdc: cached.valueMicroUsdc };
    } else {
      return { ok: false, reason: 'tx_already_spent_on_other_route' };
    }
  }

  const receipt = await waitForReceipt(txHash);
  if (!receipt) return { ok: false, reason: 'receipt_unavailable' };
  if (receipt.status !== 'success') return { ok: false, reason: 'tx_reverted' };

  // Find a Transfer log on the USDC contract with to=PAY_TO and value>=minValue.
  let payer: `0x${string}` | undefined;
  let value: bigint = 0n;
  for (const lg of receipt.logs) {
    if (lg.address.toLowerCase() !== USDC.toLowerCase()) continue;
    try {
      const decoded = decodeEventLog({ abi: ERC20_TRANSFER_ABI, topics: lg.topics, data: lg.data });
      if (decoded.eventName !== 'Transfer') continue;
      const { from, to, value: v } = decoded.args as { from: `0x${string}`; to: `0x${string}`; value: bigint };
      if (to.toLowerCase() === env.PAY_TO_ADDRESS.toLowerCase() && v >= minValue) {
        payer = from;
        value = v;
        break;
      }
    } catch {
      /* not a Transfer event we care about */
    }
  }
  if (!payer) return { ok: false, reason: 'no_matching_transfer_to_pay_to' };

  _spent.set(txHash, {
    route: routeKey,
    payer,
    valueMicroUsdc: value,
    exp: Date.now() + _TX_REUSE_WINDOW_MS,
  });
  return { ok: true, payer, valueMicroUsdc: value };
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

  const result = await verifyPaymentTx(txHash as `0x${string}`, req.path, tool.priceMicroUsdc);
  if (!result.ok) {
    log.warn('paywall verify failed', { path: req.path, txHash, reason: result.reason });
    emit402(res, tool.priceMicroUsdc, result.reason);
    return;
  }

  // Stamp the request so downstream handlers can audit who paid.
  (req as Request & { payment?: { payer?: string; tx: string; valueMicroUsdc?: bigint } }).payment = {
    payer: result.payer,
    tx: txHash,
    valueMicroUsdc: result.valueMicroUsdc,
  };
  next();
}

/** Discovery — exported for /api/health, agent.json, tools/list. */
export const SUPPORTED_RAILS = [
  { chain: 'arbitrum-sepolia', network: NETWORK, asset: USDC, scheme: 'exact' },
] as const;
export const SUPPORTED_NETWORK = NETWORK;
export const SUPPORTED_ASSET = USDC;
