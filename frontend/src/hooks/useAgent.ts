import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { config } from '../config';

export interface AgentConfig {
  id?: number;
  user_address: string;
  strategy: 'conservative' | 'balanced' | 'degen';
  max_position_usd: number;
  tokens_whitelist: string[];
  tokens_blacklist: string[];
  min_confidence: number;
  auto_execute: boolean;
  risk_tolerance: 'low' | 'medium' | 'high';
  take_profit_pct: number;
  stop_loss_pct: number;
  is_active: boolean;
  learned_preferences?: { preferred_tokens?: string[]; avg_risk_score?: number; confidence_floor?: number };
}

export interface AgentStats { total: number; wins: number; win_rate: number; pnl_usd: number }

const BASE = `${config.backendUrl}/api/v2/agent`;

export function useAgent(address: string | undefined) {
  return useQuery({
    queryKey: ['agent', address],
    queryFn: async () => {
      if (!address) return null;
      const r = await fetch(`${BASE}/my-agent?address=${address}`);
      return r.json() as Promise<{ agent: AgentConfig | null; learned: Record<string, any> }>;
    },
    enabled: !!address,
  });
}

export function useAgentStats(address: string | undefined) {
  return useQuery({
    queryKey: ['agent-stats', address],
    queryFn: async () => {
      const r = await fetch(`${BASE}/my-agent/stats?address=${address}`);
      return r.json() as Promise<AgentStats>;
    },
    enabled: !!address,
  });
}

export function useAgentNotifications(address: string | undefined) {
  return useQuery({
    queryKey: ['agent-notifs', address],
    queryFn: async () => {
      const r = await fetch(`${BASE}/my-agent/notifications?address=${address}`);
      return r.json() as Promise<{ notifications: any[] }>;
    },
    enabled: !!address,
    refetchInterval: 30_000,
  });
}

export function useSaveAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: Partial<AgentConfig> & { address: string }) => {
      const r = await fetch(`${BASE}/my-agent`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
      return r.json();
    },
    onSuccess: (_, v) => qc.invalidateQueries({ queryKey: ['agent', v.address] }),
  });
}

export function useToggleAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (address: string) => {
      const r = await fetch(`${BASE}/my-agent/toggle`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ address }) });
      return r.json();
    },
    onSuccess: (_, addr) => qc.invalidateQueries({ queryKey: ['agent', addr] }),
  });
}
