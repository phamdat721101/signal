import { useQuery } from '@tanstack/react-query';
import { config } from '../config';

async function parseError(resp: Response, fallback: string): Promise<string> {
  try {
    const data = await resp.json();
    return data?.error?.message || data?.detail || fallback;
  } catch {
    return fallback;
  }
}

async function fetchPrices() {
  const resp = await fetch(`${config.backendUrl}/api/prices`);
  if (!resp.ok) throw new Error(await parseError(resp, `Prices: HTTP ${resp.status}`));
  return resp.json();
}

async function fetchPriceHistory(symbol: string) {
  const resp = await fetch(`${config.backendUrl}/api/prices/${symbol}/history`);
  if (!resp.ok) throw new Error(await parseError(resp, `Price history: HTTP ${resp.status}`));
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


async function fetchReport(address?: string) {
  const url = address
    ? `${config.backendUrl}/api/report?address=${address}`
    : `${config.backendUrl}/api/report`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(await parseError(resp, `Report: HTTP ${resp.status}`));
  return resp.json();
}

export function useReport(address?: string) {
  return useQuery({
    queryKey: ['report', address],
    queryFn: () => fetchReport(address),
    staleTime: 60_000,
  });
}
