// Single source of truth for runtime config — Arbitrum Sepolia x402 rail.
// Boots fail-fast on missing required keys.

import 'dotenv/config';
import { z } from 'zod';

const Schema = z.object({
  PORT: z.coerce.number().int().positive().default(8002),
  NODE_ENV: z.enum(['development', 'production', 'test']).default('production'),
  LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).default('info'),

  PUBLIC_BASE_URL: z.string().url().default('https://ai.overguild.com/agent-api'),
  PYTHON_INTERNAL_URL: z.string().url().default('http://127.0.0.1:8001'),

  /** Public x402 facilitator. Default is the canonical x402.org service for
   *  Arbitrum Sepolia (no auth, no sponsor, buyer-pays-gas).
   *  Override for self-hosted facilitators. */
  FACILITATOR_URL: z.string().url().default('https://x402.org/facilitator'),

  /** Receiver of paid USDC on Arbitrum Sepolia. */
  PAY_TO_ADDRESS: z.string().regex(/^0x[a-fA-F0-9]{40}$/, 'PAY_TO_ADDRESS must be 0x… EVM address'),

  // ── GOAT testnet rail (additive, optional) ──────────────────────────
  // When ENABLED, the paywall advertises a 2nd `accepts` entry on the
  // 402 challenge (chain 48816, default token = WGBTC since USDC is
  // not issued on testnet3). Buyer picks the rail by paying on the
  // chain of their choice; on retry, `x-payment-network` selects the
  // rail for verification. Falls back to PAY_TO_ADDRESS if not set.
  GOAT_X402_ENABLED: z.coerce.boolean().default(false),
  // Empty string in .env is treated as "not set" so PAY_TO_ADDRESS fallback wins.
  GOAT_X402_PAY_TO: z.preprocess(
    (v) => (v === '' ? undefined : v),
    z.string().regex(/^0x[a-fA-F0-9]{40}$/).optional(),
  ),
  GOAT_X402_RPC_URL: z.string().url().default('https://rpc.testnet3.goat.network'),
  GOAT_X402_TOKEN_ADDRESS: z.string().regex(/^0x[a-fA-F0-9]{40}$/)
    .default('0xbC10000000000000000000000000000000000000'),
  GOAT_X402_TOKEN_SYMBOL: z.string().default('WGBTC'),
  GOAT_X402_TOKEN_USD_PRICE: z.coerce.number().positive().default(65000),
});

export type Env = z.infer<typeof Schema>;

const parsed = Schema.safeParse(process.env);
if (!parsed.success) {
  // eslint-disable-next-line no-console
  console.error('FATAL: invalid environment\n', parsed.error.flatten().fieldErrors);
  process.exit(1);
}
export const env: Env = parsed.data;

/** Single supported chain — exported for discovery surfaces in server.ts. */
export const SUPPORTED_CHAINS = ['arbitrum-sepolia'] as const;
