// Multi-chain x402 payment gate.
//
// Responsibility: emit v2-spec PAYMENT-REQUIRED envelopes (multiple accepts
// entries — Base + Stellar + ...), verify incoming payments against the
// matching facilitator, and queue settle for an async worker.
//
// We intentionally call the CDP / OZ facilitators directly (not via n-payment
// v0.12's high-level provider) so the verify path is fully under our control
// and matches the v2 transport spec exactly. n-payment is still used for
// `paidTool` discovery metadata (see tools.ts) and for the streaming SKU.

import type { NextFunction, Request, Response } from 'express';
import crypto from 'node:crypto';
import { request as undiciRequest } from 'undici';
import { env } from './env.js';
import { log } from './logger.js';
import { recordPending, recordAudit, isAlreadySettled } from './payment_state.js';

// ─── Chain constants — single source of truth for accepts envelope ──────────
type ChainKey = 'base-mainnet' | 'stellar-mainnet' | 'tempo-mainnet';

const CHAIN_INFO: Record<ChainKey, {
  network: string;        // CAIP-2
  asset: string;          // USDC contract / SAC
  receiver: () => string | undefined;
  facilitatorUrl: string;
  scheme: string;
}> = {
  'base-mainnet': {
    network: 'eip155:84532',
    asset: '0x036CbD53842c5426634e7929541eC2318f3dCF7e',
    receiver: () => env.BASE_RECEIVER,
    facilitatorUrl: env.CDP_API_KEY_ID ? 'https://api.cdp.coinbase.com/platform/v2/x402' : 'https://x402.org/facilitator',
    scheme: 'exact',
  },
  'stellar-mainnet': {
    network: 'stellar:pubnet',
    asset: 'CCW67TSZV3SSS2HXMBQ5JFGCKJNXKZM7UQUWUZPUTHXSTZLEO7SJMI75',
    receiver: () => env.STELLAR_RECEIVER,
    facilitatorUrl: 'https://channels.openzeppelin.com/x402',
    scheme: 'exact',
  },
  'tempo-mainnet': {
    network: 'eip155:4217',
    asset: '0x20C000000000000000000000b9537d11c60E8b50',
    receiver: () => env.TEMPO_RECEIVER,
    facilitatorUrl: 'https://api.cdp.coinbase.com/platform/v2/x402',
    scheme: 'exact',
  },
};

// ─── CDP JWT signing (ES256) — internal helper ──────────────────────────────
function signCdpJwt(method: string, path: string): string {
  const host = 'api.cdp.coinbase.com';
  const header = { alg: 'ES256', kid: env.CDP_API_KEY_ID, typ: 'JWT', nonce: crypto.randomBytes(16).toString('hex') };
  const now = Math.floor(Date.now() / 1000);
  const payload = { sub: env.CDP_API_KEY_ID, iss: 'cdp', aud: ['cdp_service'], nbf: now, exp: now + 120, uris: [`${method.toUpperCase()} ${host}${path}`] };
  const enc = (o: object) => Buffer.from(JSON.stringify(o)).toString('base64url');
  const signing = `${enc(header)}.${enc(payload)}`;
  const signer = crypto.createSign('SHA256');
  signer.update(signing);
  const der = signer.sign(env.CDP_API_KEY_SECRET);
  // Convert DER → JOSE (r||s, 64 bytes for P-256)
  return `${signing}.${derToJose(der).toString('base64url')}`;
}

function derToJose(der: Buffer): Buffer {
  // ES256 fixed at 64 bytes (r||s, 32 each). Strip DER wrapper.
  let i = 4;
  const rLen = der[3]!;
  const r = der.subarray(i, i + rLen);
  i += rLen + 2;
  const sLen = der[i - 1]!;
  const s = der.subarray(i, i + sLen);
  const pad = (b: Buffer) => b.length < 32 ? Buffer.concat([Buffer.alloc(32 - b.length), b]) : b.subarray(b.length - 32);
  return Buffer.concat([pad(r), pad(s)]);
}

