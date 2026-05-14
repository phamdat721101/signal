import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { config } from '../config';
import { useStellarWallet } from '../hooks/useStellarWallet';

const BASE = `${config.backendUrl}/api/v2/agent`;

export default function Marketplace() {
  const stellar = useStellarWallet();
  const [subscribing, setSubscribing] = useState(false);
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
        const r = await fetch(`${BASE}/marketplace/subscribe`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ subscriber_stellar: stellar.address, signal_id: signalId, amount_usdc: amount }),
        });
        const data = await r.json();
        if (data.unsigned_xdr) {
          await stellar.signXdr(data.unsigned_xdr);
          qc.invalidateQueries({ queryKey: ['marketplace-escrows'] });
        }
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
    </div>
  );
}
