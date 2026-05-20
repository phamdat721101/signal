// Express boot. Composes: payment_gate -> tools handler.
// Also serves discovery surfaces: SKILL.md, /.well-known/agent.json, /tools/list.

import express, { type Request, type Response, type NextFunction } from 'express';
import crypto from 'node:crypto';
import { env, supportedChains } from './env.js';
import { log } from './logger.js';
import { dbHealthy, pool } from './db.js';
import { TOOLS, makeToolHandler } from './tools.js';
import { paymentGate, SettleQueue } from './payment_gate.js';
import { streamHandler } from './streaming.js';

const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '64kb' }));

// Request-id propagation (mirrors Python middleware in app.main)
app.use((req: Request, res: Response, next: NextFunction) => {
  const rid = req.header('x-request-id') ?? crypto.randomBytes(6).toString('hex');
  res.setHeader('x-request-id', rid);
  (req.headers as Record<string, string>)['x-request-id'] = rid;
  const start = Date.now();
  res.on('finish', () => {
    if (req.path !== '/api/health' && req.path !== '/api/health/deep') {
      log.info('http', { rid, m: req.method, p: req.path, s: res.statusCode, ms: Date.now() - start });
    }
  });
  next();
});

// CORS — same as Python (open; we lock down via Caddy + payment gate)
app.use((_req: Request, res: Response, next: NextFunction) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', '*');
  next();
});

// ─── Health ────────────────────────────────────────────────────────────────
app.get('/api/health', (_req, res) => res.json({ status: 'ok', service: 'agent-provider', version: '0.1.0' }));

app.get('/api/health/deep', async (_req, res) => {
  const db = await dbHealthy();
  const ok = db;
  res.status(ok ? 200 : 503).json({
    status: ok ? 'ok' : 'degraded',
    db,
    supported_chains: supportedChains,
    public_base_url: env.PUBLIC_BASE_URL,
  });
});

// ─── Discovery surfaces ────────────────────────────────────────────────────
function buildSkillMd(): string {
  const lines = [
    `# Signal Trading Intelligence API (x402)`,
    ``,
    `AI trading signals with on-chain verifiable accuracy. Pay per call in USDC.`,
    ``,
    `Networks: ${supportedChains.join(', ')}`,
    ``,
    `## Endpoints`,
    ...TOOLS.map(t => `- GET /api/v2/agent/${t.name} — $${(Number(t.priceMicroUsdc) / 1_000_000).toFixed(4)} — ${t.description}`),
    `- GET /api/v2/agent/live-decisions-stream — $0.0005/emit (SSE) — Live decisions stream, prepaid budget`,
    ``,
    `## Discovery`,
    `- GET /.well-known/agent.json — A2A Agent Card`,
    `- GET /tools/list — JSON catalog with prices and schemas`,
    `- GET https://api.cdp.coinbase.com/platform/v2/x402/discovery/search?query=trading+signals — Bazaar search`,
  ];
  return lines.join('\n') + '\n';
}

app.get(['/SKILL.md', '/.well-known/SKILL.md'], (_req, res) => {
  res.set('Content-Type', 'text/markdown').send(buildSkillMd());
});

app.get('/.well-known/agent.json', (_req, res) => {
  res.json({
    version: '1.0',
    name: 'Signal Trading Intelligence',
    description: 'AI crypto trading signals with on-chain verifiable accuracy',
    url: env.PUBLIC_BASE_URL,
    chains: supportedChains,
    protocols: ['x402', 'a2a'],
    skills: TOOLS.map(t => ({
      name: t.name,
      description: t.description,
      price_usdc: (Number(t.priceMicroUsdc) / 1_000_000).toFixed(4),
      pricingMode: 'per-call',
      inputSchema: t.inputSchema,
    })),
  });
});

app.get('/tools/list', (_req, res) => {
  res.json({
    tools: TOOLS.map(t => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema,
      'x-x402': {
        price_usdc: (Number(t.priceMicroUsdc) / 1_000_000).toFixed(4),
        chains: supportedChains,
      },
    })),
  });
});

// ─── Paid tool routes ──────────────────────────────────────────────────────
const settleQueue = new SettleQueue();

for (const tool of TOOLS) {
  app.get(
    `/api/v2/agent/${tool.name}`,
    paymentGate({
      toolName: tool.name,
      priceMicroUsdc: tool.priceMicroUsdc,
      supportedChains,
      description: tool.description,
      inputSchema: tool.inputSchema,
      outputExample: tool.outputExample,
    }, settleQueue),
    makeToolHandler(tool),
  );
}

// Streaming SKU — prepaid budget via the same payment gate (price = entry fee)
app.get(
  '/api/v2/agent/live-decisions-stream',
  paymentGate({
    toolName: 'live-decisions-stream',
    priceMicroUsdc: 50_000n, // $0.05 prepaid budget
    supportedChains,
    description: 'Server-Sent Events stream of live APE/FADE decisions. Prepaid $0.05 budget = up to 100 emits at $0.0005 each.',
    inputSchema: { properties: {}, required: [] },
    outputExample: { event: 'decision', data: { token: 'BTC', action: 'APE' } },
  }, settleQueue),
  streamHandler,
);

// ─── Boot ──────────────────────────────────────────────────────────────────
const server = app.listen(env.PORT, () => {
  log.info('agent-provider listening', { port: env.PORT, chains: supportedChains, public: env.PUBLIC_BASE_URL });
});

// Graceful drain on SIGTERM (PM2 sends SIGINT on reload, SIGTERM on stop)
function shutdown(sig: string) {
  log.info('shutdown signal received', { sig });
  server.close((err) => {
    if (err) log.error('server close error', { err: err.message });
    void pool.end().finally(() => process.exit(err ? 1 : 0));
  });
  // Hard kill if drain takes too long (PM2 kill_timeout: 8s)
  setTimeout(() => process.exit(1), 7_000).unref();
}
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
