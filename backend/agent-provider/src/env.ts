// Single source of truth for runtime configuration.
// Boots fail-fast on missing required keys; warns on optional ones.

import 'dotenv/config';
import { z } from 'zod';

const Schema = z.object({
  PORT: z.coerce.number().int().positive().default(8002),
  NODE_ENV: z.enum(['development', 'production', 'test']).default('production'),
  LOG_LEVEL: z.enum(['debug', 'info', 'warn', 'error']).default('info'),

  PUBLIC_BASE_URL: z.string().url().default('https://ai.overguild.com/agent-api'),
  PYTHON_INTERNAL_URL: z.string().url().default('http://127.0.0.1:8001'),

  DATABASE_URL: z.string().url(),

  BASE_RECEIVER: z.string().regex(/^0x[a-fA-F0-9]{40}$/, 'BASE_RECEIVER must be 0x-prefixed EVM address'),
  STELLAR_RECEIVER: z.string().regex(/^G[A-Z2-7]{55}$/).optional(),
  TEMPO_RECEIVER: z.string().regex(/^0x[a-fA-F0-9]{40}$/).optional(),

  CDP_API_KEY_ID: z.string().default(''),
  CDP_API_KEY_SECRET: z.string().default(''),
  OZ_API_KEY: z.string().optional(),
  STELLAR_SECRET: z.string().optional(),
});

export type Env = z.infer<typeof Schema>;

const parsed = Schema.safeParse(process.env);
if (!parsed.success) {
  // eslint-disable-next-line no-console
  console.error('FATAL: invalid environment\n', parsed.error.flatten().fieldErrors);
  process.exit(1);
}
export const env: Env = parsed.data;

export const supportedChains = (() => {
  const chains: Array<'base-mainnet' | 'stellar-mainnet' | 'tempo-mainnet'> = ['base-mainnet'];
  if (env.STELLAR_RECEIVER && env.OZ_API_KEY) chains.push('stellar-mainnet');
  if (env.TEMPO_RECEIVER) chains.push('tempo-mainnet');
  return chains;
})();
