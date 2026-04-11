import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { useSignals, useSignalCount } from '../hooks/useSignals';
import { useSession, type TxStep } from '../hooks/useSession';
import { config, explorerTxUrl, truncateAddress, getAssetIcon } from '../config';
import StatCard from '../components/StatCard';
import SignalCard from '../components/SignalCard';
import { useIUSDBalance } from '../hooks/useIUSDBalance';

function TxStepRow({ step }: { step: TxStep }) {
  const icon = step.status === 'success' ? '✓' : step.status === 'error' ? '✗' : step.status === 'pending' ? '⏳' : '○';
  const color = step.status === 'success' ? 'text-green-400' : step.status === 'error' ? 'text-red-400' : step.status === 'pending' ? 'text-amber-400' : 'text-[var(--color-muted)]';
  return (
    <div className="flex items-start gap-3 py-2">
      <span className={`text-sm font-mono ${color}`}>{icon}</span>
      <div className="flex-1 min-w-0">
        <div className={`text-sm ${step.status === 'idle' ? 'text-[var(--color-muted)]' : 'text-white'}`}>{step.label}</div>
        {step.txHash && (
          <div className="flex items-center gap-2 mt-1">
            <code className="text-xs font-mono text-[var(--color-muted)] truncate">{step.txHash}</code>
            <a href={explorerTxUrl(step.txHash)} target="_blank" rel="noopener noreferrer"
              className="text-xs text-[var(--color-accent)] hover:underline whitespace-nowrap">View ↗</a>
            <button onClick={() => navigator.clipboard.writeText(step.txHash!)}
              className="text-xs text-[var(--color-muted)] hover:text-white whitespace-nowrap">Copy</button>
          </div>
        )}
        {step.error && <div className="text-xs text-red-400 mt-1">{step.error}</div>}
      </div>
    </div>
  );
}

