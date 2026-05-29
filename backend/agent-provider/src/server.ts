// Express boot for agent-provider — Morph Hoodi only.
//
// Composes: paywall (n-payment v0.18 single-rail) → tools handler.
// Discovery surfaces: SKILL.md, /.well-known/agent.json, /tools/list, /api/health.

import express, { type Request, type Response, type NextFunction } from 'express';
import crypto from 'node:crypto';
import { env, SUPPORTED_CHAINS } from './env.js';
import { log } from './logger.js';
import { TOOLS, makeToolHandler } from './tools.js';
import { paywall, SUPPORTED_NETWORK, SUPPORTED_ASSET } from './paywall.js';

const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '64kb' }));

// Request-id propagation
app.use((req: Request, res: Response, next: NextFunction) => {
  const rid = req.header('x-request-id') ?? crypto.randomBytes(6).toString('hex');
  res.setHeader('x-request-id', rid);
  (req.headers as Record<string, string>)['x-request-id'] = rid;
  const start = Date.now();
  res.on('finish', () => {
    if (req.path !== '/api/health') {
      log.info('http', { rid, m: req.method, p: req.path, s: res.statusCode, ms: Date.now() - start });
    }
  });
  next();
});

// CORS — open; locked down by reverse proxy in prod
//   * Expose-Headers: browser JS reads `payment-required` (the 402 envelope)
//     and the `x-payment-*` headers added on the retry. Without explicit
//     exposure these are stripped from `headers.get()` even though they
//     arrive on the wire.
//   * 204 short-circuit on OPTIONS: the retry GET carries `x-payment-tx`
//     etc., which are non-safelisted and trigger a CORS preflight.
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', '*');
  res.setHeader('Access-Control-Expose-Headers', '*');
  if (req.method === 'OPTIONS') return res.status(204).end();
  next();
});

// ─── Health ────────────────────────────────────────────────────────────────
app.get('/api/health', (_req, res) =>
  res.json({ status: 'ok', service: 'agent-provider', version: '0.2.0', chains: SUPPORTED_CHAINS })
);

// ─── Discovery ─────────────────────────────────────────────────────────────
function buildSkillMd(): string {
  return [
    `# Signal Trading Intelligence API (x402)`,
    ``,
    `AI trading signals with on-chain verifiable accuracy.`,
    `Pay per call in **USDC on Morph Hoodi Testnet** (chain ${2910}).`,
    `Buyer pays 0 ETH — sponsor relays via EIP-3009.`,
    ``,
    `## Endpoints`,
    ...TOOLS.map(t => `- GET /api/v2/agent/${t.name} — $${(Number(t.priceMicroUsdc) / 1_000_000).toFixed(4)} — ${t.description}`),
    ``,
    `## Discovery`,
    `- GET /.well-known/agent.json — A2A Agent Card`,
    `- GET /tools/list — JSON catalog with prices and schemas`,
    ``,
  ].join('\n');
}

app.get(['/SKILL.md', '/.well-known/SKILL.md'], (_req, res) =>
  res.set('Content-Type', 'text/markdown').send(buildSkillMd()),
);

app.get('/.well-known/agent.json', (_req, res) =>
  res.json({
    version: '1.0',
    name: 'Signal Trading Intelligence',
    description: 'AI crypto trading signals with on-chain verifiable accuracy. Paid in USDC on Morph Hoodi Testnet (EIP-3009 sponsored).',
    url: env.PUBLIC_BASE_URL,
    chains: SUPPORTED_CHAINS,
    network: SUPPORTED_NETWORK,
    asset: SUPPORTED_ASSET,
    protocols: ['x402', 'a2a'],
    skills: TOOLS.map(t => ({
      name: t.name,
      description: t.description,
      price_usdc: (Number(t.priceMicroUsdc) / 1_000_000).toFixed(4),
      pricingMode: 'per-call',
      inputSchema: t.inputSchema,
    })),
  }),
);

app.get('/tools/list', (_req, res) =>
  res.json({
    tools: TOOLS.map(t => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema,
      'x-x402': {
        price_usdc: (Number(t.priceMicroUsdc) / 1_000_000).toFixed(4),
        chain: SUPPORTED_CHAINS[0],
        network: SUPPORTED_NETWORK,
        asset: SUPPORTED_ASSET,
      },
    })),
  }),
);

// ─── Paywall + paid tool routes ────────────────────────────────────────────
// `paywall` is one global middleware that returns 402 for unpaid requests
// matching the routes table built from TOOLS, and pass-through otherwise.
app.use(paywall);

for (const tool of TOOLS) {
  app.get(`/api/v2/agent/${tool.name}`, makeToolHandler(tool));
}

// ─── Boot ──────────────────────────────────────────────────────────────────
const server = app.listen(env.PORT, () => {
  log.info('agent-provider listening', {
    port: env.PORT,
    chain: SUPPORTED_CHAINS[0],
    facilitator: env.FACILITATOR_URL,
    public: env.PUBLIC_BASE_URL,
  });
});

function shutdown(sig: string) {
  log.info('shutdown signal received', { sig });
  server.close((err) => process.exit(err ? 1 : 0));
  setTimeout(() => process.exit(1), 7_000).unref();
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
