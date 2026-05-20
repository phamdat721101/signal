// Smoke test — boots nothing, just hits a running server.
//
//   pnpm tsx scripts/smoke.ts http://localhost:8002
//
// Asserts:
//   - GET /api/health returns 200
//   - GET /api/v2/agent/decisions returns 402 with PAYMENT-REQUIRED header
//   - The base64 envelope decodes to a valid v2 multi-chain accepts payload
//   - GET /.well-known/agent.json returns valid JSON with 5+ skills

import { strict as assert } from 'node:assert';

const base = process.argv[2] ?? 'http://localhost:8002';

async function main() {
  // 1. health
  const h = await fetch(`${base}/api/health`);
  assert.equal(h.status, 200, 'health 200');
  console.log('✓ /api/health OK');

  // 2. paid endpoint returns 402
  const r = await fetch(`${base}/api/v2/agent/decisions`);
  assert.equal(r.status, 402, `decisions returns 402 (got ${r.status})`);
  const required = r.headers.get('payment-required') ?? r.headers.get('PAYMENT-REQUIRED');
  assert.ok(required, 'PAYMENT-REQUIRED header present');
  const env = JSON.parse(Buffer.from(required, 'base64').toString('utf8'));
  assert.equal(env.x402Version, 2, 'x402Version=2');
  assert.ok(Array.isArray(env.accepts) && env.accepts.length >= 1, 'accepts array');
  assert.equal(env.accepts[0].scheme, 'exact', 'scheme=exact');
  assert.match(env.accepts[0].network, /^eip155:|^stellar:/, 'CAIP-2 network');
  console.log(`✓ /api/v2/agent/decisions 402 OK (accepts ${env.accepts.length} chain(s): ${env.accepts.map((a: any) => a.network).join(', ')})`);

  // 3. agent card
  const ac = await fetch(`${base}/.well-known/agent.json`);
  assert.equal(ac.status, 200, 'agent card 200');
  const card = await ac.json() as { skills: unknown[] };
  assert.ok(card.skills.length >= 5, `skills.length >= 5 (got ${card.skills.length})`);
  console.log(`✓ /.well-known/agent.json OK (${card.skills.length} skills)`);

  // 4. tools/list
  const tl = await fetch(`${base}/tools/list`);
  assert.equal(tl.status, 200, 'tools/list 200');
  console.log('✓ /tools/list OK');

  console.log('\nSMOKE PASSED');
}

main().catch((e) => { console.error('SMOKE FAILED:', e.message); process.exit(1); });
