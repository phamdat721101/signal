import { useState } from 'react';
import { useSignals } from '../hooks/useSignals';
import SignalCard from '../components/SignalCard';

type Filter = 'all' | 'bull' | 'bear';
type StatusFilter = 'all' | 'active' | 'resolved';

export default function SignalFeed() {
  const { data: signals = [], isLoading } = useSignals(0, 100);
  const [direction, setDirection] = useState<Filter>('all');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  const filtered = signals.filter((s) => {
    if (direction === 'bull' && !s.isBull) return false;
    if (direction === 'bear' && s.isBull) return false;
    if (statusFilter === 'active' && s.resolved) return false;
    if (statusFilter === 'resolved' && !s.resolved) return false;
    return true;
  }).sort((a, b) => b.timestamp - a.timestamp);

  return (
    <div>
      <h1 className="text-3xl font-bold text-white mb-6">Signal Feed</h1>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-6">
        {(['all', 'bull', 'bear'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setDirection(f)}
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
              direction === f
                ? 'bg-[var(--color-accent)] text-white'
                : 'bg-[var(--color-surface)] text-[var(--color-muted)] hover:text-white'
            }`}
          >
            {f === 'all' ? 'All' : f === 'bull' ? 'Bullish' : 'Bearish'}
          </button>
        ))}
        <div className="w-px bg-[var(--color-border)] mx-1" />
        {(['all', 'active', 'resolved'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setStatusFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
              statusFilter === f
                ? 'bg-[var(--color-accent)] text-white'
                : 'bg-[var(--color-surface)] text-[var(--color-muted)] hover:text-white'
            }`}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="text-[var(--color-muted)]">Loading signals...</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12 text-[var(--color-muted)]">
          No signals match your filters
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filtered.map((s) => (
            <SignalCard key={s.id} signal={s} />
          ))}
        </div>
      )}
    </div>
  );
}
