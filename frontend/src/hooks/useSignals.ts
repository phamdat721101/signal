import { useQuery } from '@tanstack/react-query';
import { createPublicClient, http } from 'viem';
import { config } from '../config';
import { SIGNAL_REGISTRY_ABI } from '../abi/SignalRegistry';
import type { Signal } from '../components/SignalCard';

const client = createPublicClient({
  chain: config.chain,
  transport: http(),
});

const contractConfig = {
  address: config.contractAddress,
  abi: SIGNAL_REGISTRY_ABI,
} as const;

async function fetchSignalCount(): Promise<number> {
  const count = await client.readContract({
    ...contractConfig,
    functionName: 'getSignalCount',
  });
  return Number(count);
}

async function fetchSignals(offset: number, limit: number): Promise<Signal[]> {
  try {
    const resp = await fetch(`${config.backendUrl}/api/signals?offset=${offset}&limit=${limit}`);
    if (resp.ok) {
      const data = await resp.json();
      return data.signals;
    }
  } catch { /* fallback to contract */ }
  const raw = await client.readContract({
    ...contractConfig,
    functionName: 'getSignals',
    args: [BigInt(offset), BigInt(limit)],
  });
  return (raw as any[]).map((s, i) => ({
    id: offset + i,
    asset: s.asset || s[0],
    isBull: s.isBull ?? s[1],
    confidence: Number(s.confidence ?? s[2]),
    targetPrice: String(s.targetPrice ?? s[3]),
    entryPrice: String(s.entryPrice ?? s[4]),
    exitPrice: String(s.exitPrice ?? s[5]),
    timestamp: Number(s.timestamp ?? s[6]),
    resolved: s.resolved ?? s[7],
    creator: s.creator || s[8],
  }));
}

async function fetchSignalById(id: number): Promise<Signal> {
  try {
    const resp = await fetch(`${config.backendUrl}/api/signals/${id}`);
    if (resp.ok) return resp.json();
  } catch { /* fallback to contract */ }
  const s: any = await client.readContract({
    ...contractConfig,
    functionName: 'getSignal',
    args: [BigInt(id)],
  });
  return {
    id,
    asset: s.asset || s[0],
    isBull: s.isBull ?? s[1],
    confidence: Number(s.confidence ?? s[2]),
    targetPrice: String(s.targetPrice ?? s[3]),
    entryPrice: String(s.entryPrice ?? s[4]),
    exitPrice: String(s.exitPrice ?? s[5]),
    timestamp: Number(s.timestamp ?? s[6]),
    resolved: s.resolved ?? s[7],
    creator: s.creator || s[8],
  };
}

export function useSignalCount() {
  return useQuery({
    queryKey: ['signalCount'],
    queryFn: fetchSignalCount,
  });
}

export function useSignals(offset = 0, limit = 100) {
  return useQuery({
    queryKey: ['signals', offset, limit],
    queryFn: () => fetchSignals(offset, limit),
  });
}

export function useSignal(id: number) {
  return useQuery({
    queryKey: ['signal', id],
    queryFn: () => fetchSignalById(id),
    enabled: id >= 0,
  });
}

export function useUserSignals(address?: string) {
  return useQuery({
    queryKey: ['userSignals', address],
    queryFn: async () => {
      if (!address) return [];
      const ids: any = await client.readContract({
        ...contractConfig,
        functionName: 'getUserSignals',
        args: [address as `0x${string}`],
      });
      const signalIds = (ids as bigint[]).map(Number);
      return Promise.all(signalIds.map(fetchSignalById));
    },
    enabled: !!address,
  });
}
