/**
 * Morph Rails x402 demo buyer — pays for /morph-api/api/v2/agent/decisions
 * using USDC on Morph Hoodi testnet via the canonical x402-fetch SDK.
 *
 * Run:
 *   export MORPH_BUYER_PRIVATE_KEY=0x...   # funded with Hoodi test token
 *   export AGENT_API_URL=https://ai.overguild.com   # or http://localhost:8002
 *   npx tsx scripts/morph-demo-buyer.ts
 *
 * Prints the decisions JSON, the reference key, the on-chain tx hash, and
 * the explorer URL. Single responsibility: prove an end-to-end paid call
 * lands on the Morph rail and gets receipted.
 */
import { wrapFetchWithPayment, decodeXPaymentResponse } from "x402-fetch";
import { privateKeyToAccount } from "viem/accounts";

const PK = process.env.MORPH_BUYER_PRIVATE_KEY;
const BASE = (process.env.AGENT_API_URL ?? "http://localhost:8002").replace(/\/$/, "");
const ENDPOINT = `${BASE}/morph-api/api/v2/agent/decisions?limit=3`;

if (!PK || !PK.startsWith("0x")) {
  console.error("ERROR: set MORPH_BUYER_PRIVATE_KEY=0x... (funded on Morph Hoodi)");
  process.exit(1);
}

const account = privateKeyToAccount(PK as `0x${string}`);
console.log("buyer:", account.address);
console.log("GET   ", ENDPOINT);

const fetchWithPayment = wrapFetchWithPayment(fetch, account);

const t0 = Date.now();
const r = await fetchWithPayment(ENDPOINT);
const ms = Date.now() - t0;

console.log("status:", r.status, `(${ms}ms)`);
console.log("rail:  ", r.headers.get("x-payment-rail"));
console.log("refkey:", r.headers.get("x-morph-reference-key"));

const xpr = r.headers.get("x-payment-response");
if (xpr) {
  try {
    const receipt = decodeXPaymentResponse(xpr);
    console.log("tx:    ", receipt.transaction);
    console.log("net:   ", receipt.network);
    console.log("payer: ", receipt.payer);
  } catch (e) {
    console.warn("could not decode x-payment-response:", e);
  }
}

if (!r.ok) {
  console.error("body:", await r.text());
  process.exit(2);
}

const body = await r.json();
console.log("\n— decisions —");
console.log(JSON.stringify(body, null, 2));

// Reconcile by reference key — proves the Morph Reference Key flow end-to-end
const refKey = r.headers.get("x-morph-reference-key");
if (refKey) {
  const reconcileURL = `${BASE}/morph-api/reconcile?key=${refKey}`;
  console.log("\nGET   ", reconcileURL);
  // Settlement is fire-and-forget; give it a beat to land on-chain
  await new Promise((rs) => setTimeout(rs, 4000));
  const rec = await fetch(reconcileURL);
  console.log("status:", rec.status);
  console.log(JSON.stringify(await rec.json(), null, 2));
}
