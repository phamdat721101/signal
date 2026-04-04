import { useParams, Link } from 'react-router-dom';
import { useSignal } from '../hooks/useSignals';
import { usePriceHistory } from '../hooks/usePrices';
import { useSignalActions } from '../hooks/useSignalActions';
import { getAssetInfo, formatPrice, formatPnl, truncateAddress, explorerTxUrl, explorerAccountUrl } from '../config';
import ConfidenceBadge from '../components/ConfidenceBadge';
import PriceChart from '../components/PriceChart';

export default function SignalDetail() {
  const { id } = useParams<{ id: string }>();
  const signalId = Number(id);
  const { data: signal, isLoading } = useSignal(signalId);
  const { executeSignal, status: txStatus, txHash, error: txError, reset } = useSignalActions();

  const asset = signal ? getAssetInfo(signal.asset) : null;
  const { data: priceData } = usePriceHistory(asset?.symbol ? `${asset.symbol}/USD` : '');
  const pnl = signal?.resolved ? formatPnl(signal.entryPrice, signal.exitPrice, signal.isBull) : null;

  if (isLoading) return <div className="text-[var(--color-muted)]">Loading signal...</div>;
  if (!signal || !asset) return <div className="text-[var(--color-muted)]">Signal not found</div>;

  const entryNum = Number(BigInt(signal.entryPrice)) / 1e18;
  const targetNum = Number(BigInt(signal.targetPrice)) / 1e18;

  const handleExecute = () => {
    executeSignal(
      signal.asset,
      signal.isBull,
      signal.confidence,
      BigInt(signal.targetPrice),
      BigInt(signal.entryPrice),
    );
  };

  return (
    <div>
      <Link to="/signals" className="text-[var(--color-muted)] text-sm hover:text-white mb-4 inline-block">
        &larr; Back to Signals
      </Link>

      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <span className="text-3xl">{asset.icon}</span>
        <div>
          <h1 className="text-2xl font-bold text-white">{asset.symbol}/USD</h1>
          <div className="flex items-center gap-2 mt-1">
            <span
              className={`text-sm font-bold px-2 py-0.5 rounded ${
                signal.isBull ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'
              }`}
            >
              {signal.isBull ? 'BULLISH' : 'BEARISH'}
            </span>
            <ConfidenceBadge confidence={signal.confidence} />
            {signal.resolved && (
              <span className="text-xs px-2 py-0.5 rounded bg-[var(--color-border)] text-[var(--color-muted)]">
                Resolved
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Chart */}
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-4 mb-6">
        <PriceChart
          data={priceData?.history || []}
          entryPrice={entryNum}
          targetPrice={targetNum}
        />
      </div>

      {/* Info Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">Entry Price</div>
          <div className="text-lg font-mono text-white">${formatPrice(signal.entryPrice)}</div>
        </div>
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">Target Price</div>
          <div className="text-lg font-mono text-[var(--color-accent)]">${formatPrice(signal.targetPrice)}</div>
        </div>
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">Creator</div>
          <a href={explorerAccountUrl(signal.creator)} target="_blank" rel="noopener noreferrer"
              className="text-lg font-mono text-[var(--color-accent)] hover:opacity-80">{truncateAddress(signal.creator)} ↗</a>
        </div>
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">Created</div>
          <div className="text-lg text-white">{new Date(signal.timestamp * 1000).toLocaleDateString()}</div>
        </div>
      </div>

      {/* P&L (if resolved) */}
      {pnl && (
        <div className={`text-center py-4 mb-6 rounded-xl border ${
          pnl.pct >= 0 ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'
        }`}>
          <div className="text-sm text-[var(--color-muted)]">Result</div>
          <div className={`text-3xl font-bold font-mono ${pnl.pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {pnl.value}
          </div>
          <div className="text-sm text-[var(--color-muted)]">Exit: ${formatPrice(signal.exitPrice)}</div>
        </div>
      )}

      {/* Execute Button */}
      {!signal.resolved && (
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-6">
          <h3 className="text-lg font-semibold text-white mb-4">Execute This Signal</h3>
          <p className="text-sm text-[var(--color-muted)] mb-4">
            Copy this signal to your own on-chain record. Uses auto-signing if your session is active.
          </p>

          {txStatus === 'success' ? (
            <div className="text-green-400 text-sm">
              Signal executed!
              {txHash && (
                <a href={explorerTxUrl(txHash)} target="_blank" rel="noopener noreferrer"
                  className="ml-2 underline text-[var(--color-accent)] hover:opacity-80">View on Explorer ↗</a>
              )}
              <button onClick={reset} className="ml-2 underline text-[var(--color-muted)]">Reset</button>
            </div>
          ) : txStatus === 'error' ? (
            <div className="text-red-400 text-sm">
              {txError}
              <button onClick={reset} className="ml-2 underline text-[var(--color-muted)]">Retry</button>
            </div>
          ) : (
            <button
              onClick={handleExecute}
              disabled={txStatus === 'pending'}
              className="w-full py-3 bg-[var(--color-accent)] text-white rounded-lg font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {txStatus === 'pending' ? 'Executing...' : 'Execute with Auto-Sign'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
