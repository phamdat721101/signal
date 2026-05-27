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
 *   node scripts/sync-deployments.mjs --chain 1952   # explicit
 *   node scripts/sync-deployments.mjs --check        # CI lint mode: exits 1 on drift
 */
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

/** Each target = one .env file with a list of (envKey ← jsonKey) mappings. */
const TARGETS = [
  {
    path: "frontend/.env",
    keys: {
      VITE_XLAYER_CARD_NFT_ADDRESS:     "SignalCardNFT",
      VITE_XLAYER_HOOK_ADDRESS:         "SignalCardHook",
      VITE_XLAYER_ROUTER_ADDRESS:       "SignalCardRouter",
      VITE_XLAYER_POOL_MANAGER_ADDRESS: "PoolManager",
      VITE_XLAYER_OKB_ADDRESS:          "MockOKB",
      VITE_XLAYER_USDC_ADDRESS:         "MockUSDC",
    },
  },
  {
    path: "backend/.env",
    keys: {
      SIGNAL_CARD_NFT_ADDRESS:    "SignalCardNFT",
      SIGNAL_CARD_HOOK_ADDRESS:   "SignalCardHook",
      SIGNAL_CARD_ROUTER_ADDRESS: "SignalCardRouter",
      XLAYER_POOL_MANAGER_ADDRESS:"PoolManager",
      OKB_ADDRESS_XLAYER:         "MockOKB",
      USDC_ADDRESS_XLAYER:        "MockUSDC",
    },
  },
];

const isCheckMode = process.argv.includes("--check");
const chainArgIdx = process.argv.indexOf("--chain");
const chainArg    = chainArgIdx >= 0 ? parseInt(process.argv[chainArgIdx + 1], 10) : null;

function pickActiveDeployment() {
  const dir = join(ROOT, "contracts/deployments");
  if (!existsSync(dir)) return null;
  const jsons = readdirSync(dir)
    .filter(f => /^\d+\.json$/.test(f))
    .map(f => ({ chainId: parseInt(f, 10), path: join(dir, f) }));
  if (jsons.length === 0) return null;
  if (chainArg) return jsons.find(j => j.chainId === chainArg) || null;
  if (jsons.length === 1) return jsons[0];
  console.error(`Multiple chains found: ${jsons.map(j => j.chainId).join(", ")}. Pass --chain <id>.`);
  process.exit(1);
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
  const active = pickActiveDeployment();
  if (!active) {
    const msg = "No deployments JSON found. Deploy first via 04_DeployRealV4.s.sol.";
    if (isCheckMode) { console.log(msg); process.exit(0); }
    console.error(msg); process.exit(1);
  }

  const data = JSON.parse(readFileSync(active.path, "utf8"));
  console.log(`Active chain: ${active.chainId} (${active.path.split("/").slice(-2).join("/")})`);

  let anyDrift = false;
  for (const target of TARGETS) {
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

  if (isCheckMode && anyDrift) {
    console.error("\nDrift detected. Run `node scripts/sync-deployments.mjs` to fix.");
    process.exit(1);
  }
}

main();
