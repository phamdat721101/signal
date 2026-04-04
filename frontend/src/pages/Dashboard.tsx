import { Link } from 'react-router-dom';
import { useSignals, useSignalCount } from '../hooks/useSignals';
import StatCard from '../components/StatCard';
import SignalCard from '../components/SignalCard';

export default function Dashboard() {
  const { data: total = 0 } = useSignalCount();
  const { data: signals = [], isLoading } = useSignals(0, 100);

  const resolved = signals.filter((s) => s.resolved);
  const wins = resolved.filter((s) => {
    const entry = BigInt(s.entryPrice);
    const exit = BigInt(s.exitPrice);
    return s.isBull ? exit > entry : exit < entry;
  });
  const winRate = resolved.length > 0 ? ((wins.length / resolved.length) * 100).toFixed(1) : '0';
  const latest = [...signals].sort((a, b) => b.timestamp - a.timestamp).slice(0, 3);

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Dashboard</h1>
        <p className="text-[var(--color-muted)]">AI-powered trading intelligence on Initia</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total Signals" value={String(total)} />
        <StatCard label="Active" value={String(signals.filter((s) => !s.resolved).length)} />
        <StatCard label="Win Rate" value={`${winRate}%`} trend={Number(winRate) > 50 ? 'up' : 'neutral'} />
        <StatCard label="Resolved" value={String(resolved.length)} />
      </div>

      {/* Quick Actions */}
      <div className="flex gap-3 mb-8">
        <Link
          to="/signals"
          className="px-4 py-2 bg-[var(--color-accent)] text-white rounded-lg text-sm hover:opacity-90 transition-opacity"
        >
          View All Signals
        </Link>
        <button
          onClick={async () => {
            try {
              await fetch(`${import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'}/api/signals/generate`, {
                method: 'POST',
              });
            } catch {}
          }}
          className="px-4 py-2 bg-[var(--color-surface)] border border-[var(--color-border)] text-white rounded-lg text-sm hover:border-[var(--color-accent)] transition-colors"
        >
          Generate Signal
        </button>
        <a
          href="https://bridge.initia.xyz"
          target="_blank"
          rel="noopener noreferrer"
          className="px-4 py-2 bg-green-500/10 border border-green-500/30 text-green-400 rounded-lg text-sm hover:bg-green-500/20 transition-colors"
        >
          Bridge Funds
        </a>
      </div>

      {/* Latest Signals */}
      <div>
        <h2 className="text-xl font-semibold text-white mb-4">Latest Signals</h2>
        {isLoading ? (
          <div className="text-[var(--color-muted)]">Loading...</div>
        ) : latest.length === 0 ? (
          <div className="text-center py-12 text-[var(--color-muted)]">
            <p className="text-lg mb-2">No signals yet</p>
            <p className="text-sm">The AI engine will generate signals automatically, or trigger one manually.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {latest.map((s) => (
              <SignalCard key={s.id} signal={s} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
