import { useQuery } from '@tanstack/react-query';
import { config } from '../config';

export interface ConvictionData {
  reputation_score: number;
  total_convictions: number;
  correct_calls: number;
  accuracy: number;
  avg_conviction: number;
  current_streak: number;
  best_streak: number;
  source: string;
}

export function useConviction(address: string) {
  return useQuery({
    queryKey: ['conviction', address],
    queryFn: async (): Promise<ConvictionData> => {
      const resp = await fetch(`${config.backendUrl}/api/conviction/${address}`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json();
    },
    enabled: !!address,
  });
}

export function useConvictionLeaderboard() {
  return useQuery({
    queryKey: ['conviction-leaderboard'],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/conviction/leaderboard`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json() as Promise<{ leaderboard: any[]; source: string }>;
    },
  });
}
