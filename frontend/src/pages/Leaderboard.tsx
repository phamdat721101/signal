import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { usePrivy } from '@privy-io/react-auth';
import { config, shareToX, normalizeAddress } from '../config';
import { useConvictionLeaderboard } from '../hooks/useConviction';

export default function Leaderboard() {
  const { user } = usePrivy();
  const myAddress = normalizeAddress(user?.wallet?.address || '');
  const [tab, setTab] = useState<'reputation' | 'pnl'>('reputation');

  const { data, isLoading } = useQuery({
    queryKey: ['leaderboard'],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/leaderboard`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json() as Promise<{ leaderboard: any[] }>;
    },
  });

  const entries = data?.leaderboard ?? [];
  const myRank = entries.findIndex(e => (e.user_address || '').toLowerCase() === myAddress) + 1;
  const { data: convictionLb } = useConvictionLeaderboard();
  const repEntries = convictionLb?.leaderboard ?? [];

  const renderPnlEntry = (entry: any, i: number) => {
    const addr = entry.user_address || '';
    const pnl = entry.total_pnl_usd ?? entry.apes ?? 0;
    const hasPnl = entry.total_pnl_usd !== undefined;
    const pnlColor = pnl >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]';
    const isMe = addr.toLowerCase() === myAddress;
    return (
      <div key={addr} className={`bg-[#131313] p-4 rounded-xl flex items-center gap-4 ${isMe ? 'border border-[#bf81ff]/30' : ''}`}>
        <div className={"w-10 h-10 rounded-lg flex items-center justify-center font-headline font-black text-lg " + (
          i === 0 ? 'bg-[#8eff71]/20 text-[#8eff71]' : i === 1 ? 'bg-[#bf81ff]/20 text-[#bf81ff]' : i === 2 ? 'bg-[#ff7166]/20 text-[#ff7166]' : 'bg-[#262626] text-[#adaaaa]'
        )}>
          {i + 1}
        </div>
        <div className="flex-1 min-w-0">
          <div className="font-headline font-bold text-white text-sm truncate">
            {entry.username ? <span className="text-[#8eff71]">{entry.username}.init</span> : addr ? `${addr.slice(0, 6)}...${addr.slice(-4)}` : 'Anon'}
            {isMe && <span className="text-[#bf81ff] text-[10px] ml-1">(you)</span>}
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className="font-label text-[10px] text-[#adaaaa]">{entry.total_trades} trades</span>
            {hasPnl && entry.win_rate > 0 && (
              <span className="text-[9px] font-label font-bold px-2 py-0.5 rounded bg-[#8eff71]/10 text-[#8eff71] border border-[#8eff71]/20">
                {Math.round(entry.win_rate)}% win
              </span>
            )}
          </div>
        </div>
        <div className="text-right flex items-center gap-2">
          <div>
            {hasPnl ? (
              <>
                <div className={"font-headline font-bold text-sm " + pnlColor}>
                  {pnl >= 0 ? '+' : ''}{Number(pnl).toFixed(2)} USD
                </div>
                <div className={"font-label text-[10px] " + pnlColor}>
                  {(entry.total_pnl_pct ?? 0) >= 0 ? '+' : ''}{Number(entry.total_pnl_pct ?? 0).toFixed(1)}%
                </div>
              </>
            ) : (
              <div className="font-headline font-bold text-[#8eff71] text-sm">{entry.apes} apes</div>
            )}
          </div>
          <button onClick={() => shareToX(
            `#${i + 1} on @KineticApp 🏆 ${hasPnl ? `${pnl >= 0 ? '+' : ''}${Number(pnl).toFixed(2)} USD` : `${entry.apes} apes`} #ApeOrFade`
          )} className="p-1">
            <span className="material-symbols-outlined text-[14px] text-[#494847]">share</span>
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="p-5 space-y-4">
      <div className="text-center py-4">
        <h1 className="font-headline text-2xl font-black text-white tracking-tight">ALPHA LEADERBOARD</h1>
        <p className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest mt-1">Top traders by {tab === 'reputation' ? 'on-chain reputation' : 'profit'}</p>
      </div>

      <div className="flex gap-2">
        <button onClick={() => setTab('reputation')}
          className={`flex-1 py-2 rounded-lg font-headline font-bold text-sm ${tab === 'reputation' ? 'bg-[#bf81ff]/20 text-[#bf81ff] border border-[#bf81ff]/30' : 'bg-[#262626] text-[#adaaaa]'}`}>
          🧠 Reputation
        </button>
        <button onClick={() => setTab('pnl')}
          className={`flex-1 py-2 rounded-lg font-headline font-bold text-sm ${tab === 'pnl' ? 'bg-[#8eff71]/20 text-[#8eff71] border border-[#8eff71]/30' : 'bg-[#262626] text-[#adaaaa]'}`}>
          💰 PnL
        </button>
      </div>

      {myRank > 0 && (
        <button onClick={() => shareToX(
          `I'm #${myRank} on the @KineticApp Alpha Leaderboard 🏆 #ApeOrFade`
        )} className="w-full bg-[#bf81ff]/10 border border-[#bf81ff]/20 p-3 rounded-xl text-center text-[#bf81ff] font-headline font-bold text-sm active:scale-95 transition-transform">
          Share My Rank #{myRank} 🏆
        </button>
      )}

      <div className="bg-[#8eff71]/10 border border-[#8eff71]/20 p-3 rounded-xl text-center">
        <div className="font-label text-[9px] text-[#8eff71] uppercase tracking-widest">
          {tab === 'reputation' ? 'On-Chain Verified' : 'Weekly Competition'}
        </div>
        <div className="text-[#adaaaa] text-xs mt-1">
          {tab === 'reputation' ? 'Reputation scores computed entirely on-chain. Verifiable by anyone.' : 'Rankings reset every Monday. Top 3 earn bonus iUSD.'}
        </div>
      </div>

      {tab === 'reputation' && (
        repEntries.length === 0 ? (
          <div className="bg-[#131313] rounded-xl p-12 text-center">
            <span className="text-5xl mb-3 block">🧠</span>
            <p className="text-[#494847] text-sm">No convictions yet. Ape a card to commit your first conviction.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {repEntries.map((entry: any, i: number) => {
              const addr = entry.address || '';
              const score = entry.reputationScore ?? 0;
              const isMe = addr.toLowerCase() === myAddress;
              return (
                <div key={addr} className={`bg-[#131313] p-4 rounded-xl flex items-center gap-4 ${isMe ? 'border border-[#bf81ff]/30' : ''}`}>
                  <div className={"w-10 h-10 rounded-lg flex items-center justify-center font-headline font-black text-lg " + (
                    i === 0 ? 'bg-[#bf81ff]/20 text-[#bf81ff]' : i === 1 ? 'bg-[#8eff71]/20 text-[#8eff71]' : i === 2 ? 'bg-[#ff7166]/20 text-[#ff7166]' : 'bg-[#262626] text-[#adaaaa]'
                  )}>
                    {i + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-headline font-bold text-white text-sm truncate">
                      {entry.username ? <span className="text-[#bf81ff]">{entry.username}.init</span> : `${addr.slice(0, 6)}...${addr.slice(-4)}`}
                      {isMe && <span className="text-[#bf81ff] text-[10px] ml-1">(you)</span>}
                    </div>
                    <span className="text-[9px] font-label text-[#494847]">on-chain verified ✓</span>
                  </div>
                  <div className="text-right flex items-center gap-2">
                    <div className={`font-headline font-bold text-sm ${score >= 0 ? 'text-[#bf81ff]' : 'text-[#ff7166]'}`}>
                      {score >= 0 ? '+' : ''}{score} REP
                    </div>
                    <button onClick={() => shareToX(
                      `#${i + 1} on @KineticApp Reputation Leaderboard 🧠 ${score} REP (on-chain verified) #ProofOfConviction`
                    )} className="p-1">
                      <span className="material-symbols-outlined text-[14px] text-[#494847]">share</span>
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )
      )}

      {tab === 'pnl' && (
        isLoading ? (
          <div className="text-center text-[#adaaaa] font-label text-sm py-12">Loading...</div>
        ) : entries.length === 0 ? (
          <div className="bg-[#131313] rounded-xl p-12 text-center">
            <span className="material-symbols-outlined text-5xl text-[#494847] mb-3">leaderboard</span>
            <p className="text-[#494847] text-sm">No traders yet. Be the first to ape.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {entries.map(renderPnlEntry)}
          </div>
        )
      )}
    </div>
  );
}