// ─── Facilitator HTTP client ────────────────────────────────────────────────
type FacilitatorBody = { paymentPayload: unknown; paymentRequirements: unknown };

async function callFacilitator(network: string, route: 'verify' | 'settle', body: FacilitatorBody)
  : Promise<{ ok: boolean; data?: any; error?: string }> {
  const chain = Object.values(CHAIN_INFO).find(c => c.network === network);
  if (!chain) return { ok: false, error: `unsupported_network:${network}` };

  const path = `/${route}`;
  const fullPath = chain.facilitatorUrl.includes('cdp.coinbase.com')
    ? `/platform/v2/x402${path}`
    : `/x402${path}`;
  const url = chain.facilitatorUrl.includes('cdp.coinbase.com')
    ? `https://api.cdp.coinbase.com${fullPath}`
    : `${chain.facilitatorUrl}${path}`;

  const headers: Record<string, string> = { 'content-type': 'application/json' };
  if (chain.facilitatorUrl.includes('cdp.coinbase.com')) {
    headers['authorization'] = `Bearer ${signCdpJwt('POST', fullPath)}`;
  } else if (chain.facilitatorUrl.includes('openzeppelin.com')) {
    if (!env.OZ_API_KEY) return { ok: false, error: 'oz_api_key_missing' };
    headers['x-api-key'] = env.OZ_API_KEY;
  }

  try {
    const res = await undiciRequest(url, { method: 'POST', headers, body: JSON.stringify(body), bodyTimeout: 10_000, headersTimeout: 5_000 });
    const text = await res.body.text();
    if (res.statusCode >= 400) return { ok: false, error: `${res.statusCode}:${text.slice(0, 200)}` };
    return { ok: true, data: text ? JSON.parse(text) : {} };
  } catch (e: any) {
    return { ok: false, error: `facilitator_unreachable:${e.message}` };
  }
}

// ─── Envelope builder ───────────────────────────────────────────────────────
const PRICE_DECIMALS = 1_000_000n; // USDC has 6 decimals; price input is microUSDC

function buildAccepts(supportedChains: ChainKey[], priceMicroUsdc: bigint) {
  return supportedChains
    .map((key) => {
      const c = CHAIN_INFO[key];
      const payTo = c.receiver();
      if (!payTo) return null;
      return {
        scheme: c.scheme,
        network: c.network,
        maxAmountRequired: priceMicroUsdc.toString(),
        asset: c.asset,
        payTo,
        maxTimeoutSeconds: 60,
      };
    })
    .filter((x): x is NonNullable<typeof x> => x !== null);
}

// ─── Express middleware factory ─────────────────────────────────────────────
export interface GateOptions {
  toolName: string;
  priceMicroUsdc: bigint;
  supportedChains: ChainKey[];
  description: string;
  inputSchema?: object;
  outputExample?: object;
}

const PAYMENT_HEADERS = ['payment-signature', 'x-payment'] as const;

function getPaymentHeader(req: Request): { raw: string; key: string } | null {
  for (const k of PAYMENT_HEADERS) {
    const v = req.header(k);
    if (v) return { raw: v, key: k };
  }
  return null;
}

function decodePayload(raw: string): { network?: string; payer?: string; [k: string]: unknown } {
  try { return JSON.parse(Buffer.from(raw, 'base64').toString('utf8')); }
  catch { return {}; }
}

function buildExtensions(opts: GateOptions) {
  return {
    bazaar: {
      info: {
        input: { type: 'http', method: 'GET', queryParams: opts.inputSchema ? {} : {} },
        output: { type: 'json', example: opts.outputExample ?? {} },
      },
      schema: opts.inputSchema ? { properties: { input: opts.inputSchema } } : undefined,
    },
  };
}

