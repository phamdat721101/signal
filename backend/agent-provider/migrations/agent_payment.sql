-- Agent Provider payment state. Designed for crash-safe outbox pattern.
--
-- payment_audit       — append-only ledger of every paid call
-- x402_settlements    — outbox of settle attempts; UNIQUE(payload_hash) is idempotency key
-- streaming_sessions  — sticky state for SSE streaming SKU (resume after crash)
--
-- Idempotent: safe to run multiple times.

CREATE TABLE IF NOT EXISTS payment_audit (
  id              BIGSERIAL PRIMARY KEY,
  ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  tool_name       TEXT NOT NULL,
  network         TEXT NOT NULL,
  payer           TEXT NOT NULL,
  amount          NUMERIC NOT NULL,
  reference_key   TEXT,
  payload_hash    TEXT NOT NULL,           -- ties row to settlement attempt
  status          TEXT NOT NULL,           -- 'verified' | 'settled' | 'failed'
  request_id      TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_payer_ts ON payment_audit (payer, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_ref      ON payment_audit (reference_key) WHERE reference_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_hash     ON payment_audit (payload_hash);

CREATE TABLE IF NOT EXISTS x402_settlements (
  payload_hash    TEXT PRIMARY KEY,        -- SHA256(payment header) — idempotency
  resource        TEXT NOT NULL,
  network         TEXT NOT NULL,
  payer           TEXT,
  amount          NUMERIC,
  status          TEXT NOT NULL,           -- 'pending' | 'settled' | 'failed' | 'expired'
  attempts        INT NOT NULL DEFAULT 0,
  next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_error      TEXT,
  tx_hash         TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  settled_at      TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_settle_pending ON x402_settlements (next_attempt_at) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS streaming_sessions (
  id                  TEXT PRIMARY KEY,
  payer               TEXT NOT NULL,
  tool_name           TEXT NOT NULL,
  network             TEXT NOT NULL,
  budget_remaining    NUMERIC NOT NULL,
  unsettled_amount    NUMERIC NOT NULL DEFAULT 0,
  last_settled_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  status              TEXT NOT NULL,       -- 'open' | 'closed' | 'expired'
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_stream_open ON streaming_sessions (status, last_settled_at);
