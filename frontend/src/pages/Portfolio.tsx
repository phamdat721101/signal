import { useState } from 'react';
import { useSignals } from '../hooks/useSignals';
import { getAssetInfo, formatPrice, formatPnl } from '../config';
import StatCard from '../components/StatCard';

type Tab = 'active' | 'history';

export default function Portfolio() {
  const { data: signals = [], isLoading } = useSignals(0, 100);
  const [tab, setTab] = useState<Tab>('active');

  // For now show all signals (in production, filter by connected wallet)
  const resolved = signals.filter((s) => s.resolved);
  const active = signals.filter((s) => !s.resolved);
  const displayed = tab === 'active' ? active : resolved;

  const wins = resolved.filter((s) => {
    const e = BigInt(s.entryPrice);
    const x = BigInt(s.exitPrice);
    return s.isBull ? x > e : x < e;
  });
  const winRate = resolved.length > 0 ? ((wins.length / resolved.length) * 100).toFixed(1) : '0';

  let totalPnl = 0;
  let bestTrade = 0;
  for (const s of resolved) {
    const { pct } = formatPnl(s.entryPrice, s.exitPrice, s.isBull);
    totalPnl += pct;
    if (pct > bestTrade) bestTrade = pct;
  }

  return (
    <div>
      <h1 className="text-3xl font-bold text-white mb-6">Portfolio</h1>

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Total P&L"
          value={`${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}%`}
          trend={totalPnl >= 0 ? 'up' : 'down'}
        />
        <StatCard label="Win Rate" value={`${winRate}%`} trend={Number(winRate) > 50 ? 'up' : 'neutral'} />
        <StatCard label="Total Trades" value={String(signals.length)} />
        <StatCard label="Best Trade" value={`+${bestTrade.toFixed(2)}%`} trend="up" />
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        {(['active', 'history'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm ${
              tab === t ? 'bg-[var(--color-accent)] text-white' : 'bg-[var(--color-surface)] text-[var(--color-muted)]'
            }`}
          >
            {t === 'active' ? `Active (${active.length})` : `History (${resolved.length})`}
          </button>
        ))}
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="text-[var(--color-muted)]">Loading...</div>
      ) : displayed.length === 0 ? (
        <div className="text-center py-12 text-[var(--color-muted)]">
          {tab === 'active' ? 'No active signals' : 'No trade history yet'}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
                <th className="text-left py-3 px-2">Asset</th>
                <th className="text-left py-3 px-2">Direction</th>
                <th className="text-right py-3 px-2">Entry</th>
                {tab === 'history' && <th className="text-right py-3 px-2">Exit</th>}
                <th className="text-right py-3 px-2">{tab === 'history' ? 'P&L' : 'Target'}</th>
                <th className="text-right py-3 px-2">Confidence</th>
              </tr>
            </thead>
            <tbody>
              {displayed.sort((a, b) => b.timestamp - a.timestamp).map((s) => {
                const asset = getAssetInfo(s.asset);
                const pnl = s.resolved ? formatPnl(s.entryPrice, s.exitPrice, s.isBull) : null;
                return (
                  <tr key={s.id} className="border-b border-[var(--color-border)] hover:bg-[var(--color-surface)]">
                    <td className="py-3 px-2 text-white font-mono">{asset.icon} {asset.symbol}</td>
                    <td className="py-3 px-2">
                      <span className={s.isBull ? 'text-green-400' : 'text-red-400'}>
                        {s.isBull ? 'BULL' : 'BEAR'}
                      </span>
                    </td>
                    <td className="py-3 px-2 text-right font-mono text-white">${formatPrice(s.entryPrice)}</td>
                    {tab === 'history' && (
                      <td className="py-3 px-2 text-right font-mono text-white">${formatPrice(s.exitPrice)}</td>
                    )}
                    <td className={`py-3 px-2 text-right font-mono font-bold ${
                      pnl ? (pnl.pct >= 0 ? 'text-green-400' : 'text-red-400') : 'text-[var(--color-accent)]'
                    }`}>
                      {pnl ? pnl.value : `$${formatPrice(s.targetPrice)}`}
                    </td>
                    <td className="py-3 px-2 text-right font-mono">{s.confidence}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
