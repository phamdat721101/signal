/**
 * Single source of truth for /agent prompt bundles + the rail registry.
 *
 * A "rail" = (chainId → API base + token + payment protocol kind). Adding a
 * supported chain is one row in `RAILS`. All four UI consumers (Agent page,
 * BundleCard, PreflightStrip, TryItRunner) read from this registry, so they
 * can never drift out of sync — and the page Just Works on any rail the
 * connected wallet is currently on.
 *
 * SOLID:
 *   - Single Responsibility — this module owns the rail registry + bundle
 *     metadata + pure rendering helpers (URL, prompt). No React, no I/O.
 *   - Open/Closed — adding a rail is a row in `RAILS`. Adding a bundle is
 *     a row in `BUNDLES`. Neither edits the other.
 *   - Dependency Inversion — UI consumes a `RailConfig` interface, not
 *     concrete chain values.
 */
import { config } from '../../config';

// ─── Bundle metadata (chain-agnostic) ─────────────────────────────────────

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
  /** Canonical USD price string (e.g. "$0.001") — must mirror backend route prices. */
  priceUsd: string;
  /** Path under the rail's `/api/v2/agent/` — e.g. 'decisions', 'prices'. */
  endpoint: string;
  /** Variables substituted into both the URL and the copyable prompt. */
  vars: PromptVar[];
  /** Plain-English instruction appended to the prompt template. */
  task: string;
}

export const BUNDLES: Bundle[] = [
  {
    id: 'decisions',
    title: 'Alpha Decisions',
    tagline: 'APE/FADE verdicts with confidence + per-token track record.',
    persona: 'analyst',
    priceUsd: '$0.001',
    endpoint: 'decisions',
    vars: [{ key: 'LIMIT', label: 'Limit', default: '5', placeholder: '1-50' }],
    task: 'summarize the top APE/FADE verdicts.',
  },
  {
    id: 'prices',
    title: 'Aggregated Prices',
    tagline: 'Real-time spot prices fused from CoinGecko + DexScreener.',
    persona: 'oracle',
    priceUsd: '$0.001',
    endpoint: 'prices',
    vars: [{ key: 'SYMBOLS', label: 'Symbols', default: 'BTC,ETH,SOL', placeholder: 'CSV' }],
    task: 'report the prices with sources.',
  },
  {
    id: 'pools',
    title: 'LP Pool Advisory',
    tagline: 'Multi-chain DeFi pools ranked by APY, TVL, and IL risk.',
    persona: 'analyst',
    priceUsd: '$0.005',
    endpoint: 'pools',
    vars: [{ key: 'LIMIT', label: 'Limit', default: '10' }],
    task: 'recommend the best risk-adjusted pool.',
  },
  {
    id: 'track-record',
    title: 'Track Record',
    tagline: 'On-chain resolved prediction accuracy, per-token.',
    persona: 'forensic',
    priceUsd: '$0.01',
    endpoint: 'track-record',
    vars: [],
    task: 'report overall accuracy + the three most accurate tokens.',
  },
  {
    id: 'context',
    title: 'Macro Context',
    tagline: 'ETF flows, sector rotation, and AI oracle market mood.',
    persona: 'oracle',
    priceUsd: '$0.01',
    endpoint: 'context',
    vars: [],
    task: 'tell me the current macro mood + biggest ETF flow.',
  },
];

// ─── Rail registry ────────────────────────────────────────────────────────

/**
 * Two payment protocols are supported per rail:
 *   • 'eip3009' — USDC transferWithAuthorization (Arbitrum Sepolia).
 *     Buyer signs typed data, submits authorization tx, server reads
 *     the resulting Transfer log for verification.
 *   • 'erc20-transfer' — buyer broadcasts a plain ERC-20 transfer to
 *     payTo (GOAT testnet, since USDC is not issued there). Server
 *     verifies the receipt.
 *
 * Both rails advertise the same `payment-required` envelope and accept
 * the same `X-Payment-Tx: <hash>` retry header — only the on-chain
 * payment step differs.
 */
export type RailKind = 'eip3009' | 'erc20-transfer';

export interface RailToken {
  address: `0x${string}`;
  symbol: string;
  decimals: number;
  /** EIP-712 domain — only required when `kind: 'eip3009'`. */
  domain?: { name: string; version: string };
}

export interface RailConfig {
  chainId: number;
  /** Display name (e.g. "Arbitrum Sepolia", "GOAT Testnet"). */
  name: string;
  /** n-payment SDK chain key — used in copy-paste prompts. */
  nPaymentKey: string;
  /** Base URL up to and including the rail prefix (e.g. ".../goat-api"). */
  apiBase: string;
  token: RailToken;
  kind: RailKind;
  /** Native gas faucet (ETH on Arb, BTC on GOAT). */
  gasFaucetUrl: string;
  /** Faucet for the payment token, if separate (USDC on Arb). null = same as gas. */
  tokenFaucetUrl: string | null;
  /** Native gas symbol shown in error hints. */
  gasSymbol: string;
  /**
   * Minimum native-gas balance (wei) we require before submitting the on-chain
   * payment. Sized so it's both
   *   (a) above a realistic ERC-20 transfer cost on the chain, and
   *   (b) below what the public testnet faucet typically hands out
   * — otherwise UX dies at preflight. ETH and BTC are not interchangeable
   * here: on GOAT testnet 1 wei is BTC-denominated, so the same `5e13`
   * literal that worked for ETH on Arb (~$0.20) was ~$3.25 on GOAT —
   * above the faucet drop of ~0.00001 BTC.
   */
  minGasWei: bigint;
}

