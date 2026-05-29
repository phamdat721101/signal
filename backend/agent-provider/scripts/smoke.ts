/**
 * Smoke test for the Morph Hoodi rail.
 *
 *   npm run smoke -- http://localhost:8002 http://localhost:4040
 *
 * Asserts:
 *  - facilitator /health returns 200 with sponsor + balances
 *  - agent-provider /api/health returns chains=['morph-hoodi-testnet']
 *  - GET /api/v2/agent/decisions returns 402 with eip155:2910 envelope
 *  - /.well-known/agent.json advertises Morph Hoodi only
 */
import { strict as assert } from 'node:assert';

const provider = process.argv[2] ?? 'http://127.0.0.1:8002';
const facilitator = process.argv[3] ?? 'http://127.0.0.1:4040';

async function main() {
  // facilitator
  const fh = await fetch(`${facilitator}/health`);
  assert.equal(fh.status, 200, 'facilitator /health 200');
  const fhJson = await fh.json() as any;
  assert.equal(fhJson.chain, 'eip155:2910', 'facilitator on eip155:2910');
  assert.match(fhJson.sponsor, /^0x[0-9a-fA-F]{40}$/, 'sponsor address');
  console.log(`✓ facilitator OK (sponsor ${fhJson.sponsor.slice(0, 10)}…, ${fhJson.ethBalance} ETH, ${fhJson.usdcBalance} USDC)`);

  // agent-provider /api/health
  const ph = await fetch(`${provider}/api/health`);
  assert.equal(ph.status, 200, 'agent-provider /api/health 200');
  const phJson = await ph.json() as any;
  assert.deepEqual(phJson.chains, ['morph-hoodi-testnet'], 'single-chain advertisement');
  console.log('✓ agent-provider /api/health OK');

  // 402 envelope
  const r = await fetch(`${provider}/api/v2/agent/decisions`);
  assert.equal(r.status, 402, `decisions 402 (got ${r.status})`);
  const required = r.headers.get('payment-required');
  assert.ok(required, 'payment-required header');
  const env = JSON.parse(Buffer.from(required, 'base64').toString('utf8'));
  const a = env.accepts?.[0];
  assert.equal(a?.scheme, 'eip3009', 'scheme=eip3009');
  assert.equal(a?.network, 'eip155:2910', 'network=eip155:2910');
  assert.equal(a?.asset?.toLowerCase(), '0x7433b41c6c5e1d58d4da99483609520255ab661b', 'Hoodi USDC asset');
  console.log(`✓ 402 envelope OK (price ${a.maxAmountRequired} microUSDC → ${a.payTo})`);

  // agent card
  const ac = await fetch(`${provider}/.well-known/agent.json`);
  assert.equal(ac.status, 200, 'agent card 200');
  const card = await ac.json() as any;
  assert.equal(card.network, 'eip155:2910', 'card advertises Morph Hoodi');
  assert.ok(card.skills?.length >= 5, `5+ skills (got ${card.skills?.length})`);
  console.log(`✓ /.well-known/agent.json OK (${card.skills.length} skills, network ${card.network})`);

  console.log('\nSMOKE PASSED');
}

main().catch((e) => { console.error('SMOKE FAILED:', e.message); process.exit(1); });
