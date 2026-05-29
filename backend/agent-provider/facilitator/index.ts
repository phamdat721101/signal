// Standalone Morph Hoodi facilitator on :4040.
//
// Single responsibility: run n-payment v0.18's createMorphHoodiFacilitator
// handler (verify + settle for sponsored EIP-3009 USDC transfers) on a
// dedicated process bound to localhost. Sponsor key isolation is the
// motivation — agent-provider only needs the facilitator URL, not the key.
//
// Sponsor key is read once at boot from MORPH_HOODI_SPONSOR_KEY (preferred)
// or PRIVATE_KEY (fallback to the canonical key in backend/.env). Bind to
// 127.0.0.1 only — agent-provider is the sole client.

import { config as loadEnv } from 'dotenv';
import express from 'express';
import { CHAINS, createMorphHoodiFacilitator } from 'n-payment';
import { createPublicClient, createWalletClient, defineChain, erc20Abi, formatEther, formatUnits, http } from 'viem';
import { privateKeyToAccount } from 'viem/accounts';

// Load env from agent-provider/.env first, then backend/.env (PRIVATE_KEY canonical).
loadEnv();
loadEnv({ path: '../.env' });

const SPONSOR_KEY = (process.env.MORPH_HOODI_SPONSOR_KEY || process.env.PRIVATE_KEY || '').trim();
if (!/^0x[0-9a-fA-F]{64}$/.test(SPONSOR_KEY)) {
  console.error('FATAL: MORPH_HOODI_SPONSOR_KEY (or PRIVATE_KEY) must be a 0x-prefixed 32-byte hex string');
  process.exit(1);
}

const PORT = Number(process.env.FACILITATOR_PORT ?? 4040);
const HOST = process.env.FACILITATOR_HOST ?? '127.0.0.1';
// Default '/x402' matches local dev (buyer uses http://127.0.0.1:4040/x402).
// Behind a reverse proxy that already strips a path prefix (Caddy
// `handle_path /facilitator/*` on the VPS), set this to '' so /v2/{verify,
// settle,supported} are served directly.
const PATH_PREFIX = process.env.FACILITATOR_PATH_PREFIX ?? '/x402';

const chain = CHAINS['morph-hoodi-testnet']!;
const viemChain = defineChain({
  id: chain.chainId,
  name: chain.name,
  nativeCurrency: { name: 'ETH', symbol: 'ETH', decimals: 18 },
  rpcUrls: { default: { http: [process.env.MORPH_HOODI_RPC || chain.rpcUrl] } },
  blockExplorers: { default: { name: 'Morph Hoodi Explorer', url: 'https://explorer-hoodi.morph.network' } },
  testnet: true,
});

const sponsor = privateKeyToAccount(SPONSOR_KEY as `0x${string}`);
const publicClient = createPublicClient({ chain: viemChain, transport: http() });
const sponsorClient = createWalletClient({ account: sponsor, chain: viemChain, transport: http() });

const facilitator = createMorphHoodiFacilitator({
  usdcAddress: chain.tokens.USDC as `0x${string}`,
  // Hoodi USDC on-chain reports name="USDC" (verified via DOMAIN_SEPARATOR
  // probe). The SDK default is "USD Coin" which would cause a signature
  // mismatch on settle. Both buyer and facilitator must pin "USDC".
  tokenName: 'USDC',
  tokenVersion: '2',
  pathPrefix: PATH_PREFIX,
  publicClient: publicClient as never,
  sponsorClient: sponsorClient as never,
  sponsorAddress: sponsor.address,
});

const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '64kb' }));

// CORS — browser buyer (TryItRunner) calls /v2/settle directly, with a JSON
// body that triggers a preflight. Mirror the agent-provider's CORS shape so
// both services behave the same way to the same client.
app.use((req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', '*');
  res.setHeader('Access-Control-Expose-Headers', '*');
  if (req.method === 'OPTIONS') return res.status(204).end();
  next();
});

// Health endpoint — checked by agent-provider on boot and by ops dashboards.
// Reads sponsor's ETH + USDC balances on every call so a quick `curl /health`
// shows whether the relayer is funded enough to settle the next payment.
app.get('/health', async (_req, res) => {
  try {
    const [eth, usdc] = await Promise.all([
      publicClient.getBalance({ address: sponsor.address }),
      publicClient.readContract({ address: chain.tokens.USDC as `0x${string}`, abi: erc20Abi, functionName: 'balanceOf', args: [sponsor.address] }),
    ]);
    res.json({
      ok: true,
      service: 'morph-hoodi-facilitator',
      chain: chain.caip2,
      sponsor: sponsor.address,
      ethBalance: formatEther(eth),
      usdcBalance: formatUnits(usdc as bigint, 6),
      usdc: chain.tokens.USDC,
    });
  } catch (e: any) {
    res.status(503).json({ ok: false, error: e.message });
  }
});

// Mount the n-payment handler. It owns /x402/v2/{supported,verify,settle}.
//
// Workaround for n-payment v0.18 buyer↔facilitator shape mismatch:
// MorphX402Adapter.paySponsored sends `paymentPayload: { x402Version, scheme,
// network, payload: { authorization, signature } }` (nested) but the v0.18
// facilitator's runVerify reads `paymentPayload.authorization` (flat). Lift
// the nested payload to top-level before the handler sees it. Remove when
// n-payment publishes a fix that aligns both sides.
app.use((req, _res, next) => {
  if (req.method === 'POST' && /\/v2\/(verify|settle)$/.test(req.path)) {
    const pp = req.body?.paymentPayload;
    if (pp?.payload && !pp.authorization) {
      req.body.paymentPayload = { ...pp, ...pp.payload };
    }
  }
  next();
});

app.use(facilitator as any);

const server = app.listen(PORT, HOST, async () => {
  const eth = await publicClient.getBalance({ address: sponsor.address }).catch(() => 0n);
  const usdc = await publicClient.readContract({ address: chain.tokens.USDC as `0x${string}`, abi: erc20Abi, functionName: 'balanceOf', args: [sponsor.address] }).catch(() => 0n);
  console.log(`morph-hoodi-facilitator listening on http://${HOST}:${PORT}${PATH_PREFIX}`);
  console.log(`  sponsor:      ${sponsor.address}`);
  console.log(`  eth balance:  ${formatEther(eth as bigint)} ETH`);
  console.log(`  usdc balance: ${formatUnits(usdc as bigint, 6)} USDC`);
  console.log(`  rpc:          ${viemChain.rpcUrls.default.http[0]}`);
});

const shutdown = (sig: string) => {
  console.log(`shutdown ${sig}`);
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 5_000).unref();
};
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
