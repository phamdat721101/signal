/**
 * E2E buyer demo — pays for /api/v2/agent/decisions on Morph Hoodi (chain 2910)
 * via a hand-rolled EIP-3009 buyer.
 *
 * Why hand-rolled: n-payment v0.18's MorphX402Adapter hardcodes the EIP-712
 * domain name "USD Coin" and provides no tokenName override, but Hoodi USDC
 * exposes name="USDC" on-chain. We sign typed data with the correct domain
 * via n-payment's exported buildTransferWithAuthorizationTypedData helper.
 * Same approach is reused on the frontend (Task 10).
 *
 * Run:
 *   PRIVATE_KEY=0x... npm run e2e
 */
import {
  CHAINS,
  buildTransferWithAuthorizationTypedData,
  encodeAuthorizationPayload,
  randomEip3009Nonce,
} from 'n-payment';
import { config as loadEnv } from 'dotenv';
import { privateKeyToAccount } from 'viem/accounts';

loadEnv();
loadEnv({ path: '../.env' });

const BASE = (process.env.AGENT_API_URL ?? 'http://127.0.0.1:8002').replace(/\/$/, '');
const FACILITATOR = process.env.FACILITATOR_URL ?? 'http://127.0.0.1:4040/x402';
const ENDPOINT = `${BASE}/api/v2/agent/decisions?limit=3`;

const PK = (process.env.MORPH_BUYER_PRIVATE_KEY ?? process.env.PRIVATE_KEY ?? '').trim();
if (!/^0x[0-9a-fA-F]{64}$/.test(PK)) {
  console.error('ERROR: set MORPH_BUYER_PRIVATE_KEY (or PRIVATE_KEY) in env');
  process.exit(1);
}
const buyer = privateKeyToAccount(PK as `0x${string}`);
const chain = CHAINS['morph-hoodi-testnet']!;

console.log('buyer:  ', buyer.address);
console.log('GET    ', ENDPOINT);

// 1. Fetch — expect 402 with `payment-required` envelope.
const t0 = Date.now();
const res402 = await fetch(ENDPOINT);
if (res402.status !== 402) {
  console.error(`expected 402, got ${res402.status}`);
  process.exit(2);
}
const envelopeB64 = res402.headers.get('payment-required') ?? res402.headers.get('x-payment-required');
if (!envelopeB64) {
  console.error('no payment-required header');
  process.exit(3);
}
const envelope = JSON.parse(Buffer.from(envelopeB64, 'base64').toString('utf8'));
const accept = envelope.accepts?.[0];
if (!accept || accept.network !== chain.caip2 || accept.scheme !== 'eip3009') {
  console.error('unexpected envelope', envelope);
  process.exit(4);
}
console.log(`402 → pay ${accept.maxAmountRequired} USDC base-units to ${accept.payTo}`);

// 2. Build EIP-3009 authorization + sign with the correct domain.
const now = Math.floor(Date.now() / 1000);
const authorization = {
  from: buyer.address as `0x${string}`,
  to: accept.payTo as `0x${string}`,
  value: BigInt(accept.maxAmountRequired),
  validAfter: 0n,
  validBefore: BigInt(now + 300),
  nonce: randomEip3009Nonce(),
};
const td = buildTransferWithAuthorizationTypedData({
  verifyingContract: accept.asset as `0x${string}`,
  chainId: chain.chainId,
  tokenName: 'USDC',     // pinned to match on-chain Hoodi USDC contract
  tokenVersion: '2',
  authorization,
});
const signature = await buyer.signTypedData({
  domain: td.domain,
  types: td.types,
  primaryType: 'TransferWithAuthorization',
  message: td.message as never,
});

// 3. Submit to facilitator's /v2/settle — relays the on-chain tx via sponsor.
const settleRes = await fetch(`${FACILITATOR}/v2/settle`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    x402Version: 2,
    paymentPayload: {
      x402Version: 2,
      scheme: 'eip3009',
      network: chain.caip2,
      authorization: encodeAuthorizationPayload(authorization),
      signature,
    },
    paymentRequirements: accept,
  }),
});
const settleJson: any = await settleRes.json();
if (!settleRes.ok || !settleJson.success) {
  console.error('settle failed:', settleRes.status, JSON.stringify(settleJson, null, 2));
  process.exit(5);
}
console.log(`settled tx ${settleJson.transaction} (${Date.now() - t0}ms)`);

// 4. Retry original URL with proof headers — createPaywall lets it through.
const r = await fetch(ENDPOINT, {
  headers: {
    'x-payment-tx': settleJson.transaction,
    'x-payment-network': chain.caip2,
    'x-payment-payer': buyer.address,
  },
});
console.log('status:', r.status, `(${Date.now() - t0}ms total)`);
if (!r.ok) {
  console.error('body:', await r.text());
  process.exit(6);
}
console.log('\n— decisions —');
console.log(JSON.stringify(await r.json(), null, 2));