const ARB_BASE = config.arbitrumSepolia.agentApiUrl.replace(/\/$/, '');
// All rails share the same agent-API base URL — the chain that settled the
// payment is signalled to the server via the `x-payment-network` retry header
// (set by TryItRunner). One URL, one paywall, two rails advertised in 402.
const GOAT_BASE = ARB_BASE;

export const RAILS: Record<number, RailConfig> = {
  [config.arbitrumSepolia.chainId]: {
    chainId: config.arbitrumSepolia.chainId,
    name: 'Arbitrum Sepolia',
    nPaymentKey: 'arbitrum-sepolia',
    apiBase: ARB_BASE,
    token: {
      address: config.arbitrumSepolia.usdcAddress,
      symbol: 'USDC',
      decimals: 6,
      domain: { name: 'USD Coin', version: '2' },
    },
    kind: 'eip3009',
    gasFaucetUrl: config.arbitrumSepolia.faucetUrl,
    tokenFaucetUrl: config.arbitrumSepolia.usdcFaucetUrl,
    gasSymbol: 'ETH',
    // ~0.00005 ETH (≈ $0.20). transferWithAuthorization is ~50k gas;
    // typical Alchemy faucet drop is 0.001 ETH = 1e15 wei — plenty of headroom.
    minGasWei: 50_000_000_000_000n,
  },
  [config.goatTestnet.chainId]: {
    chainId: config.goatTestnet.chainId,
    name: 'GOAT Testnet',
    nPaymentKey: 'goat-testnet',
    apiBase: GOAT_BASE,
    token: {
      address: config.goatTestnet.tokenAddress,
      symbol: config.goatTestnet.tokenSymbol,
      decimals: 18,
    },
    kind: 'erc20-transfer',
    gasFaucetUrl: config.goatTestnet.faucetUrl,
    tokenFaucetUrl: null, // gas + payment token both = wrapped BTC; one faucet covers both
    gasSymbol: 'BTC',
    // ~1e10 wei = 1e-8 BTC. ERC-20 transfer is ~50k gas × 0.1 gwei = 5e9 wei
    // actual cost; 2× safety. Faucet drop ~0.00001 BTC = 1e13 wei → 1000× headroom.
    minGasWei: 10_000_000_000n,
  },
};

export const SUPPORTED_RAIL_IDS = Object.keys(RAILS).map(Number);

export function getRail(chainId: number | undefined): RailConfig | undefined {
  return chainId === undefined ? undefined : RAILS[chainId];
}

// ─── Pure rendering helpers ───────────────────────────────────────────────

/** Substitute {{KEY}} → value from a vars dict. */
export function fillVars(template: string, values: Record<string, string>): string {
  return template.replace(/\{\{(\w+)\}\}/g, (_, k) => values[k] ?? `{{${k}}}`);
}

/** Build the full endpoint URL for a (rail, bundle, values) triple. */
export function endpointUrl(
  rail: RailConfig, bundle: Bundle, values: Record<string, string>,
): string {
  const params = new URLSearchParams();
  for (const v of bundle.vars) {
    const val = values[v.key] ?? v.default;
    if (val) params.set(v.key.toLowerCase(), val);
  }
  const qs = params.toString();
  return `${rail.apiBase}/api/v2/agent/${bundle.endpoint}${qs ? `?${qs}` : ''}`;
}

/** Compose the copyable LLM prompt for a (rail, bundle, values) triple. */
export function renderPrompt(
  rail: RailConfig, bundle: Bundle, values: Record<string, string>,
): string {
  const url = endpointUrl(rail, fillBundleVars(bundle, values), values);
  // For non-USD-stable rails (e.g. WGBTC), surface the token in the prompt
  // so the LLM/SDK doesn't try to interpret USD literally.
  const priceLabel = rail.token.symbol === 'USDC'
    ? `${bundle.priceUsd.replace('$', '')} USDC`
    : `${bundle.priceUsd} (in ${rail.token.symbol})`;
  return `Use n-payment on chain ${rail.nPaymentKey} to call ${url}, pay ${priceLabel}, and ${bundle.task}`;
}

/** Resolve {{VAR}}s inside a Bundle's endpoint slug (currently a no-op).
 *  Helper kept so the call signature in `renderPrompt` reads cleanly. */
function fillBundleVars(b: Bundle, _values: Record<string, string>): Bundle {
  return b;
}
