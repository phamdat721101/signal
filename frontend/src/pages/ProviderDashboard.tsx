import { useState } from 'react';
import { usePrivy } from '@privy-io/react-auth';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { config } from '../config';

type Tab = 'quick' | 'full' | 'journal';

interface Signal {
  id: number; symbol: string; isBull: boolean; confidence: number;
  entryPrice: string; targetPrice: string; stopLoss: string; exitPrice: string;
  resolved: boolean; resolutionType: string | null; provider: string;
  analysis: string; timeframe: string; timestamp: number;
}

interface ProviderStats {
  total: number; wins: number; losses: number; active: number;
  win_rate: number; avg_return: number; current_streak: number; best_streak: number;
}

// ─── Signal Form ────────────────────────────────────────────

function SignalForm({ mode, provider }: { mode: 'quick' | 'full'; provider: string }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    symbol: '', isBull: true, entryPrice: '', targetPrice: '', stopLoss: '',
    confidence: 75, timeframe: '24h', analysis: '',
  });
  const [result, setResult] = useState<{ signalId: number; cardId: number } | null>(null);

  const submit = useMutation({
    mutationFn: async () => {
      const body = {
        asset: `${form.symbol.toUpperCase()}/USD`, symbol: form.symbol.toUpperCase(),
        isBull: form.isBull, confidence: form.confidence,
        entryPrice: form.entryPrice, targetPrice: form.targetPrice, stopLoss: form.stopLoss,
        provider, timeframe: form.timeframe,
        analysis: mode === 'full' ? form.analysis : '',
      };
      const resp = await fetch(`${config.backendUrl}/api/provider/signals`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!resp.ok) throw new Error((await resp.json()).detail || 'Submit failed');
      return resp.json();
    },
    onSuccess: (data) => {
      setResult(data);
      setForm(f => ({ ...f, symbol: '', entryPrice: '', targetPrice: '', stopLoss: '', analysis: '' }));
      qc.invalidateQueries({ queryKey: ['providerSignals'] });
      qc.invalidateQueries({ queryKey: ['cards'] });
    },
  });

  const valid = form.symbol && Number(form.entryPrice) > 0 && Number(form.targetPrice) > 0 && Number(form.stopLoss) > 0
    && (form.isBull ? Number(form.targetPrice) > Number(form.entryPrice) && Number(form.stopLoss) < Number(form.entryPrice)
      : Number(form.targetPrice) < Number(form.entryPrice) && Number(form.stopLoss) > Number(form.entryPrice));

  return (
    <div className="space-y-3">
      {/* Direction toggle */}
      <div className="flex gap-2">
        <button onClick={() => setForm(f => ({ ...f, isBull: true }))}
          className={`flex-1 py-2.5 rounded-lg font-headline font-bold text-sm transition-all ${form.isBull ? 'bg-[#8eff71]/15 text-[#8eff71] border border-[#8eff71]/30' : 'bg-[#262626] text-[#adaaaa]'}`}>
          🟢 LONG
        </button>
        <button onClick={() => setForm(f => ({ ...f, isBull: false }))}
          className={`flex-1 py-2.5 rounded-lg font-headline font-bold text-sm transition-all ${!form.isBull ? 'bg-[#ff7166]/15 text-[#ff7166] border border-[#ff7166]/30' : 'bg-[#262626] text-[#adaaaa]'}`}>
          🔴 SHORT
        </button>
      </div>

      {/* Token + Timeframe */}
      <div className="flex gap-2">
        <input placeholder="Token (BTC, ETH...)" value={form.symbol}
          onChange={e => setForm(f => ({ ...f, symbol: e.target.value.toUpperCase() }))}
          className="flex-1 bg-[#262626] text-white rounded-lg px-3 py-2.5 font-headline text-sm placeholder:text-[#494847] outline-none focus:ring-1 focus:ring-[#8eff71]/30" />
        <select value={form.timeframe} onChange={e => setForm(f => ({ ...f, timeframe: e.target.value }))}
          className="bg-[#262626] text-white rounded-lg px-3 py-2.5 font-headline text-sm outline-none">
          {['1h', '4h', '24h', '7d'].map(t => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {/* Prices */}
      <div className="grid grid-cols-3 gap-2">
        {[['Entry', 'entryPrice'], ['Take Profit', 'targetPrice'], ['Stop Loss', 'stopLoss']].map(([label, key]) => (
          <div key={key}>
            <label className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest">{label}</label>
            <input type="number" step="any" placeholder="0.00" value={(form as any)[key]}
              onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
              className="w-full bg-[#262626] text-white rounded-lg px-3 py-2 font-headline text-sm outline-none focus:ring-1 focus:ring-[#8eff71]/30" />
          </div>
        ))}
      </div>

      {/* Confidence */}
      <div>
        <label className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest">Confidence: {form.confidence}%</label>
        <input type="range" min={50} max={95} value={form.confidence}
          onChange={e => setForm(f => ({ ...f, confidence: Number(e.target.value) }))}
          className="w-full accent-[#8eff71]" />
      </div>

      {/* Analysis (full mode only) */}
      {mode === 'full' && (
        <textarea placeholder="Your trading thesis / analysis..." value={form.analysis}
          onChange={e => setForm(f => ({ ...f, analysis: e.target.value }))}
          rows={3} className="w-full bg-[#262626] text-white rounded-lg px-3 py-2 font-body text-sm placeholder:text-[#494847] outline-none resize-none focus:ring-1 focus:ring-[#bf81ff]/30" />
      )}

      {/* Submit */}
      <button onClick={() => submit.mutate()} disabled={!valid || submit.isPending}
        className="w-full ape-gradient text-[#0b5800] font-headline font-black py-3 rounded-lg disabled:opacity-40 active:scale-[0.98] transition-transform">
        {submit.isPending ? 'Submitting...' : 'Publish Signal'}
      </button>

      {!valid && form.entryPrice && (
        <p className="text-[#ff7166] text-xs font-label">
          {form.isBull ? 'LONG: TP must be above entry, SL below entry' : 'SHORT: TP must be below entry, SL above entry'}
        </p>
      )}

      {submit.isError && <p className="text-[#ff7166] text-xs">{(submit.error as Error).message}</p>}

      {result && (
        <div className="bg-[#8eff71]/10 border border-[#8eff71]/20 rounded-lg p-3">
          <p className="text-[#8eff71] font-headline font-bold text-sm">✅ Signal #{result.signalId} published</p>
          {result.cardId > 0 && <p className="text-[#adaaaa] text-xs mt-1">Card #{result.cardId} generated for feed</p>}
        </div>
      )}
    </div>
  );
}

// ─── My Signals (Journal) ───────────────────────────────────

function MySignals({ provider }: { provider: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['providerSignals', provider],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/provider/signals?provider=${provider}&limit=50`);
      return resp.ok ? resp.json() as Promise<{ signals: Signal[]; total: number }> : { signals: [], total: 0 };
    },
    enabled: !!provider, refetchInterval: 30_000,
  });

  const { data: stats } = useQuery({
    queryKey: ['providerStats', provider],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/provider/${provider}/stats`);
      return resp.ok ? resp.json() as Promise<ProviderStats & { provider: string }> : null;
    },
    enabled: !!provider,
  });

  if (isLoading) return <p className="text-[#adaaaa] text-center py-8">Loading...</p>;

  const signals = data?.signals || [];

  return (
    <div className="space-y-3">
      {/* Stats bar */}
      {stats && stats.total > 0 && (
        <div className="grid grid-cols-4 gap-2">
          {[
            ['Win Rate', `${stats.win_rate}%`, stats.win_rate >= 50 ? '#8eff71' : '#ff7166'],
            ['Signals', String(stats.total), '#fff'],
            ['Streak', `🔥${stats.current_streak}`, '#f0c040'],
            ['Avg Return', `${stats.avg_return > 0 ? '+' : ''}${stats.avg_return}%`, stats.avg_return >= 0 ? '#8eff71' : '#ff7166'],
          ].map(([label, value, color]) => (
            <div key={label} className="bg-[#262626] rounded-lg p-2 text-center">
              <div className="font-label text-[8px] text-[#adaaaa] uppercase">{label}</div>
              <div className="font-headline font-bold text-sm" style={{ color: color as string }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {signals.length === 0 && <p className="text-[#494847] text-center py-8 text-sm">No signals yet. Publish your first one above.</p>}

      {signals.map(s => <SignalRow key={s.id} signal={s} />)}
    </div>
  );
}

function SignalRow({ signal: s }: { signal: Signal }) {
  const entry = Number(s.entryPrice) || 0;
  const tp = Number(s.targetPrice) || 0;
  const sl = Number(s.stopLoss) || 0;
  const exit = Number(s.exitPrice) || 0;
  const pnl = entry > 0 && exit > 0 ? ((exit - entry) / entry * 100 * (s.isBull ? 1 : -1)) : 0;

  // Progress: where is current price between SL and TP (0=SL, 100=TP)
  const range = Math.abs(tp - sl);
  const progress = range > 0 && exit > 0 ? Math.max(0, Math.min(100, ((exit - Math.min(tp, sl)) / range) * 100)) : 50;

  const statusMap: Record<string, { label: string; color: string }> = {
    TP_HIT: { label: '✅ TP HIT', color: '#8eff71' },
    SL_HIT: { label: '❌ SL HIT', color: '#ff7166' },
    EXPIRED: { label: '⏰ EXPIRED', color: '#f0c040' },
  };
  const status = s.resolved ? (statusMap[s.resolutionType || ''] || { label: '✓ Resolved', color: '#adaaaa' })
    : { label: '⏳ Active', color: '#bf81ff' };

  const age = Math.floor((Date.now() / 1000 - s.timestamp) / 3600);

  return (
    <div className="bg-[#131313] rounded-xl p-3 border border-[#494847]/10">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-headline font-bold px-2 py-0.5 rounded ${s.isBull ? 'bg-[#8eff71]/15 text-[#8eff71]' : 'bg-[#ff7166]/15 text-[#ff7166]'}`}>
            {s.isBull ? 'LONG' : 'SHORT'}
          </span>
          <span className="font-headline font-bold text-white">${s.symbol}</span>
          <span className="text-[9px] text-[#494847]">{s.timeframe} · {age}h ago</span>
        </div>
        <span className="text-xs font-label font-bold" style={{ color: status.color }}>{status.label}</span>
      </div>

      {/* Price levels */}
      <div className="flex justify-between text-[10px] font-label text-[#adaaaa] mb-1">
        <span>SL ${sl.toLocaleString()}</span>
        <span>Entry ${entry.toLocaleString()}</span>
        <span>TP ${tp.toLocaleString()}</span>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 bg-[#262626] rounded-full overflow-hidden mb-2">
        <div className="h-full rounded-full transition-all" style={{
          width: `${progress}%`,
          backgroundColor: s.resolved ? status.color : '#bf81ff',
        }} />
      </div>

      {/* PnL if resolved */}
      {s.resolved && exit > 0 && (
        <div className="flex justify-between items-center">
          <span className="text-[10px] text-[#adaaaa]">Exit: ${exit.toLocaleString()}</span>
          <span className={`font-headline font-bold text-sm ${pnl >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>
            {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
          </span>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────────

export default function ProviderDashboard() {
  const { user, authenticated, login } = usePrivy();
  const [tab, setTab] = useState<Tab>('quick');
  const provider = user?.wallet?.address || '';

  if (!authenticated) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6">
        <span className="text-4xl">📡</span>
        <p className="text-[#adaaaa] text-center">Connect your wallet to publish trading signals</p>
        <button onClick={login} className="ape-gradient px-6 py-2.5 rounded-lg text-[#0b5800] font-headline font-bold">
          Connect Wallet
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto px-4 py-4 space-y-4">
      <div>
        <h2 className="font-headline font-black text-xl text-white">Signal Provider</h2>
        <p className="text-[#adaaaa] text-xs font-label">Publish signals · Track performance · Build reputation</p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#262626]">
        {([['quick', '⚡ Quick'], ['full', '📝 Full'], ['journal', '📊 Journal']] as [Tab, string][]).map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            className={`flex-1 py-2 text-sm font-label font-semibold transition-colors ${tab === key ? 'text-[#8eff71] border-b-2 border-[#8eff71]' : 'text-[#adaaaa]'}`}>
            {label}
          </button>
        ))}
      </div>

      {/* Content */}
      {tab === 'quick' && <SignalForm mode="quick" provider={provider} />}
      {tab === 'full' && <SignalForm mode="full" provider={provider} />}
      {tab === 'journal' && <MySignals provider={provider} />}
    </div>
  );
}
