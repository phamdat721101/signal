import { useQuery } from '@tanstack/react-query';
import { config } from '../config';

async function fetchPrices() {
  const resp = await fetch(`${config.backendUrl}/api/prices`);
  if (!resp.ok) throw new Error('Failed to fetch prices');
  return resp.json();
}

async function fetchPriceHistory(symbol: string) {
  const resp = await fetch(`${config.backendUrl}/api/prices/${symbol}/history`);
  if (!resp.ok) throw new Error('Failed to fetch price history');
  return resp.json();
}

async function fetchLeaderboard() {
  const resp = await fetch(`${config.backendUrl}/api/leaderboard`);
  if (!resp.ok) throw new Error('Failed to fetch leaderboard');
  return resp.json();
}

export function usePrices() {
  return useQuery({
    queryKey: ['prices'],
    queryFn: fetchPrices,
    staleTime: 15_000,
  });
}

export function usePriceHistory(symbol: string) {
  return useQuery({
    queryKey: ['priceHistory', symbol],
    queryFn: () => fetchPriceHistory(symbol),
    enabled: !!symbol,
  });
}

export function useLeaderboard() {
  return useQuery({
    queryKey: ['leaderboard'],
    queryFn: fetchLeaderboard,
    staleTime: 60_000,
  });
}