export function paymentGate(opts: GateOptions, settleQueue: SettleQueue) {
  return async (req: Request, res: Response, next: NextFunction) => {
    const resourceUrl = `${env.PUBLIC_BASE_URL}${req.path}`;
    const accepts = buildAccepts(opts.supportedChains, opts.priceMicroUsdc);

    // No payment header → emit v2-spec 402 with PAYMENT-REQUIRED header
    const ph = getPaymentHeader(req);
    if (!ph) {
      const envelope = {
        x402Version: 2,
        resource: { url: resourceUrl, type: 'http', description: opts.description, mimeType: 'application/json' },
        accepts,
        extensions: buildExtensions(opts),
      };
      const b64 = Buffer.from(JSON.stringify(envelope)).toString('base64');
      res.setHeader('PAYMENT-REQUIRED', b64);
      res.setHeader('payment-required', b64); // v0.12 compat
      return res.status(402).json(envelope); // body kept for clients that only parse JSON
    }

    // Decode + dispatch
    const payload = decodePayload(ph.raw);
    if (!payload.network) return res.status(400).json({ error: 'invalid_payment_payload' });
    const matched = accepts.find(a => a.network === payload.network);
    if (!matched) return res.status(400).json({ error: 'unsupported_network', network: payload.network });

    // Idempotency — same payload header twice = single audit entry
    const payloadHash = crypto.createHash('sha256').update(ph.raw).digest('hex');
    if (await isAlreadySettled(payloadHash)) {
      log.info('replayed payment', { rid: req.header('x-request-id'), payload_hash: payloadHash.slice(0, 12) });
      return next(); // already paid; deliver the data again (server is idempotent)
    }

    // Verify with facilitator
    const verifyResp = await callFacilitator(payload.network, 'verify', { paymentPayload: payload, paymentRequirements: matched });
    if (!verifyResp.ok || !verifyResp.data?.isValid) {
      return res.status(402).json({ error: 'payment_invalid', reason: verifyResp.error || verifyResp.data?.invalidReason });
    }

    // Persist intent BEFORE delivering data — outbox pattern survives crash
    await recordPending({ payloadHash, resource: resourceUrl, network: payload.network, payer: verifyResp.data.payer ?? payload.payer ?? null, amount: matched.maxAmountRequired });
    await recordAudit({ toolName: opts.toolName, network: payload.network, payer: verifyResp.data.payer ?? '', amount: matched.maxAmountRequired, payloadHash, status: 'verified', referenceKey: req.header('x-reference-key') ?? null, requestId: req.header('x-request-id') ?? null });

    // Queue settle (async — does not block response)
    settleQueue.enqueue({ payloadHash, network: payload.network, paymentPayload: payload, paymentRequirements: matched });
    return next();
  };
}

// ─── Settle queue (in-process, with PG persistence for crash recovery) ──────
export interface SettleJob {
  payloadHash: string;
  network: string;
  paymentPayload: unknown;
  paymentRequirements: unknown;
}

export class SettleQueue {
  enqueue(job: SettleJob): void {
    // Fire-and-forget. Persistent state is in x402_settlements (recordPending).
    // Settler process picks up rows where status='pending'.
    void this.settleNow(job).catch(e => log.warn('settle exception', { err: e.message, hash: job.payloadHash.slice(0, 12) }));
  }

  async settleNow(job: SettleJob): Promise<void> {
    const r = await callFacilitator(job.network, 'settle', { paymentPayload: job.paymentPayload, paymentRequirements: job.paymentRequirements });
    const { markSettled, markFailed } = await import('./payment_state.js');
    if (r.ok && r.data?.success) {
      await markSettled(job.payloadHash, r.data.transaction ?? '');
      log.info('settled', { hash: job.payloadHash.slice(0, 12), tx: (r.data.transaction ?? '').slice(0, 16) });
    } else {
      await markFailed(job.payloadHash, r.error ?? r.data?.errorReason ?? 'unknown');
      log.warn('settle failed', { hash: job.payloadHash.slice(0, 12), err: r.error });
    }
  }
}
