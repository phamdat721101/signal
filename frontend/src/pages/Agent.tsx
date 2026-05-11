import { useState } from 'react';
import { usePrivy } from '@privy-io/react-auth';
import { useAgent, useAgentStats, useAgentNotifications, useSaveAgent, useToggleAgent } from '../hooks/useAgent';
import { normalizeAddress } from '../config';

const STRATEGIES = [
  { id: 'conservative', label: '🛡️ Conservative', desc: 'Low risk, high confidence only' },
  { id: 'balanced', label: '⚖️ Balanced', desc: 'Mix of safety and opportunity' },
  { id: 'degen', label: '🔥 Degen', desc: 'High risk, high reward' },
] as const;

export default function Agent() {
  const { user } = usePrivy();
  const address = user?.wallet?.address ? normalizeAddress(user.wallet.address) : undefined;
  const { data } = useAgent(address);
  const { data: stats } = useAgentStats(address);
  const { data: notifs } = useAgentNotifications(address);
  const save = useSaveAgent();
  const toggle = useToggleAgent();

  const agent = data?.agent;
  const learned = data?.learned || agent?.learned_preferences || {};

  const [strategy, setStrategy] = useState(agent?.strategy || 'balanced');
  const [budget, setBudget] = useState(agent?.max_position_usd || 50);
  const [confidence, setConfidence] = useState(agent?.min_confidence || 60);
  const [autoExec, setAutoExec] = useState(agent?.auto_execute || false);
  const [risk, setRisk] = useState(agent?.risk_tolerance || 'medium');

  if (!address) return <div className="p-6 text-center text-gray-400">Connect wallet to configure your agent</div>;

  const handleSave = () => {
    save.mutate({ address, strategy, max_position_usd: budget, min_confidence: confidence, auto_execute: autoExec, risk_tolerance: risk, is_active: agent?.is_active ?? false });
  };

  return (
    <div className="max-w-md mx-auto p-4 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">🤖 My Agent</h1>
        <button onClick={() => toggle.mutate(address)} className={`px-4 py-1.5 rounded-full text-sm font-medium ${agent?.is_active ? 'bg-[#8eff71]/20 text-[#8eff71]' : 'bg-gray-800 text-gray-400'}`}>
          {agent?.is_active ? '● Active' : '○ Inactive'}
        </button>
      </div>

      {/* Stats */}
      {stats && stats.total > 0 && (
        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="bg-gray-900 rounded-lg p-3"><div className="text-lg font-bold">{stats.total}</div><div className="text-xs text-gray-400">Trades</div></div>
          <div className="bg-gray-900 rounded-lg p-3"><div className="text-lg font-bold">{stats.win_rate}%</div><div className="text-xs text-gray-400">Win Rate</div></div>
          <div className="bg-gray-900 rounded-lg p-3"><div className={`text-lg font-bold ${stats.pnl_usd >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>${stats.pnl_usd}</div><div className="text-xs text-gray-400">PnL</div></div>
        </div>
      )}

      {/* Strategy */}
      <div>
        <label className="text-sm text-gray-400 mb-2 block">Strategy</label>
        <div className="grid grid-cols-3 gap-2">
          {STRATEGIES.map(s => (
            <button key={s.id} onClick={() => setStrategy(s.id)} className={`p-3 rounded-lg text-center text-xs ${strategy === s.id ? 'bg-[#8eff71]/20 border border-[#8eff71]' : 'bg-gray-900 border border-gray-800'}`}>
              <div className="text-lg">{s.label.split(' ')[0]}</div>
              <div className="mt-1">{s.label.split(' ')[1]}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Budget */}
      <div>
        <label className="text-sm text-gray-400">Budget per trade: ${budget}</label>
        <input type="range" min={10} max={500} step={10} value={budget} onChange={e => setBudget(+e.target.value)} className="w-full mt-1 accent-[#8eff71]" />
      </div>

      {/* Confidence */}
      <div>
        <label className="text-sm text-gray-400">Min confidence: {confidence}%</label>
        <input type="range" min={30} max={95} step={5} value={confidence} onChange={e => setConfidence(+e.target.value)} className="w-full mt-1 accent-[#8eff71]" />
      </div>

      {/* Risk */}
      <div>
        <label className="text-sm text-gray-400 mb-2 block">Risk tolerance</label>
        <div className="flex gap-2">
          {(['low', 'medium', 'high'] as const).map(r => (
            <button key={r} onClick={() => setRisk(r)} className={`flex-1 py-2 rounded-lg text-sm ${risk === r ? 'bg-[#8eff71]/20 text-[#8eff71]' : 'bg-gray-900 text-gray-400'}`}>{r}</button>
          ))}
        </div>
      </div>

      {/* Auto-execute */}
      <div className="flex items-center justify-between bg-gray-900 rounded-lg p-4">
        <div><div className="text-sm font-medium">Auto-execute trades</div><div className="text-xs text-gray-400">{autoExec ? 'Agent trades automatically' : 'Notify only'}</div></div>
        <button onClick={() => setAutoExec(!autoExec)} className={`w-12 h-6 rounded-full transition ${autoExec ? 'bg-[#8eff71]' : 'bg-gray-700'}`}>
          <div className={`w-5 h-5 rounded-full bg-white transition-transform ${autoExec ? 'translate-x-6' : 'translate-x-0.5'}`} />
        </button>
      </div>

      {/* Save */}
      <button onClick={handleSave} disabled={save.isPending} className="w-full py-3 rounded-lg bg-[#8eff71] text-black font-bold">
        {save.isPending ? 'Saving...' : 'Save Agent Config'}
      </button>

      {/* Learned */}
      {learned?.preferred_tokens?.length > 0 && (
        <div className="bg-gray-900 rounded-lg p-4">
          <div className="text-sm text-gray-400 mb-2">🧠 Learned from your swipes</div>
          <div className="flex flex-wrap gap-1">
            {learned.preferred_tokens.map((t: string) => <span key={t} className="px-2 py-0.5 bg-gray-800 rounded text-xs">{t}</span>)}
          </div>
          {learned.avg_risk_score && <div className="text-xs text-gray-500 mt-2">Avg risk: {learned.avg_risk_score} | Style confidence: {learned.confidence_floor}%</div>}
        </div>
      )}

      {/* Notifications */}
      {(notifs?.notifications?.length ?? 0) > 0 && (
        <div>
          <div className="text-sm text-gray-400 mb-2">Recent signals</div>
          <div className="space-y-2">
            {notifs!.notifications.slice(0, 5).map((n: any) => (
              <div key={n.id} className="bg-gray-900 rounded-lg p-3 text-xs">{n.message}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
