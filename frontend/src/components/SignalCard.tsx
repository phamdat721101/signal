import { Link } from 'react-router-dom';
import { getAssetInfo, getAssetIcon, formatPrice, formatPnl, truncateAddress, explorerAccountUrl } from '../config';
import ConfidenceBadge from './ConfidenceBadge';

export interface Signal {
  id: number;
  asset: string;
  isBull: boolean;
  confidence: number;
  targetPrice: string;
  entryPrice: string;
  exitPrice: string;
  timestamp: number;
  resolved: boolean;
  creator: string;
  pattern?: string;
  analysis?: string;
  timeframe?: string;
  stopLoss?: string;
  symbol?: string;
}

export default function SignalCard({ signal }: { signal: Signal }) {
  const staticAsset = getAssetInfo(signal.asset);
  const dynamicInfo = signal.symbol ? getAssetIcon(signal.symbol) : null;
  const asset = dynamicInfo ? { symbol: signal.symbol.replace('/USD', ''), ...dynamicInfo } : staticAsset;
  const pnl = signal.resolved ? formatPnl(signal.entryPrice, signal.exitPrice, signal.isBull) : null;

  return (
    <Link
      to={`/signal/${signal.id}`}
      className="block bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-4 hover:border-[var(--color-accent)] transition-colors"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">{asset.icon}</span>
          <span className="font-semibold text-white">{asset.symbol}/USD</span>
        </div>
        <ConfidenceBadge confidence={signal.confidence} />
      </div>

      {/* Direction */}
      <div className="flex items-center gap-2 mb-3">
        <span
          className={`text-sm font-bold px-2 py-0.5 rounded ${
            signal.isBull ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
          }`}
        >
          {signal.isBull ? 'BULL' : 'BEAR'}
        </span>
        {signal.pattern && (
          <span className="text-xs px-2 py-0.5 rounded bg-purple-500/20 text-purple-400">{signal.pattern}</span>
        )}
        {signal.timeframe && (
          <span className="text-xs px-2 py-0.5 rounded bg-blue-500/20 text-blue-400">{signal.timeframe.split(' / ')[0]}</span>
        )}
        {signal.resolved && (
          <span className="text-xs text-[var(--color-muted)]">Resolved</span>
        )}
      </div>

      {/* Prices */}
      <div className="grid grid-cols-2 gap-2 text-sm">
        <div>
          <span className="text-[var(--color-muted)]">Entry</span>
          <div className="text-white font-mono">${formatPrice(signal.entryPrice)}</div>
        </div>
        <div>
          <span className="text-[var(--color-muted)]">Target</span>
          <div className="text-white font-mono">${formatPrice(signal.targetPrice)}</div>
        </div>
      </div>

      {/* P&L */}
      {pnl && (
        <div className={`mt-3 text-right font-mono font-bold ${pnl.pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
          {pnl.value}
        </div>
      )}
    </Link>
  );
}
