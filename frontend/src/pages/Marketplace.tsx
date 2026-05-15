import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { config } from '../config';
import { useStellarWallet } from '../hooks/useStellarWallet';

const BASE = `${config.backendUrl}/api/v2/agent`;

function ReportModal({ report, onClose }: { report: any; onClose: () => void }) {
  if (!report) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4" onClick={onClose}>
      <div className="bg-[#1a1a1a] rounded-2xl border border-[#333] max-w-md w-full max-h-[85vh] overflow-y-auto p-5 space-y-4" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center">
          <h3 className="text-white font-bold text-lg">📊 Premium Report</h3>
          <button onClick={onClose} className="text-[#adaaaa] text-xl">×</button>
        </div>

        {report.market_summary && (
          <div className="space-y-2">
            <h4 className="text-[#8eff71] font-bold text-sm">Market Sentiment</h4>
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-[#131313] p-3 rounded-lg">
                <div className="text-xs text-[#adaaaa]">BTC</div>
                <div className={`font-bold ${report.market_summary.btc_sentiment > 0 ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>
                  {report.market_summary.btc_direction} ({report.market_summary.btc_sentiment})
                </div>
              </div>
              <div className="bg-[#131313] p-3 rounded-lg">
                <div className="text-xs text-[#adaaaa]">ETH</div>
                <div className={`font-bold ${report.market_summary.eth_sentiment > 0 ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>
                  {report.market_summary.eth_direction} ({report.market_summary.eth_sentiment})
                </div>
              </div>
            </div>
          </div>
        )}

        {report.etf_flows && (
          <div className="space-y-1">
            <h4 className="text-[#bf81ff] font-bold text-sm">ETF Flows</h4>
            <p className="text-[#adaaaa] text-sm">BTC: ${((report.etf_flows.btc_net_flow || 0) / 1e6).toFixed(0)}M</p>
            <p className="text-[#adaaaa] text-sm">ETH: ${((report.etf_flows.eth_net_flow || 0) / 1e6).toFixed(0)}M</p>
          </div>
        )}

        {report.top_signals?.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-yellow-400 font-bold text-sm">Top Signals</h4>
            {report.top_signals.map((s: any, i: number) => (
              <div key={i} className="bg-[#131313] p-3 rounded-lg">
                <div className="flex justify-between">
                  <span className="text-white font-bold">{s.token} {s.direction === 'APE' ? '🦍' : '💨'}</span>
                  <span className="text-[#8eff71] text-sm">{s.confidence}%</span>
                </div>
                <div className="text-xs text-[#adaaaa] mt-1">
                  Entry: ${s.entry} → Target: ${s.target} | Stop: ${s.stop}
                </div>
                {s.reasoning && <p className="text-xs text-[#494847] mt-1">{s.reasoning}</p>}
              </div>
            ))}
          </div>
        )}

        {report.allocation && (
          <div className="space-y-2">
            <h4 className="text-[#8eff71] font-bold text-sm">Portfolio Allocation</h4>
            <div className="flex gap-2 flex-wrap">
              {Object.entries(report.allocation).map(([k, v]) => (
                <span key={k} className="bg-[#131313] px-3 py-1 rounded-full text-sm text-white">{k}: {v as number}%</span>
              ))}
            </div>
            {report.action && <p className="text-[#adaaaa] text-sm">💡 {report.action}</p>}
          </div>
        )}

        {report.risk_level && (
          <div className="text-center pt-2 border-t border-[#333]">
            <span className={`text-sm font-bold ${report.risk_level === 'high' ? 'text-[#ff7166]' : 'text-yellow-400'}`}>
              Risk: {report.risk_level.toUpperCase()}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Marketplace() {
  const stellar = useStellarWallet();
  const [subscribing, setSubscribing] = useState(false);
  const [reportModal, setReportModal] = useState<any>(null);
  const [buyingReport, setBuyingReport] = useState<string | null>(null);
  const [txSteps, setTxSteps] = useState<Array<{ label: string; status: string; txHash?: string; explorerUrl?: string; error?: string }>>([]);
  const qc = useQueryClient();

  const { data: providers } = useQuery({
    queryKey: ['marketplace-providers'],
    queryFn: async () => {
      const r = await fetch(`${BASE}/marketplace/providers`);
      return r.json() as Promise<{ providers: any[] }>;
    },
  });

  const { data: escrows } = useQuery({
    queryKey: ['marketplace-escrows', stellar.address],
    queryFn: async () => {
      const r = await fetch(`${BASE}/marketplace/escrows?address=${stellar.address}`);
      return r.json() as Promise<{ escrows: any[] }>;
    },
    enabled: !!stellar.address,
  });

  const backSignal = useMutation({
    mutationFn: async ({ signalId, amount }: { signalId: number; amount: number }) => {
      setSubscribing(true);
      try {
        // Step 1: Get unsigned deploy XDR from backend
        const r = await fetch(`${BASE}/marketplace/subscribe`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ subscriber_stellar: stellar.address, signal_id: signalId, amount_usdc: amount }),
        });
        const data = await r.json();
        if (data.error) throw new Error(data.error);
        if (!data.unsigned_xdr) throw new Error('No transaction to sign');

        // Step 2: User signs with Freighter
        const signedXdr = await stellar.signXdr(data.unsigned_xdr);

        // Step 3: Submit signed XDR to Stellar via Trustless Work
        await fetch(`${config.backendUrl}/api/v2/agent/marketplace/submit-tx`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ signed_xdr: signedXdr }),
        });

        qc.invalidateQueries({ queryKey: ['marketplace-escrows'] });
        return data;
      } finally {
        setSubscribing(false);
      }
    },
  });

  return (
    <div className="px-4 py-6 space-y-6 max-w-lg mx-auto">
      {/* Header */}
      <div className="text-center space-y-2">
        <h2 className="text-2xl font-black text-white">Signal Marketplace</h2>
        <p className="text-[#adaaaa] text-sm">Back AI signals with USDC. Get refunded if wrong.</p>
      </div>

      {/* Stellar Wallet */}
      <div className="flex justify-center">
        {stellar.connected ? (
          <div className="flex items-center gap-2 bg-[#1a1a1a] px-4 py-2 rounded-full border border-[#333]">
            <span className="w-2 h-2 rounded-full bg-[#8eff71]" />
            <span className="text-sm text-[#adaaaa]">{stellar.address.slice(0, 8)}...{stellar.address.slice(-4)}</span>
            <button onClick={stellar.disconnect} className="text-[#ff7166] text-xs ml-2">×</button>
          </div>
        ) : (
          <button onClick={stellar.connect} className="bg-[#8eff71] px-5 py-2.5 rounded-full text-black font-bold text-sm">
            {stellar.installed === false ? 'Install Freighter Wallet' : 'Connect Stellar Wallet'}
          </button>
        )}
      </div>

      {/* How it works */}
      {!stellar.connected && (
        <div className="bg-[#1a1a1a] rounded-xl p-4 border border-[#333] space-y-3">
          <h3 className="text-white font-bold text-sm">How it works</h3>
          <div className="space-y-2 text-sm text-[#adaaaa]">
            <p>1️⃣ Connect your Stellar wallet (Freighter)</p>
            <p>2️⃣ Back a signal with USDC — funds held in escrow</p>
            <p>3️⃣ After 24h: signal correct → provider paid. Wrong → you get refunded</p>
          </div>
          <p className="text-xs text-[#494847]">Powered by Trustless Work escrow on Stellar</p>
        </div>
      )}

      {/* Signal Providers */}
      {providers?.providers.map((p, i) => (
        <div key={i} className="bg-[#1a1a1a] rounded-xl p-4 border border-[#333]">
          <div className="flex justify-between items-start mb-3">
            <div>
              <h3 className="text-white font-bold text-lg">🧠 {p.name}</h3>
              <div className="flex gap-3 mt-1 text-xs">
                <span className="text-[#8eff71]">{p.win_rate}% win rate</span>
                <span className="text-[#adaaaa]">{p.total_signals} signals</span>
              </div>
            </div>
            <div className="text-right">
              <span className="text-[#8eff71] font-bold text-lg">${p.price_usdc}</span>
              <p className="text-[#494847] text-xs">per signal</p>
            </div>
          </div>
          {stellar.connected ? (
            <button
              onClick={() => backSignal.mutate({ signalId: 1, amount: p.price_usdc })}
              disabled={subscribing}
              className="w-full bg-[#8eff71] text-black py-2.5 rounded-lg font-bold text-sm disabled:opacity-50"
            >
              {subscribing ? '⏳ Signing with Freighter...' : `Back Signal — $${p.price_usdc} USDC`}
            </button>
          ) : (
            <button onClick={stellar.connect} className="w-full bg-[#262626] text-[#adaaaa] py-2.5 rounded-lg text-sm border border-[#333]">
              Connect wallet to back signals
            </button>
          )}
          <p className="text-center text-[#494847] text-xs mt-2">Refunded automatically if signal is wrong</p>
        </div>
      ))}

      {/* Active Escrows */}
      {stellar.connected && escrows?.escrows && escrows.escrows.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-white font-bold text-sm">Your Backed Signals</h3>
          {escrows.escrows.map((e: any) => (
            <div key={e.id} className="bg-[#131313] rounded-lg p-3 border border-[#222]">
              <div className="flex justify-between items-center">
                <div>
                  <span className="text-white text-sm font-medium">{e.token_symbol} {e.verdict}</span>
                  <span className="text-[#adaaaa] text-xs ml-2">${e.amount_usdc} USDC</span>
                </div>
                <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                  e.status === 'resolved' ? 'bg-[#8eff71]/10 text-[#8eff71]' :
                  e.status === 'refunded' ? 'bg-[#ff7166]/10 text-[#ff7166]' :
                  'bg-yellow-400/10 text-yellow-400'
                }`}>
                  {e.status === 'funded' ? '⏳ Pending' : e.status === 'resolved' ? '✅ Paid' : '↩️ Refunded'}
                </span>
              </div>
              {e.evidence && <p className="text-[#494847] text-xs mt-1">{e.evidence}</p>}
            </div>
          ))}
        </div>
      )}

      {/* Premium Reports */}
      <div className="space-y-3 pt-4 border-t border-[#333]">
        <div className="text-center space-y-1">
          <h3 className="text-white font-bold text-lg">📊 Premium Reports</h3>
          <p className="text-[#adaaaa] text-xs">Pay via Stellar escrow → Get AI-generated market intelligence</p>
        </div>

        {[
          { key: 'market_overview', icon: '🌐', name: 'Market Overview', price: 2, desc: 'Top signals, ETF flows, sentiment' },
          { key: 'token_deep_dive', icon: '🔬', name: 'Token Deep Dive', price: 5, desc: 'Multi-agent analysis on top token' },
          { key: 'portfolio_advisory', icon: '💼', name: 'Portfolio Advisory', price: 10, desc: 'Allocation + risk assessment' },
        ].map(rt => (
          <div key={rt.key} className="bg-[#1a1a1a] rounded-xl p-4 border border-[#333]">
            <div className="flex justify-between items-center">
              <div>
                <h4 className="text-white font-bold text-sm">{rt.icon} {rt.name}</h4>
                <p className="text-[#494847] text-xs">{rt.desc}</p>
              </div>
              <button
                onClick={async () => {
                  if (!stellar.connected) { stellar.connect(); return; }
                  setBuyingReport(rt.key);
                  setTxSteps([
                    { label: 'Deploy escrow', status: 'pending' },
                    { label: 'Sign & fund', status: 'idle' },
                    { label: 'Generate report', status: 'idle' },
                  ]);
                  try {
                    // Step 1: Deploy (platform signs server-side)
                    const r1 = await fetch(`${BASE}/reports/purchase`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ report_type: rt.key, buyer_stellar: stellar.address }),
                    });
                    const d1 = await r1.json();
                    if (!r1.ok) throw new Error(d1.detail || d1.message || 'Deploy failed');

                    setTxSteps(prev => prev.map((s, i) =>
                      i === 0 ? { ...s, status: 'success', txHash: d1.tx_hash, explorerUrl: d1.explorer_url } :
                      i === 1 ? { ...s, status: 'pending' } : s
                    ));

                    // Step 2: Fund escrow (user signs with Freighter)
                    let signedXdr = '';
                    try {
                      // Get fund XDR from Trustless Work
                      const fundResp = await fetch(`${BASE}/marketplace/submit-tx`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: 'get_fund_xdr', escrow_address: d1.escrow_address, signer: stellar.address }),
                      });
                      // If fund XDR available, sign it
                      if (fundResp.ok) {
                        const fundData = await fundResp.json();
                        if (fundData.unsigned_xdr) {
                          signedXdr = await stellar.signXdr(fundData.unsigned_xdr);
                        }
                      }
                    } catch {
                      // Freighter not available or user rejected — proceed without fund
                    }

                    setTxSteps(prev => prev.map((s, i) =>
                      i === 1 ? { ...s, status: 'success' } :
                      i === 2 ? { ...s, status: 'pending' } : s
                    ));

                    // Step 3: Confirm + generate report
                    const r2 = await fetch(`${BASE}/reports/confirm`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ escrow_id: d1.escrow_id, signed_xdr: signedXdr }),
                    });
                    const d2 = await r2.json();

                    if (d2.error) {
                      setTxSteps(prev => prev.map((s, i) =>
                        i === 1 ? { ...s, status: 'error', error: d2.hint || d2.message } : s
                      ));
                      return;
                    }

                    if (d2.report) {
                      setTxSteps(prev => prev.map((s, i) =>
                        i === 2 ? { ...s, status: 'success', txHash: d2.fund_tx_hash, explorerUrl: d2.fund_explorer_url } : s
                      ));
                      setTimeout(() => setReportModal(d2.report), 500);
                    } else {
                      throw new Error(d2.detail || 'Generation failed');
                    }
                  } catch (e: any) {
                    setTxSteps(prev => prev.map(s => s.status === 'pending' ? { ...s, status: 'error', error: e.message } : s));
                  } finally {
                    setTimeout(() => setBuyingReport(null), 2000);
                  }
                }}
                disabled={!!buyingReport}
                className="bg-[#bf81ff] text-white px-4 py-2 rounded-lg font-bold text-sm whitespace-nowrap disabled:opacity-50"
              >
                {buyingReport === rt.key ? '⏳...' : `$${rt.price}`}
              </button>
            </div>

            {/* Tx Steps for this report type */}
            {buyingReport === rt.key && txSteps.length > 0 && (
              <div className="mt-3 bg-[#131313] rounded-lg p-3 space-y-2">
                {txSteps.map((step, i) => (
                  <div key={i} className="space-y-1">
                    <div className="flex items-center gap-2 text-xs">
                      <span className={
                        step.status === 'success' ? 'text-[#8eff71]' :
                        step.status === 'error' ? 'text-[#ff7166]' :
                        step.status === 'pending' ? 'text-[#bf81ff] animate-pulse' :
                        'text-[#494847]'
                      }>
                        {step.status === 'success' ? '✓' : step.status === 'error' ? '✗' : step.status === 'pending' ? '◉' : '○'}
                      </span>
                      <span className="text-[#adaaaa]">{step.label}</span>
                    </div>
                    {step.txHash && (
                      <a href={step.explorerUrl || `https://stellar.expert/explorer/testnet/tx/${step.txHash}`}
                         target="_blank" rel="noopener noreferrer"
                         className="text-[10px] text-[#8eff71] ml-5 flex items-center gap-1 hover:underline">
                        {step.txHash.slice(0, 12)}...{step.txHash.slice(-6)}
                        <span className="material-symbols-outlined text-[10px]">open_in_new</span>
                      </a>
                    )}
                    {step.error && <div className="text-[10px] text-[#ff7166] ml-5">{step.error}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Report Modal */}
      {reportModal && <ReportModal report={reportModal} onClose={() => setReportModal(null)} />}
    </div>
  );
}
