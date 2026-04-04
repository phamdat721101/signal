import { defineChain } from 'viem';

const network = import.meta.env.VITE_NETWORK || 'local';

const localChain = defineChain({
  id: 1,
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
    indexer: [{ address: 'http://localhost:8080' }],
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

// Asset metadata
export const ASSETS: Record<string, { symbol: string; name: string; icon: string }> = {
  '0x0000000000000000000000000000000000000001': { symbol: 'BTC', name: 'Bitcoin', icon: '₿' },
  '0x0000000000000000000000000000000000000002': { symbol: 'ETH', name: 'Ethereum', icon: 'Ξ' },
  '0x0000000000000000000000000000000000000003': { symbol: 'INIT', name: 'Initia', icon: 'I' },
};

export function getAssetInfo(address: string) {
  return ASSETS[address.toLowerCase()] || { symbol: '???', name: 'Unknown', icon: '?' };
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

// Explorer URL for Initia Scan
const EXPLORER_BASE = `https://scan.testnet.initia.xyz/${import.meta.env.VITE_CHAIN_ID || 'initia-signal-1'}`;

export function explorerTxUrl(txHash: string): string {
  return `${EXPLORER_BASE}/txs/${txHash}`;
}

export function explorerAccountUrl(address: string): string {
  return `${EXPLORER_BASE}/accounts/${address}`;
}

export function explorerContractUrl(address: string): string {
  return `${EXPLORER_BASE}/evm-contracts/${address}`;
}
