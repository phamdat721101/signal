#!/usr/bin/env node
/**
 * sync-deployments.mjs — single source of truth for X Layer addresses.
 *
 * Reads:  contracts/deployments/<chainId>.json   (written by 04_DeployRealV4.s.sol)
 * Writes: frontend/.env, backend/.env            (only the canonical FE/BE keys; preserves all others)
 *
 * Active-chain semantics:
 *   • Default: if one JSON exists, use it.
 *   • Multiple JSONs: pass `--chain <id>` to pick which one populates the canonical env keys.
 *
 * SOLID:
 *   - SRP: one job, deploy-JSON → canonical env vars.
 *   - OCP: target keys live in TARGETS array — add a key by adding a row.
 *   - Idempotent: re-running produces no diff.
 *   - Zero deps.
 *
 * Usage:
 *   node scripts/sync-deployments.mjs                # auto-pick if single chain
 *   node scripts/sync-deployments.mjs --chain 50312  # explicit
 *   node scripts/sync-deployments.mjs --check        # CI lint mode: exits 1 on drift
 */
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Each target = one .env file with a list of (envKey ← jsonKey) mappings, per chain. */
const TARGETS_BY_CHAIN = {
  50312: [
    { path: "frontend/.env", keys: {
      VITE_SOMNIA_SIGNAL_REGISTRY_ADDRESS: "SignalRegistry", VITE_SOMNIA_CONVICTION_ENGINE_ADDRESS: "ConvictionEngine",
      VITE_SOMNIA_ORACLE_ADAPTER_ADDRESS: "SomniaOracleAdapter", VITE_SOMNIA_SIGNAL_AGENT_ADDRESS: "SomniaSignalAgent",
      VITE_SOMNIA_SESSION_VAULT_ADDRESS: "SessionVault", VITE_SOMNIA_MOCK_STT_ADDRESS: "MockSTT",
      VITE_SOMNIA_CARD_EXECUTOR_ADDRESS: "SomniaCardExecutor", VITE_SOMNIA_AGENT_MARKET_ADDRESS: "SomniaAgentMarket",
    }},
    { path: "backend/.env", keys: {
      SOMNIA_SIGNAL_REGISTRY_ADDRESS: "SignalRegistry", SOMNIA_CONVICTION_ENGINE_ADDRESS: "ConvictionEngine",
      SOMNIA_ORACLE_ADAPTER_ADDRESS: "SomniaOracleAdapter", SOMNIA_SIGNAL_AGENT_ADDRESS: "SomniaSignalAgent",
      SOMNIA_SESSION_VAULT_ADDRESS: "SessionVault", SOMNIA_MOCK_STT_ADDRESS: "MockSTT",
      SOMNIA_CARD_EXECUTOR_ADDRESS: "SomniaCardExecutor", SOMNIA_AGENT_MARKET_ADDRESS: "SomniaAgentMarket",
    }},
  ],
};

const isCheckMode = process.argv.includes("--check");
const chainArgIdx = process.argv.indexOf("--chain");
const chainArg    = chainArgIdx >= 0 ? parseInt(process.argv[chainArgIdx + 1], 10) : null;

function pickActiveDeployments() {
  const dir = join(ROOT, "contracts/deployments");
  if (!existsSync(dir)) return [];
  const jsons = readdirSync(dir)
    .filter(f => /^\d+\.json$/.test(f))
    .map(f => ({ chainId: parseInt(f, 10), path: join(dir, f) }));
  if (chainArg) return jsons.filter(j => j.chainId === chainArg);
  return jsons;
}

/** Replace existing matching lines; append any missing keys with a single header block. */
function mergeEnv(envText, kvs) {
  const lines = envText.split("\n");
  const seen  = new Set();
  let drift   = false;

  const out = lines.map(line => {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (!m) return line;
    const [, key, val] = m;
    if (kvs[key] !== undefined) {
      seen.add(key);
      const want = kvs[key];
      if (val.trim() !== want) drift = true;
      return `${key}=${want}`;
    }
    return line;
  });

  const missing = Object.keys(kvs).filter(k => !seen.has(k));
  if (missing.length) {
    drift = true;
    if (out.at(-1) !== "") out.push("");
    out.push("# Auto-synced by scripts/sync-deployments.mjs — single source of truth");
    for (const k of missing) out.push(`${k}=${kvs[k]}`);
  }
  return { text: out.join("\n"), drift };
}

function main() {
  const deployments = pickActiveDeployments();
  if (deployments.length === 0) {
    const msg = "No deployments JSON found. Deploy first.";
    if (isCheckMode) { console.log(msg); process.exit(0); }
    console.error(msg); process.exit(1);
  }

  let anyDrift = false;
  for (const active of deployments) {
    const data = JSON.parse(readFileSync(active.path, "utf8"));
    console.log(`Chain ${active.chainId} (${active.path.split("/").slice(-2).join("/")})`);

    const targets = TARGETS_BY_CHAIN[active.chainId];
    if (!targets) {
      console.warn(`  skip (no key mappings for chain ${active.chainId})`);
      continue;
    }
    for (const target of targets) {
      const full = join(ROOT, target.path);
      if (!existsSync(full)) {
        console.warn(`  skip (not found): ${target.path}`);
        continue;
      }
      const kvs = Object.fromEntries(
        Object.entries(target.keys)
          .filter(([, jsonKey]) => data[jsonKey])
          .map(([envKey, jsonKey]) => [envKey, data[jsonKey]])
      );
      const before = readFileSync(full, "utf8");
      const { text, drift } = mergeEnv(before, kvs);
      anyDrift = anyDrift || drift;
      if (isCheckMode) {
        console.log(`  ${drift ? "DRIFT" : "ok"}: ${target.path}`);
      } else if (drift) {
        writeFileSync(full, text, "utf8");
        console.log(`  wrote: ${target.path}`);
      } else {
        console.log(`  ok:    ${target.path}`);
      }
    }
  }

  if (isCheckMode && anyDrift) {
    console.error("\nDrift detected. Run `node scripts/sync-deployments.mjs` to fix.");
    process.exit(1);
  }
}

main();
