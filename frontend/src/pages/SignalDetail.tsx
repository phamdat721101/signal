import { useParams, Link } from 'react-router-dom';
import { useSignal } from '../hooks/useSignals';
import { usePriceHistory } from '../hooks/usePrices';
import { useSignalActions } from '../hooks/useSignalActions';
import { getAssetInfo, getAssetIcon, formatPrice, formatPnl, truncateAddress, explorerTxUrl, explorerAccountUrl } from '../config';
import ConfidenceBadge from '../components/ConfidenceBadge';
import PriceChart from '../components/PriceChart';

export default function SignalDetail() {
  const { id } = useParams<{ id: string }>();
  const signalId = Number(id);
  const { data: signal, isLoading } = useSignal(signalId);
  const { executeSignal, status: txStatus, txHash, error: txError, reset } = useSignalActions();

  const staticAsset = signal ? getAssetInfo(signal.asset) : null;
  const dynamicInfo = signal?.symbol ? getAssetIcon(signal.symbol) : null;
  const asset = dynamicInfo && signal?.symbol ? { symbol: signal.symbol.replace('/USD', ''), ...dynamicInfo } : staticAsset;
  const { data: priceData } = usePriceHistory(asset?.symbol ? `${asset.symbol}/USD` : '');
  const pnl = signal?.resolved ? formatPnl(signal.entryPrice, signal.exitPrice, signal.isBull) : null;

  if (isLoading) return <div className="text-[var(--color-muted)]">Loading signal...</div>;
  if (!signal || !asset) return <div className="text-[var(--color-muted)]">Signal not found</div>;

  const entryNum = Number(BigInt(signal.entryPrice)) / 1e18;
  const targetNum = Number(BigInt(signal.targetPrice)) / 1e18;
  const stopLoss = signal.stopLoss ? Number(BigInt(signal.stopLoss)) / 1e18 : (signal.isBull ? entryNum * 0.985 : entryNum * 1.015);

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
            {signal.pattern && (
              <span className="text-sm px-2 py-0.5 rounded bg-purple-500/20 text-purple-400">{signal.pattern}</span>
            )}
            {signal.timeframe && (
              <span className="text-sm px-2 py-0.5 rounded bg-blue-500/20 text-blue-400">{signal.timeframe}</span>
            )}
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
          isBull={signal.isBull}
        />
      </div>

      {/* Trading Levels */}
      <div className="grid grid-cols-3 gap-4 mb-4">
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">🟡 Entry Price</div>
          <div className="text-lg font-mono text-amber-400">${formatPrice(signal.entryPrice)}</div>
        </div>
        <div className="bg-[var(--color-surface)] border border-green-500/30 rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">🟢 Take Profit</div>
          <div className="text-lg font-mono text-green-400">${formatPrice(signal.targetPrice)}</div>
        </div>
        <div className="bg-[var(--color-surface)] border border-red-500/30 rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">🔴 Stop Loss</div>
          <div className="text-lg font-mono text-red-400">${stopLoss >= 1000 ? stopLoss.toLocaleString(undefined, { maximumFractionDigits: 2 }) : stopLoss.toFixed(4)}</div>
        </div>
      </div>

      {/* Signal Info */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">Risk/Reward</div>
          <div className="text-lg font-mono text-white">1:1</div>
        </div>
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-4">
          <div className="text-sm text-[var(--color-muted)]">Confidence</div>
          <div className="text-lg font-mono text-white">{signal.confidence}%</div>
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

      {/* AI Workflow */}
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5 mb-6">
        <div className="text-sm font-semibold text-white mb-4">AI Signal Generation Pipeline</div>
        <div className="flex items-center gap-2 text-xs overflow-x-auto pb-2">
          <div className="flex-shrink-0 px-3 py-2 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400">
            📡 Price Feed
          </div>
          <span className="text-[var(--color-muted)]">→</span>
          <div className="flex-shrink-0 px-3 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400">
            📈 EMA(5/10)
          </div>
          <span className="text-[var(--color-muted)]">→</span>
          <div className="flex-shrink-0 px-3 py-2 rounded-lg bg-purple-500/10 border border-purple-500/30 text-purple-400">
            📊 RSI Filter
          </div>
          <span className="text-[var(--color-muted)]">→</span>
          <div className="flex-shrink-0 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/30 text-amber-400">
            🎯 {signal.confidence}%
          </div>
          <span className="text-[var(--color-muted)]">→</span>
          <div className={`flex-shrink-0 px-3 py-2 rounded-lg ${signal.isBull ? 'bg-green-500/10 border border-green-500/30 text-green-400' : 'bg-red-500/10 border border-red-500/30 text-red-400'}`}>
            {signal.isBull ? '📈 BULL' : '📉 BEAR'}
          </div>
          <span className="text-[var(--color-muted)]">→</span>
          <div className="flex-shrink-0 px-3 py-2 rounded-lg bg-[var(--color-accent)]/10 border border-[var(--color-accent)]/30 text-[var(--color-accent)]">
            ⛓️ On-Chain
          </div>
        </div>
        <div className="mt-3 text-xs text-[var(--color-muted)]">
          Real-time prices → EMA(5) vs EMA(10) crossover for direction → RSI confirms not overbought/oversold → confidence scored → ±1.5% target → on-chain → auto-resolve 24h
        </div>
      </div>

      {/* Price Analysis */}
      {signal.analysis && (
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5 mb-6">
          <div className="flex items-center justify-between mb-3">
            <div className="text-sm font-semibold text-white">📝 Why This Signal?</div>
            {signal.timeframe && (
              <span className="text-xs px-2 py-1 rounded bg-blue-500/10 border border-blue-500/30 text-blue-400">
                ⏱ {signal.timeframe}
              </span>
            )}
          </div>
          {signal.analysis.split('. ').filter(Boolean).map((sentence, i) => (
            <p key={i} className="text-sm text-[var(--color-muted)] leading-relaxed mb-1">
              {sentence.endsWith('.') ? sentence : sentence + '.'}
            </p>
          ))}
        </div>
      )}

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
            <div className="space-y-2">
              <div className="text-green-400 text-sm font-semibold">✓ Signal executed on-chain!</div>
              {txHash && (
                <div className="bg-[var(--color-bg)] rounded-lg p-3 space-y-2">
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-[var(--color-muted)]">TX Hash:</span>
                    <code className="font-mono text-white break-all">{txHash}</code>
                  </div>
                  <div className="flex gap-2">
                    <a href={explorerTxUrl(txHash)} target="_blank" rel="noopener noreferrer"
                      className="px-3 py-1 text-xs bg-[var(--color-accent)]/20 text-[var(--color-accent)] rounded hover:bg-[var(--color-accent)]/30 transition-colors">
                      Initia Scan ↗
                    </a>
                    <button onClick={() => navigator.clipboard.writeText(txHash)}
                      className="px-3 py-1 text-xs bg-[var(--color-surface)] border border-[var(--color-border)] text-white rounded hover:border-[var(--color-accent)] transition-colors">
                      Copy Hash
                    </button>
                  </div>
                </div>
              )}
              <button onClick={reset} className="text-xs underline text-[var(--color-muted)]">Reset</button>
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
