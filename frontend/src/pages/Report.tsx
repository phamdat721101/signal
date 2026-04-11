import { useEffect, useRef } from 'react';
import { useReport } from '../hooks/usePrices';
import { useInterwovenKit } from '@initia/interwovenkit-react';
import StatCard from '../components/StatCard';
import { createChart, ColorType, LineSeries } from 'lightweight-charts';

function BalanceChart({ history }: { history: { trade: number; balance: number }[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || history.length < 2) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#71717a' },
      grid: { vertLines: { color: '#1e1e2e' }, horzLines: { color: '#1e1e2e' } },
      width: ref.current.clientWidth, height: 300,
      rightPriceScale: { borderColor: '#1e1e2e' },
      timeScale: { borderColor: '#1e1e2e', visible: false },
    });
    const series = chart.addSeries(LineSeries, { color: '#8b5cf6', lineWidth: 2 });
    series.setData(history.map(h => ({ time: h.trade as any, value: h.balance })));
    series.createPriceLine({ price: 10000, color: '#f59e0b44', lineWidth: 1, lineStyle: 2, title: 'Start $10,000' });
    chart.timeScale().fitContent();
    const resize = () => { if (ref.current) chart.applyOptions({ width: ref.current.clientWidth }); };
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); chart.remove(); };
  }, [history]);
  if (history.length < 2) return <div className="h-[300px] flex items-center justify-center text-[var(--color-muted)]">Not enough data</div>;
  return <div ref={ref} />;
}

function bech32ToHex(addr: string): string {
  const CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l';
  const data = addr.slice(addr.lastIndexOf('1') + 1);
  const words = [...data].map(c => CHARSET.indexOf(c)).slice(0, -6);
  let bits = 0, value = 0;
  const bytes: number[] = [];
  for (const w of words) { value = (value << 5) | w; bits += 5; while (bits >= 8) { bits -= 8; bytes.push((value >> bits) & 0xff); } }
  return `0x${bytes.map(b => b.toString(16).padStart(2, '0')).join('')}`;
}

export default function Report() {
  const { initiaAddress } = useInterwovenKit();
  const evmAddress = initiaAddress ? bech32ToHex(initiaAddress) : undefined;
  const { data: report, isLoading } = useReport(evmAddress);

  if (!initiaAddress) {
    return (
      <div>
        <h1 className="text-3xl font-bold text-white mb-6">Performance Report</h1>
        <div className="text-center py-12 text-[var(--color-muted)]">
          <p className="text-lg mb-2">Connect your wallet</p>
          <p className="text-sm">Your report tracks performance of signals you've executed.</p>
        </div>
      </div>
    );
  }

  if (isLoading) return <div className="text-[var(--color-muted)]">Loading report...</div>;
  if (!report) return <div className="text-[var(--color-muted)]">No report data available. Execute some signals first.</div>;

  const sim = report.simulation;

  return (
    <div>
      <h1 className="text-3xl font-bold text-white mb-6">Performance Report</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total Signals" value={String(report.totalSignals)} />
        <StatCard label="Win Rate" value={`${report.winRate}%`} trend={report.winRate > 50 ? 'up' : 'neutral'} />
        <StatCard label="Avg ROI" value={`${report.averageRoi >= 0 ? '+' : ''}${report.averageRoi}%`} trend={report.averageRoi >= 0 ? 'up' : 'down'} />
        <StatCard label="Wins / Losses" value={`${report.wins} / ${report.losses}`} />
      </div>

      {/* Best / Worst */}
      <div className="grid grid-cols-2 gap-4 mb-8">
        <div className="bg-[var(--color-surface)] border border-green-500/30 rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">🏆 Best Trade</div>
          <div className="text-2xl font-bold font-mono text-green-400">+{report.bestTrade}%</div>
        </div>
        <div className="bg-[var(--color-surface)] border border-red-500/30 rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">📉 Worst Trade</div>
          <div className="text-2xl font-bold font-mono text-red-400">{report.worstTrade}%</div>
        </div>
      </div>

      {/* Simulated Balance */}
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5 mb-8">
        <div className="flex items-center justify-between mb-4">
          <div className="text-sm font-semibold text-white">Simulated Portfolio ($10,000 start, $100/trade)</div>
          <div className={`text-lg font-bold font-mono ${sim.totalReturn >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            ${sim.finalBalance.toLocaleString()} ({sim.totalReturnPct >= 0 ? '+' : ''}{sim.totalReturnPct}%)
          </div>
        </div>
        <BalanceChart history={sim.balanceHistory} />
      </div>

      {/* Per-Asset Breakdown */}
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5">
        <div className="text-sm font-semibold text-white mb-4">Per-Asset Breakdown</div>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
              <th className="text-left py-3 px-2">Asset</th>
              <th className="text-right py-3 px-2">Signals</th>
              <th className="text-right py-3 px-2">Win Rate</th>
              <th className="text-right py-3 px-2">Total P&L</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(report.perAsset || {}).map(([asset, stats]: [string, any]) => (
              <tr key={asset} className="border-b border-[var(--color-border)]">
                <td className="py-3 px-2 text-white font-mono">{asset}</td>
                <td className="py-3 px-2 text-right font-mono text-white">{stats.total}</td>
                <td className="py-3 px-2 text-right font-mono text-white">{stats.winRate}%</td>
                <td className={`py-3 px-2 text-right font-mono font-bold ${stats.totalPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {stats.totalPnl >= 0 ? '+' : ''}{stats.totalPnl}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
