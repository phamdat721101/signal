// Single source of truth for runtime config — Morph Hoodi only.
// Boots fail-fast on missing required keys.

import 'dotenv/config';
import { z } from 'zod';

const Schema = z.object({
  PORT: z.coerce.number().int().positive().default(8002),
  NODE_ENV: z.enum(['development', 'production', 'test']).default('production'),
  LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).default('info'),

  PUBLIC_BASE_URL: z.string().url().default('https://ai.overguild.com/agent-api'),
  PYTHON_INTERNAL_URL: z.string().url().default('http://127.0.0.1:8001'),

  /** Local Morph Hoodi facilitator (Task 2). */
  FACILITATOR_URL: z.string().url().default('http://127.0.0.1:4040/x402'),

  /** Receiver of paid USDC on Morph Hoodi. */
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
export const SUPPORTED_CHAINS = ['morph-hoodi-testnet'] as const;
