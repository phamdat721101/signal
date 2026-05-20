// Tool definitions and Python proxy.
//
// Each tool's handler delegates to the existing Python /api/v2/agent/* endpoint
// over loopback. Heavy data is cached briefly (matches Python's existing TTLs).

import { Agent, request as undiciRequest } from 'undici';
import type { Request, Response } from 'express';
import { env } from './env.js';
import { log } from './logger.js';

// Persistent connection pool to Python — saves ~3ms TCP setup per call
const pythonAgent = new Agent({ keepAliveTimeout: 30_000, keepAliveMaxTimeout: 60_000, connections: 16 });

// ─── Tiny LRU cache ─────────────────────────────────────────────────────────
class TtlCache<V> {
  private map = new Map<string, { v: V; exp: number }>();
  constructor(private ttlMs: number, private max = 100) {}
  get(k: string): V | undefined {
    const hit = this.map.get(k);
    if (!hit) return undefined;
    if (hit.exp < Date.now()) { this.map.delete(k); return undefined; }
    // refresh recency
    this.map.delete(k); this.map.set(k, hit);
    return hit.v;
  }
  set(k: string, v: V): void {
    if (this.map.size >= this.max) {
      const first = this.map.keys().next().value;
      if (first !== undefined) this.map.delete(first);
    }
    this.map.set(k, { v, exp: Date.now() + this.ttlMs });
  }
}

// ─── Python proxy ───────────────────────────────────────────────────────────
async function fetchPython(path: string, query: Record<string, string | undefined>): Promise<{ ok: boolean; status: number; body: unknown }> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== '') qs.set(k, v);
  const url = `${env.PYTHON_INTERNAL_URL}${path}${qs.toString() ? `?${qs.toString()}` : ''}`;
  try {
    const r = await undiciRequest(url, { method: 'GET', dispatcher: pythonAgent, headersTimeout: 5_000, bodyTimeout: 10_000 });
    const text = await r.body.text();
    return { ok: r.statusCode < 400, status: r.statusCode, body: text ? JSON.parse(text) : null };
  } catch (e: any) {
    log.warn('python_proxy failed', { path, err: e.message });
    return { ok: false, status: 502, body: { error: 'upstream_unreachable' } };
  }
}

// ─── Tool catalog ───────────────────────────────────────────────────────────
export interface ToolSpec {
  name: string;
  path: string;
  priceMicroUsdc: bigint;
  description: string;
  inputSchema: { properties: Record<string, { type: string; description?: string }>; required: string[] };
  outputExample: object;
  cacheTtlMs: number;
  pickQuery: (req: Request) => Record<string, string | undefined>;
}

export const TOOLS: ToolSpec[] = [
  {
    name: 'decisions',
    path: '/api/v2/agent/decisions',
    priceMicroUsdc: 1000n, // $0.001
    description: 'AI crypto trading signals with on-chain verifiable 60.8% accuracy across 5,816+ resolved predictions. Returns APE/FADE verdicts with confidence, entry, target, stop, reasoning, and per-token track record.',
    inputSchema: { properties: { limit: { type: 'string', description: 'Max results 1-50' } }, required: [] },
    outputExample: { decisions: [{ token: 'BTC', action: 'APE', confidence: 85, entry: 104250.5, target: 105814.3, stop: 102686.7, reasoning: 'Bullish EMA crossover + RSI momentum', track_record: { win_rate: 68.5, sample_size: 42 } }], total: 1 },
    cacheTtlMs: 0,
    pickQuery: (req) => ({ limit: req.query.limit as string | undefined }),
  },
  {
    name: 'prices',
    path: '/api/v2/agent/prices',
    priceMicroUsdc: 1000n,
    description: 'Real-time aggregated cryptocurrency spot prices from CoinGecko + DexScreener with source attribution. Pass comma-separated symbols (e.g. BTC,ETH,SOL).',
    inputSchema: { properties: { symbols: { type: 'string', description: 'CSV symbols e.g. BTC,ETH' } }, required: ['symbols'] },
    outputExample: { prices: [{ symbol: 'BTC', price: 104250.5, source: 'coingecko' }] },
    cacheTtlMs: 0,
    pickQuery: (req) => ({ symbols: req.query.symbols as string | undefined }),
  },
  {
    name: 'pools',
    path: '/api/v2/agent/pools',
    priceMicroUsdc: 5000n, // $0.005
    description: 'DeFi LP pool advisory ranked by APY and TVL with impermanent-loss risk scoring across multiple chains and protocols.',
    inputSchema: { properties: { limit: { type: 'string' } }, required: [] },
    outputExample: { pools: [{ pair: 'ETH/USDC', apy: 12.5, tvl: 5_000_000, risk_score: 35 }], total: 1 },
    cacheTtlMs: 30_000,
    pickQuery: (req) => ({ limit: req.query.limit as string | undefined }),
  },
  {
    name: 'track-record',
    path: '/api/v2/agent/track-record',
    priceMicroUsdc: 10_000n, // $0.01
    description: 'Historical prediction accuracy and per-token win rates from on-chain resolved predictions. Includes overall accuracy, per-token breakdown, sample size, and average PnL.',
    inputSchema: { properties: {}, required: [] },
    outputExample: { overall: { total: 5816, wins: 3534, win_rate: 60.8 }, per_token: { BTC: { total: 42, wins: 29, win_rate: 69.0, avg_pnl: 1.42 } } },
    cacheTtlMs: 60_000,
    pickQuery: () => ({}),
  },
  {
    name: 'context',
    path: '/api/v2/agent/context',
    priceMicroUsdc: 10_000n,
    description: 'Macro market context: BTC/ETH ETF net flows, macro economic event calendar, sector rotation signals, breaking news, plus AI oracle current market mood.',
    inputSchema: { properties: {}, required: [] },
    outputExample: { sosovalue: { etf_flows: { btc_net_flow_24h: 150_000_000 } }, oracle_mood: 'bullish' },
    cacheTtlMs: 30_000,
    pickQuery: () => ({}),
  },
];

const caches = new Map<string, TtlCache<unknown>>();
for (const t of TOOLS) if (t.cacheTtlMs > 0) caches.set(t.name, new TtlCache(t.cacheTtlMs));

export function makeToolHandler(spec: ToolSpec) {
  return async (req: Request, res: Response) => {
    const q = spec.pickQuery(req);
    const cacheKey = `${spec.name}:${JSON.stringify(q)}`;
    const cache = caches.get(spec.name);
    if (cache) {
      const hit = cache.get(cacheKey);
      if (hit) return res.json(hit);
    }
    const r = await fetchPython(spec.path, q);
    if (!r.ok) return res.status(r.status).json(r.body);
    if (cache) cache.set(cacheKey, r.body);
    return res.json(r.body);
  };
}
