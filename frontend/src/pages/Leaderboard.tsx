import { useState } from 'react';
import { useLeaderboard } from '../hooks/usePrices';
import { truncateAddress } from '../config';

type SortKey = 'totalPnl' | 'winRate' | 'totalSignals';

export default function Leaderboard() {
  const { data, isLoading } = useLeaderboard();
  const [sortBy, setSortBy] = useState<SortKey>('totalPnl');

  const board = [...(data?.leaderboard || [])].sort((a: any, b: any) => b[sortBy] - a[sortBy]);

  const getBadges = (entry: any) => {
    const badges: string[] = [];
    if (entry.winRate > 80) badges.push('Top Accuracy');
    if (entry.totalSignals >= 10) badges.push('Most Active');
    if (entry.totalPnl > 50) badges.push('Whale');
    return badges;
  };

  return (
    <div>
      <h1 className="text-3xl font-bold text-white mb-6">Leaderboard</h1>

      {/* Sort */}
      <div className="flex gap-2 mb-6">
        {([
          { key: 'totalPnl' as const, label: 'Profit' },
          { key: 'winRate' as const, label: 'Win Rate' },
          { key: 'totalSignals' as const, label: 'Activity' },
        ]).map((s) => (
          <button
            key={s.key}
            onClick={() => setSortBy(s.key)}
            className={`px-3 py-1.5 rounded-lg text-sm ${
              sortBy === s.key
                ? 'bg-[var(--color-accent)] text-white'
                : 'bg-[var(--color-surface)] text-[var(--color-muted)]'
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="text-[var(--color-muted)]">Loading leaderboard...</div>
      ) : board.length === 0 ? (
        <div className="text-center py-12 text-[var(--color-muted)]">
          No data yet. Signals need to be resolved to populate the leaderboard.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--color-border)] text-[var(--color-muted)]">
                <th className="text-left py-3 px-2 w-12">#</th>
                <th className="text-left py-3 px-2">Trader</th>
                <th className="text-right py-3 px-2">Profit %</th>
                <th className="text-right py-3 px-2">Win Rate</th>
                <th className="text-right py-3 px-2">Signals</th>
                <th className="text-left py-3 px-2">Badges</th>
              </tr>
            </thead>
            <tbody>
              {board.map((entry: any, i: number) => {
                const badges = getBadges(entry);
                return (
                  <tr key={entry.address} className="border-b border-[var(--color-border)] hover:bg-[var(--color-surface)]">
                    <td className="py-3 px-2 font-bold text-[var(--color-muted)]">{i + 1}</td>
                    <td className="py-3 px-2 font-mono text-white">
                      {truncateAddress(entry.address)}
                    </td>
                    <td className={`py-3 px-2 text-right font-mono font-bold ${
                      entry.totalPnl >= 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {entry.totalPnl >= 0 ? '+' : ''}{entry.totalPnl.toFixed(2)}%
                    </td>
                    <td className="py-3 px-2 text-right font-mono text-white">{entry.winRate}%</td>
                    <td className="py-3 px-2 text-right font-mono text-white">{entry.totalSignals}</td>
                    <td className="py-3 px-2">
                      <div className="flex gap-1 flex-wrap">
                        {badges.map((b) => (
                          <span key={b} className="text-xs px-1.5 py-0.5 rounded bg-[var(--color-accent)]/20 text-[var(--color-accent)]">
                            {b}
                          </span>
                        ))}
                      </div>
                    </td>
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
