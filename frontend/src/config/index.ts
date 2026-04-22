import { defineChain } from 'viem';

const network = import.meta.env.VITE_NETWORK || 'local';

const localChain = defineChain({
  id: 4354150043272442,
  name: 'Minitia Local',
  nativeCurrency: { name: 'INIT', symbol: 'INIT', decimals: 18 },
  rpcUrls: {
    default: { http: [import.meta.env.VITE_LOCAL_JSON_RPC_URL || 'http://localhost:8545'] },
  },
});

const testnetChain = defineChain({
  id: 7891,
  name: 'Initia Testnet',
  nativeCurrency: { name: 'INIT', symbol: 'INIT', decimals: 18 },
  rpcUrls: {
    default: {
      http: [import.meta.env.VITE_TESTNET_JSON_RPC_URL || 'https://jsonrpc-evm-1.anvil.asia-southeast.initia.xyz'],
    },
  },
});

export const config = {
  network,
  chain: network === 'testnet' ? testnetChain : localChain,
  chainId: import.meta.env.VITE_CHAIN_ID || 'minitia-1',
  contractAddress: import.meta.env.VITE_CONTRACT_ADDRESS as `0x${string}` || '0x0000000000000000000000000000000000000000',
  backendUrl: import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000',
  demoMode: import.meta.env.VITE_DEMO_MODE === 'true',
  mockIUSDAddress: import.meta.env.VITE_MOCK_IUSD_ADDRESS as `0x${string}` || '0x0000000000000000000000000000000000000000',
  sessionVaultAddress: import.meta.env.VITE_SESSION_VAULT_ADDRESS as `0x${string}` || '0x0000000000000000000000000000000000000000',
  paymentGatewayAddress: import.meta.env.VITE_PAYMENT_GATEWAY_ADDRESS as `0x${string}` || '0x0000000000000000000000000000000000000000',
  paymentEnabled: import.meta.env.VITE_PAYMENT_ENABLED === 'true',
};

// InterwovenKit custom chain definition
const nativeDenom = import.meta.env.VITE_NATIVE_DENOM || 'umin';
const nativeSymbol = import.meta.env.VITE_NATIVE_SYMBOL || 'MIN';

export const customChain = {
  chain_id: config.chainId,
  chain_name: 'initia-signal',
  pretty_name: 'Initia Signal',
  network_type: 'testnet' as const,
  bech32_prefix: 'init',
  apis: {
    rpc: [{ address: import.meta.env.VITE_COSMOS_RPC_URL || 'http://localhost:26657' }],
    rest: [{ address: import.meta.env.VITE_REST_URL || 'http://localhost:1317' }],
    'json-rpc': [{ address: config.chain.rpcUrls.default.http[0] }],
    indexer: [{ address: import.meta.env.VITE_INDEXER_URL || 'http://localhost:8080' }],
  },
  fees: {
    fee_tokens: [{
      denom: nativeDenom,
      fixed_min_gas_price: 0, low_gas_price: 0, average_gas_price: 0, high_gas_price: 0,
    }],
  },
  staking: { staking_tokens: [{ denom: nativeDenom }] },
  native_assets: [{ denom: nativeDenom, symbol: nativeSymbol, decimals: 18 }],
  metadata: { is_l1: false, minitia: { type: 'minievm' } },
};

// Known asset icons (extensible)
const ASSET_ICONS: Record<string, { name: string; icon: string }> = {
  BTC: { name: 'Bitcoin', icon: '₿' },
  ETH: { name: 'Ethereum', icon: 'Ξ' },
  INIT: { name: 'Initia', icon: 'I' },
  SOL: { name: 'Solana', icon: 'S' },
  AVAX: { name: 'Avalanche', icon: 'A' },
  DOGE: { name: 'Dogecoin', icon: 'D' },
  LINK: { name: 'Chainlink', icon: 'L' },
  DOT: { name: 'Polkadot', icon: 'D' },
  ATOM: { name: 'Cosmos', icon: 'A' },
  TIA: { name: 'Celestia', icon: 'T' },
  SEI: { name: 'Sei', icon: 'S' },
  SUI: { name: 'Sui', icon: 'S' },
  APT: { name: 'Aptos', icon: 'A' },
  ARB: { name: 'Arbitrum', icon: 'A' },
  OP: { name: 'Optimism', icon: 'O' },
  INJ: { name: 'Injective', icon: 'I' },
  MATIC: { name: 'Polygon', icon: 'M' },
};

// Static fallback for known addresses
export const ASSETS: Record<string, { symbol: string; name: string; icon: string }> = {
  '0x0000000000000000000000000000000000000001': { symbol: 'BTC', name: 'Bitcoin', icon: '₿' },
  '0x0000000000000000000000000000000000000002': { symbol: 'ETH', name: 'Ethereum', icon: 'Ξ' },
  '0x0000000000000000000000000000000000000003': { symbol: 'INIT', name: 'Initia', icon: 'I' },
};

export function getAssetInfo(address: string) {
  const known = ASSETS[address.toLowerCase()];
  if (known) return known;
  // Try to extract symbol from address pattern (custom assets use hash-based addresses)
  return { symbol: '???', name: 'Custom', icon: '•' };
}

export function getAssetIcon(symbol: string): { name: string; icon: string } {
  const base = symbol.replace('/USD', '').toUpperCase();
  return ASSET_ICONS[base] || { name: base, icon: base.charAt(0) };
}

export function formatPrice(weiStr: string): string {
  const val = Number(BigInt(weiStr)) / 1e18;
  if (val >= 1000) return val.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (val >= 1) return val.toFixed(4);
  return val.toFixed(6);
}

export function formatPnl(entry: string, exit: string, isBull: boolean): { pct: number; value: string } {
  const e = Number(BigInt(entry));
  const x = Number(BigInt(exit));
  if (e === 0) return { pct: 0, value: '0%' };
  let pct = ((x - e) / e) * 100;
  if (!isBull) pct = -pct;
  return { pct, value: `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` };
}

export function truncateAddress(addr: string): string {
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`;
}

// Explorer URLs
const SCAN_BASE = `https://scan.testnet.initia.xyz/${import.meta.env.VITE_CHAIN_ID || 'initia-signal-1'}`;
const INDEXER_BASE = import.meta.env.VITE_INDEXER_URL || 'http://localhost:8080';

export function explorerTxUrl(txHash: string): string {
  return `${SCAN_BASE}/txs/${txHash}`;
}

export function explorerAccountUrl(address: string): string {
  return `${SCAN_BASE}/accounts/${address}`;
}

export function explorerContractUrl(address: string): string {
  return `${SCAN_BASE}/evm-contracts/${address}`;
}

export async function lookupTx(txHash: string): Promise<any | null> {
  try {
    const res = await fetch(`${INDEXER_BASE}/indexer/tx/v1/txs/${txHash}`);
    if (!res.ok) return null;
    const data = await res.json();
    return data.tx || null;
  } catch { return null; }
}

// Card helpers
export function formatVolume(n: number): string {
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${(n / 1e3).toFixed(0)}K`;
  return `$${n.toFixed(0)}`;
}

export function shareToX(text: string, url?: string) {
  const params = new URLSearchParams({ text });
  if (url) params.set('url', url);
  window.open(`https://twitter.com/intent/tweet?${params}`, '_blank');
}
