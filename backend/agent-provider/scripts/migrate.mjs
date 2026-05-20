#!/usr/bin/env node
// Run the SQL migration. Idempotent.
//   node scripts/migrate.mjs
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import pg from 'pg';
import 'dotenv/config';

const here = dirname(fileURLToPath(import.meta.url));
const sql = await readFile(resolve(here, '../migrations/agent_payment.sql'), 'utf8');
const url = process.env.DATABASE_URL;
if (!url) { console.error('DATABASE_URL not set'); process.exit(1); }

const client = new pg.Client({ connectionString: url });
await client.connect();
try {
  await client.query(sql);
  console.log('migration applied');
} finally {
  await client.end();
}
