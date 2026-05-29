/**
 * Single source of truth for /agent prompt bundles.
 *
 * Each bundle maps 1:1 to a paid endpoint on agent-provider. Adding a tool =
 * one row here. Cards (Copy) and the Try-It runner (Run) both consume this
 * array, so they can never drift out of sync.
 */
import { config } from '../../config';

export interface PromptVar {
  key: string;
  label: string;
  default: string;
  placeholder?: string;
}

export interface Bundle {
  id: string;
  title: string;
  tagline: string;
  persona: 'analyst' | 'oracle' | 'forensic';
  /** microUSDC integer — must mirror agent-provider/src/tools.ts. */
  priceUsdc: bigint;
  /** Path under agent-provider — e.g. 'decisions', 'prices'. */
  endpoint: string;
  /** Variables substituted into both the URL and the copyable prompt. */
  vars: PromptVar[];
  /** One-liner the user pastes into Claude/ChatGPT. {{VAR}} placeholders. */
  prompt: string;
}

const BASE = config.morphHoodi.agentApiUrl.replace(/\/$/, '');

export const BUNDLES: Bundle[] = [
  {
    id: 'decisions',
    title: 'Alpha Decisions',
    tagline: 'APE/FADE verdicts with confidence + per-token track record.',
    persona: 'analyst',
    priceUsdc: 1000n,
    endpoint: 'decisions',
    vars: [{ key: 'LIMIT', label: 'Limit', default: '5', placeholder: '1-50' }],
    prompt: `Use n-payment on chain morph-hoodi-testnet to call ${BASE}/api/v2/agent/decisions?limit={{LIMIT}}, pay 0.001 USDC, and summarize the top APE/FADE verdicts.`,
  },
  {
    id: 'prices',
    title: 'Aggregated Prices',
    tagline: 'Real-time spot prices fused from CoinGecko + DexScreener.',
    persona: 'oracle',
    priceUsdc: 1000n,
    endpoint: 'prices',
    vars: [{ key: 'SYMBOLS', label: 'Symbols', default: 'BTC,ETH,SOL', placeholder: 'CSV' }],
    prompt: `Use n-payment on chain morph-hoodi-testnet to call ${BASE}/api/v2/agent/prices?symbols={{SYMBOLS}}, pay 0.001 USDC, and report the prices with sources.`,
  },
  {
    id: 'pools',
    title: 'LP Pool Advisory',
    tagline: 'Multi-chain DeFi pools ranked by APY, TVL, and IL risk.',
    persona: 'analyst',
    priceUsdc: 5000n,
    endpoint: 'pools',
    vars: [{ key: 'LIMIT', label: 'Limit', default: '10' }],
    prompt: `Use n-payment on chain morph-hoodi-testnet to call ${BASE}/api/v2/agent/pools?limit={{LIMIT}}, pay 0.005 USDC, and recommend the best risk-adjusted pool.`,
  },
  {
    id: 'track-record',
    title: 'Track Record',
    tagline: 'On-chain resolved prediction accuracy, per-token.',
    persona: 'forensic',
    priceUsdc: 10000n,
    endpoint: 'track-record',
    vars: [],
    prompt: `Use n-payment on chain morph-hoodi-testnet to call ${BASE}/api/v2/agent/track-record, pay 0.01 USDC, and report overall accuracy + the three most accurate tokens.`,
  },
  {
    id: 'context',
    title: 'Macro Context',
    tagline: 'ETF flows, sector rotation, and AI oracle market mood.',
    persona: 'oracle',
    priceUsdc: 10000n,
    endpoint: 'context',
    vars: [],
    prompt: `Use n-payment on chain morph-hoodi-testnet to call ${BASE}/api/v2/agent/context, pay 0.01 USDC, and tell me the current macro mood + biggest ETF flow.`,
  },
];

/** Substitute {{KEY}} → value from a vars dict. */
export function fillVars(template: string, values: Record<string, string>): string {
  return template.replace(/\{\{(\w+)\}\}/g, (_, k) => values[k] ?? `{{${k}}}`);
}

/** Build the full endpoint URL with query params from filled vars. */
export function endpointUrl(b: Bundle, values: Record<string, string>): string {
  const params = new URLSearchParams();
  for (const v of b.vars) {
    const val = values[v.key] ?? v.default;
    if (val) params.set(v.key.toLowerCase(), val);
  }
  const qs = params.toString();
  return `${BASE}/api/v2/agent/${b.endpoint}${qs ? `?${qs}` : ''}`;
}

/** Format microUSDC as a short price label. */
export function formatPrice(micro: bigint): string {
  const usd = Number(micro) / 1_000_000;
  return `$${usd.toFixed(usd < 0.01 ? 4 : 3)}`;
}
