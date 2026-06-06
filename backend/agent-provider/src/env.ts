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
