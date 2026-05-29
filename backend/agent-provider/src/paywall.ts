// Single-rail paywall — Morph Hoodi only, EIP-3009 sponsored payments.
//
// Replaces the previous multi-rail hand-rolled payment_gate.ts. n-payment
// v0.18's createPaywall handles the 402 envelope, facilitator verify, and
// trustedFacilitators allowlist; we just declare the routes table.
//
// SOLID:
//   - Single source of truth for paid endpoints: tools.ts → routes table.
//     Add a tool = one row in tools.ts. Zero edits here.
//   - Single responsibility for this file: build the routes table and hand
//     it to createPaywall. No HTTP, no facilitator, no audit DB.

import { createPaywall, type PaywallConfig } from 'n-payment';
import { env } from './env.js';
import { TOOLS } from './tools.js';

const MORPH_HOODI = {
  network: 'eip155:2910',
  asset: '0x7433b41C6c5e1d58D4Da99483609520255ab661B', // Hoodi USDC
  scheme: 'eip3009' as const,                          // sponsored, zero-ETH for buyers
};

const config: PaywallConfig = {
  facilitator: env.FACILITATOR_URL,
  routes: Object.fromEntries(
    TOOLS.map((t) => [
      `GET /api/v2/agent/${t.name}`,
      {
        // x402 spec: maxAmountRequired is the integer microUSDC (USDC has 6
        // decimals). n-payment's MorphX402Adapter does BigInt(price) directly,
        // so we emit the bigint string, not the dollar-prefixed form.
        price: t.priceMicroUsdc.toString(),
        description: t.description,
        morph: { payTo: env.PAY_TO_ADDRESS, ...MORPH_HOODI },
      },
    ]),
  ),
};

export const paywall = createPaywall(config);
export const SUPPORTED_NETWORK = MORPH_HOODI.network;
export const SUPPORTED_ASSET = MORPH_HOODI.asset;
