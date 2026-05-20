// Single shared PG pool. All DB access goes through here.
// Health check exposed for /api/health/deep.

import pg from 'pg';
import { env } from './env.js';

export const pool = new pg.Pool({
  connectionString: env.DATABASE_URL,
  max: 10,
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 5_000,
});

pool.on('error', (e) => {
  // eslint-disable-next-line no-console
  console.error({ err: e.message }, 'pg pool error');
});

export async function dbHealthy(): Promise<boolean> {
  try {
    await pool.query('SELECT 1');
    return true;
  } catch {
    return false;
  }
}
