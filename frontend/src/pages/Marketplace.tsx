import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { config } from '../config';
import { useStellarWallet } from '../hooks/useStellarWallet';

const BASE = `${config.backendUrl}/api/v2/agent`;

export default function Marketplace() {
  const stellar = useStellarWallet();
  const [subscribing, setSubscribing] = useState(false);

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

  const subscribe = useMutation({
    mutationFn: async ({ signalId, amount }: { signalId: number; amount: number }) => {
      setSubscribing(true);
      const r = await fetch(`${BASE}/marketplace/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ subscriber_stellar: stellar.address, signal_id: signalId, amount_usdc: amount }),
      });
      const data = await r.json();
      if (data.unsigned_xdr) {
        await stellar.signXdr(data.unsigned_xdr);
      }
      setSubscribing(false);
      return data;
    },
  });

  return (
    <div className="px-4 py-6 space-y-6 max-w-lg mx-auto">
      <div className="flex justify-between items-center">
        <h2 className="text-xl font-black text-white">🏪 Signal Marketplace</h2>
        {stellar.connected ? (
          <button onClick={stellar.disconnect} className="text-xs bg-[#1a1a1a] px-3 py-1.5 rounded-lg text-[#8eff71] border border-[#8eff71]/20">
            {stellar.address.slice(0, 6)}...{stellar.address.slice(-4)}
          </button>
        ) : (
          <button onClick={stellar.connect} className="text-xs bg-[#8eff71] px-3 py-1.5 rounded-lg text-black font-bold">
            Connect Stellar
          </button>
        )}
      </div>

      {/* Providers */}
      {providers?.providers.map((p, i) => (
        <div key={i} className="bg-[#1a1a1a] rounded-xl p-4 border border-[#333]">
          <div className="flex justify-between items-start">
            <div>
              <h3 className="text-white font-bold">🧠 {p.name}</h3>
              <p className="text-[#adaaaa] text-sm mt-1">
                Win Rate: {p.win_rate}% | Signals: {p.total_signals} | Avg PnL: {p.avg_pnl > 0 ? '+' : ''}{p.avg_pnl}%
              </p>
            </div>
            <span className="text-[#8eff71] font-bold">${p.price_usdc}</span>
          </div>
          {stellar.connected && (
            <button
              onClick={() => subscribe.mutate({ signalId: 1, amount: p.price_usdc })}
              disabled={subscribing}
              className="mt-3 w-full bg-[#8eff71]/10 border border-[#8eff71]/30 text-[#8eff71] py-2 rounded-lg font-bold text-sm disabled:opacity-50"
            >
              {subscribing ? 'Signing...' : `Subscribe $${p.price_usdc} USDC`}
            </button>
          )}
        </div>
      ))}

      {/* Active Escrows */}
      {stellar.connected && escrows?.escrows && escrows.escrows.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-white font-bold text-sm uppercase tracking-wider">Your Escrows</h3>
          {escrows.escrows.map((e: any) => (
            <div key={e.id} className="bg-[#131313] rounded-lg p-3 border border-[#222]">
              <div className="flex justify-between">
                <span className="text-white text-sm font-medium">
                  {e.token_symbol} {e.verdict} | ${e.amount_usdc}
                </span>
                <span className={`text-xs font-bold ${e.status === 'resolved' ? 'text-[#8eff71]' : e.status === 'refunded' ? 'text-[#ff7166]' : 'text-yellow-400'}`}>
                  {e.status.toUpperCase()}
                </span>
              </div>
              {e.evidence && <p className="text-[#adaaaa] text-xs mt-1">{e.evidence}</p>}
            </div>
          ))}
        </div>
      )}

      {!stellar.connected && (
        <p className="text-center text-[#adaaaa] text-sm">Connect your Stellar wallet to subscribe to signals</p>
      )}
    </div>
  );
}