export default function Dashboard() {
  const { data: total = 0 } = useSignalCount();
  const { data: signals = [], isLoading } = useSignals(0, 100);
  const { claimFaucet, approveAndDeposit, clearSteps, findActiveSession, payForService, loading: sessionLoading, steps, connected } = useSession();
  const { walletFormatted, sessionFormatted, sessionBalance } = useIUSDBalance();
  const [genLoading, setGenLoading] = useState(false);
  const [genResult, setGenResult] = useState<any>(null);
  const [selectedAssets, setSelectedAssets] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState('30m');
  const [targetPct, setTargetPct] = useState('1.5');
  const [trackedPairs, setTrackedPairs] = useState<{address: string; symbol: string}[]>([]);
  const [availablePairs, setAvailablePairs] = useState<string[]>([]);
  const [customPair, setCustomPair] = useState('');
  const [addingPair, setAddingPair] = useState(false);

  useEffect(() => {
    fetch(`${config.backendUrl}/api/signal-options`)
      .then(r => r.json())
      .then(d => {
        setTrackedPairs(d.assets || []);
        setAvailablePairs(d.availablePairs || []);
      })
      .catch(() => {});
  }, []);

  const handleAddPair = async () => {
    if (!customPair.trim()) return;
    setAddingPair(true);
    try {
      const resp = await fetch(`${config.backendUrl}/api/assets?symbol=${encodeURIComponent(customPair.trim())}`, { method: 'POST' });
      const data = await resp.json();
      if (resp.ok) {
        setTrackedPairs(prev => [...prev, { address: data.address, symbol: data.symbol }]);
        setCustomPair('');
      } else {
        setGenResult({ error: data?.detail || 'Failed to add pair' });
      }
    } catch (e: any) {
      setGenResult({ error: e.message });
    } finally {
      setAddingPair(false);
    }
  };

  const handleRemovePair = async (symbol: string) => {
    try {
      const resp = await fetch(`${config.backendUrl}/api/assets?symbol=${encodeURIComponent(symbol)}`, { method: 'DELETE' });
      if (resp.ok) {
        setTrackedPairs(prev => prev.filter(p => p.symbol !== symbol));
        setSelectedAssets(prev => prev.filter(a => a !== symbol));
      }
    } catch {}
  };

  const resolved = signals.filter((s) => s.resolved);
  const wins = resolved.filter((s) => {
    const entry = BigInt(s.entryPrice);
    const exit = BigInt(s.exitPrice);
    return s.isBull ? exit > entry : exit < entry;
  });
  const winRate = resolved.length > 0 ? ((wins.length / resolved.length) * 100).toFixed(1) : '0';
  const latest = [...signals].sort((a, b) => b.timestamp - a.timestamp).slice(0, 3);
  const allDone = steps.length > 0 && steps.every(s => s.status === 'success' || s.status === 'error');

  const handleGenerate = async () => {
    setGenLoading(true);
    setGenResult(null);
    try {
      const headers: Record<string, string> = {};

      if (config.paymentEnabled) {
        if (!connected) {
          setGenResult({ error: 'Connect wallet first.' });
          return;
        }

        // 1. Get pricing
        const pricingResp = await fetch(`${config.backendUrl}/api/payment/pricing`);
        const pricing = await pricingResp.json();
        const priceWei = BigInt(pricing.pricing['signal-premium'].price_wei);

        // 2. Find active session
        const session = await findActiveSession(priceWei);
        if (!session) {
          setGenResult({ error: 'No active session with sufficient balance. Deposit iUSD first.' });
          return;
        }

        // 3. Pay on-chain
        const txHash = await payForService(session.sessionId, priceWei, 'signal-premium');
        if (!txHash) {
          setGenResult({ error: 'Payment transaction failed.' });
          return;
        }
        headers['X-PAYMENT-TX'] = txHash;
      }

      // 4. Call backend with user params
      const params = new URLSearchParams();
      if (selectedAssets.length > 0) params.set('assets', selectedAssets.join(','));
      params.set('timeframe', timeframe);
      params.set('target_pct', targetPct);
      const resp = await fetch(`${config.backendUrl}/api/signals/generate?${params}`, {
        method: 'POST',
        headers,
      });
      const data = await resp.json();
      if (!resp.ok) {
        const detail = data?.detail; const msg = typeof detail === 'string' ? detail : detail?.error || data?.error?.message || JSON.stringify(data);
        setGenResult({ error: `Server error: ${msg}` });
        return;
      }
      setGenResult(data);
    } catch (e: any) {
      setGenResult({ error: e.message === 'Failed to fetch' ? 'Backend unreachable — is the server running on ' + config.backendUrl + '?' : (e.message || 'Generation failed') });
    } finally {
      setGenLoading(false);
    }
  };

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Dashboard</h1>
        <p className="text-[var(--color-muted)]">AI-powered trading intelligence on Initia</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total Signals" value={String(total)} />
        <StatCard label="Active" value={String(signals.filter((s) => !s.resolved).length)} />
        <StatCard label="Win Rate" value={`${winRate}%`} trend={Number(winRate) > 50 ? 'up' : 'neutral'} />
        <StatCard label="Resolved" value={String(resolved.length)} />
      </div>

      {/* MPP Payment Session */}
      {config.paymentEnabled && (
        <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5 mb-8">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="text-sm font-semibold text-white">iUSD Payment Session (MPP)</div>
              <div className="text-xs text-[var(--color-muted)] mt-1">Pay with mock-iUSD to get signal access via Micropayment Protocol</div>
            </div>
            {config.mockIUSDAddress !== '0x0000000000000000000000000000000000000000' && (
              <a href={explorerTxUrl('')?.replace('/txs/', '/evm-contracts/').replace(/\/$/,'')} target="_blank" rel="noopener noreferrer"
                className="text-xs text-[var(--color-muted)] font-mono hover:text-[var(--color-accent)]">
                iUSD: {truncateAddress(config.mockIUSDAddress)}
              </a>
            )}
          </div>

          {/* Balances */}
          {connected && (
            <div className="flex items-center gap-4 mb-4 px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)]">
              <div className="text-xs">
                <span className="text-[var(--color-muted)]">Wallet: </span>
                <span className="text-amber-400 font-mono">{Number(walletFormatted).toFixed(2)} iUSD</span>
              </div>
              <div className="text-xs">
                <span className="text-[var(--color-muted)]">Session: </span>
                <span className="text-purple-400 font-mono">
                  {sessionBalance > 0n ? `${Number(sessionFormatted).toFixed(2)} iUSD` : 'No active session'}
                </span>
              </div>
            </div>
          )}

          {/* Flow */}
          <div className="flex items-center gap-1 text-xs overflow-x-auto pb-3 mb-4 border-b border-[var(--color-border)]">
            {['🪙 Faucet', '✅ Approve', '🔐 Deposit', '📋 Session', '🎫 Voucher', '📊 Signal'].map((label, i, arr) => (
              <span key={label} className="flex items-center gap-1">
                <span className="flex-shrink-0 px-2 py-1 rounded bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-muted)]">{label}</span>
                {i < arr.length - 1 && <span className="text-[var(--color-muted)]">→</span>}
              </span>
            ))}
          </div>

          {/* Actions */}
          <div className="flex flex-wrap gap-3 mb-4">
            <button onClick={claimFaucet} disabled={sessionLoading || !connected}
              className="px-4 py-2 bg-amber-500/10 border border-amber-500/30 text-amber-400 rounded-lg text-sm hover:bg-amber-500/20 transition-colors disabled:opacity-50">
              {sessionLoading ? '⏳ Processing...' : '🪙 Claim 1000 iUSD'}
            </button>
            <button onClick={() => approveAndDeposit('10', 24)} disabled={sessionLoading || !connected}
              className="px-4 py-2 bg-purple-500/10 border border-purple-500/30 text-purple-400 rounded-lg text-sm hover:bg-purple-500/20 transition-colors disabled:opacity-50">
              {sessionLoading ? '⏳ Processing...' : '🔐 Deposit 10 iUSD → 24h Session'}
            </button>
            {!connected && <span className="text-xs text-[var(--color-muted)] self-center">Connect wallet first</span>}
          </div>

          {/* Tx Steps */}
          {steps.length > 0 && (
            <div className="bg-[var(--color-bg)] rounded-lg p-4">
              <div className="flex items-center justify-between mb-2">
                <div className="text-xs font-semibold text-white">Transaction Progress</div>
                {allDone && <button onClick={clearSteps} className="text-xs text-[var(--color-muted)] hover:text-white">Clear</button>}
              </div>
              <div className="divide-y divide-[var(--color-border)]">
                {steps.map((step, i) => <TxStepRow key={i} step={step} />)}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Signal Configuration */}
      <div className="bg-[var(--color-surface)] border border-[var(--color-border)] rounded-xl p-5 mb-6">
        <div className="text-sm font-semibold text-white mb-4">⚙️ Signal Configuration</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          {/* Token Pairs */}
          <div className="md:col-span-3">
            <label className="text-xs text-[var(--color-muted)] mb-1 block">Token Pairs (click to select, right-click to remove custom)</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {trackedPairs.map(({symbol}) => {
                const info = getAssetIcon(symbol);
                return (
                  <button key={symbol}
                    onClick={() => setSelectedAssets(prev =>
                      prev.includes(symbol) ? prev.filter(a => a !== symbol) : [...prev, symbol]
                    )}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      if (!['BTC/USD','ETH/USD','INIT/USD'].includes(symbol)) handleRemovePair(symbol);
                    }}
                    className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
                      selectedAssets.length === 0 || selectedAssets.includes(symbol)
                        ? 'bg-[var(--color-accent)]/20 border border-[var(--color-accent)] text-white'
                        : 'bg-[var(--color-bg)] border border-[var(--color-border)] text-[var(--color-muted)]'
                    }`}>
                    {info.icon} {symbol.replace('/USD', '')}
                  </button>
                );
              })}
              {/* Add custom pair */}
              <div className="flex items-center gap-1">
                <select value={customPair} onChange={e => setCustomPair(e.target.value)}
                  className="px-2 py-1.5 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-white text-sm">
                  <option value="">+ Add pair...</option>
                  {availablePairs.filter(p => !trackedPairs.some(t => t.symbol === p)).map(p => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
                {customPair && (
                  <button onClick={handleAddPair} disabled={addingPair}
                    className="px-2 py-1.5 rounded-lg bg-green-500/20 border border-green-500/30 text-green-400 text-sm disabled:opacity-50">
                    {addingPair ? '...' : '✓'}
                  </button>
                )}
              </div>
            </div>
            <div className="text-xs text-[var(--color-muted)]">{selectedAssets.length === 0 ? 'All pairs selected' : selectedAssets.join(', ')}</div>
          </div>
          {/* Timeframe */}
          <div>
            <label className="text-xs text-[var(--color-muted)] mb-1 block">Chart Timeframe</label>
            <select value={timeframe} onChange={e => setTimeframe(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-white text-sm">
              <option value="15m">15m candles / 24h</option>
              <option value="30m">30m candles / 24h</option>
              <option value="1h">1h candles / 7 days</option>
              <option value="4h">4h candles / 30 days</option>
              <option value="1d">1d candles / 90 days</option>
            </select>
          </div>
          {/* Target P/L */}
          <div>
            <label className="text-xs text-[var(--color-muted)] mb-1 block">Target P/L %</label>
            <div className="flex items-center gap-2">
              <input type="number" value={targetPct} onChange={e => setTargetPct(e.target.value)}
                min="0.1" max="20" step="0.1"
                className="w-full px-3 py-2 rounded-lg bg-[var(--color-bg)] border border-[var(--color-border)] text-white text-sm font-mono" />
              <span className="text-sm text-[var(--color-muted)]">%</span>
            </div>
            <div className="text-xs text-[var(--color-muted)] mt-1">TP: +{targetPct}% / SL: -{targetPct}%</div>
          </div>
        </div>
        <div className="flex flex-wrap gap-3">
          <button onClick={handleGenerate} disabled={genLoading}
            className="px-4 py-2 bg-[var(--color-accent)] text-white rounded-lg text-sm hover:opacity-90 transition-opacity disabled:opacity-50">
            {genLoading ? '⏳ Generating...' : '⚡ Generate Signal'}
          </button>
          <Link to="/signals" className="px-4 py-2 bg-[var(--color-surface)] border border-[var(--color-border)] text-white rounded-lg text-sm hover:border-[var(--color-accent)] transition-colors">
            View All Signals
          </Link>
          <a href="https://bridge.initia.xyz" target="_blank" rel="noopener noreferrer"
            className="px-4 py-2 bg-green-500/10 border border-green-500/30 text-green-400 rounded-lg text-sm hover:bg-green-500/20 transition-colors">
            Bridge Funds
          </a>
        </div>
      </div>

      {/* Generate Result */}
      {genResult && (
        <div className={`rounded-lg p-4 mb-8 text-sm ${genResult.error ? 'bg-red-500/10 border border-red-500/20' : 'bg-green-500/10 border border-green-500/20'}`}>
          {genResult.error ? (
            <div className="text-red-400">{genResult.error}</div>
          ) : (
            <div>
              <div className="text-green-400 font-semibold mb-2">
                {genResult.newSignals > 0
                  ? `Generated ${genResult.newSignals} new signal(s)`
                  : 'No new signals \u2014 market conditions unchanged'}
              </div>
              {genResult.errors?.length > 0 && (
                <div className="text-amber-400 text-xs mt-1">
                  {genResult.errors.map((err: string, i: number) => <div key={i}>⚠ {err}</div>)}
                </div>
              )}
              {genResult.recentTxs?.map((tx: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs mt-1">
                  <span className="text-white">{tx.symbol} {tx.isBull ? '\u{1F4C8}' : '\u{1F4C9}'} {tx.confidence}%</span>
                  <a href={explorerTxUrl(tx.txHash)} target="_blank" rel="noopener noreferrer"
                    className="font-mono text-[var(--color-accent)] hover:underline">{tx.txHash?.slice(0, 16)}...</a>
                </div>
              ))}
              {genResult.payment && (
                <div className="text-xs text-[var(--color-muted)] mt-2">
                  Paid: {(Number(genResult.payment.amount_paid) / 1e18).toFixed(4)} iUSD | Session #{genResult.payment.session_id} | <a href={explorerTxUrl(genResult.payment.tx_hash)} target="_blank" rel="noopener noreferrer" className="text-[var(--color-accent)] hover:underline">tx</a>
                </div>
              )}
            </div>
          )}
          <button onClick={() => setGenResult(null)} className="text-xs text-[var(--color-muted)] hover:text-white mt-2">Dismiss</button>
        </div>
      )}

      {/* Latest Signals */}
      <div>
        <h2 className="text-xl font-semibold text-white mb-4">Latest Signals</h2>
        {isLoading ? (
          <div className="text-[var(--color-muted)]">Loading...</div>
        ) : latest.length === 0 ? (
          <div className="text-center py-12 text-[var(--color-muted)]">
            <p className="text-lg mb-2">No signals yet</p>
            <p className="text-sm">Deposit iUSD and generate signals, or the AI engine runs automatically.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {latest.map((s) => <SignalCard key={s.id} signal={s} />)}
          </div>
        )}
      </div>
    </div>
  );
}
