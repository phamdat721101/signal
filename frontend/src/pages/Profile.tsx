import { usePrivy } from '@privy-io/react-auth';
import { useQuery } from '@tanstack/react-query';
import { config, shareToX, explorerTxUrl } from '../config';
import { useSession } from '../hooks/useSession';

export default function Profile() {
  const { user } = usePrivy();
  const address = user?.wallet?.address || '';
  const { claimFaucet, approveAndDeposit, closeSession, clearSteps, loading, error, steps, iusdBalance } = useSession();

  const { data } = useQuery({
    queryKey: ['profile', address],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/profile/${address}`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json();
    },
    enabled: !!address,
  });

  if (!address) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6">
        <span className="material-symbols-outlined text-6xl text-[#494847]">person</span>
        <p className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">Connect wallet to view profile</p>
      </div>
    );
  }

  const rewards = data?.rewards || {};
  const achievements = data?.achievements || {};
  const summary = data?.summary || {};
  const iq = data?.trading_iq || 0;

  return (
    <div className="p-5 space-y-5 pb-24">
      {/* Trading IQ */}
      <div className="text-center py-4">
        <div className="font-label text-[10px] text-[#bf81ff] uppercase tracking-widest mb-1">Trading IQ</div>
        <div className="font-headline text-5xl font-black text-[#8eff71]">{iq}</div>
        <div className="font-label text-[10px] text-[#adaaaa] mt-1">{address.slice(0, 6)}...{address.slice(-4)}</div>
      </div>

      {/* Streak */}
      <div className="flex justify-center gap-8">
        <div className="text-center">
          <div className="font-headline text-2xl font-bold text-[#ff7166]">🔥 {rewards.currentStreak || 0}</div>
          <div className="font-label text-[9px] text-[#adaaaa] uppercase">Current Streak</div>
        </div>
        <div className="text-center">
          <div className="font-headline text-2xl font-bold text-white">{rewards.bestStreak || 0}</div>
          <div className="font-label text-[9px] text-[#adaaaa] uppercase">Best Streak</div>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-2">
        {[
          ['Trades', summary.total_trades || 0, 'white'],
          ['Wins', rewards.wins || 0, '#8eff71'],
          ['Win %', `${rewards.winRate || 0}%`, '#8eff71'],
          ['PnL', `$${(summary.total_pnl_usd || 0).toFixed(0)}`, (summary.total_pnl_usd || 0) >= 0 ? '#8eff71' : '#ff7166'],
        ].map(([label, val, color]) => (
          <div key={label as string} className="bg-[#262626] p-3 rounded-xl text-center">
            <div className="font-headline text-lg font-bold" style={{ color: color as string }}>{val}</div>
            <div className="font-label text-[8px] text-[#adaaaa] uppercase">{label}</div>
          </div>
        ))}
      </div>

      {/* Achievements */}
      {(achievements.earned || []).length > 0 && (
        <div>
          <h2 className="font-headline font-bold text-sm text-white mb-2">Achievements</h2>
          <div className="flex flex-wrap gap-2">
            {(achievements.earned || []).map((t: any) => (
              <div key={t.tier} className="bg-[#131313] px-3 py-2 rounded-lg flex items-center gap-2 border border-[#494847]/20">
                <span className="text-lg">{t.emoji}</span>
                <span className="font-label text-xs text-white">{t.name}</span>
                <button onClick={() => shareToX(`I earned ${t.name} ${t.emoji} on @KineticApp — on-chain proof. #ApeOrFade`)} className="ml-1">
                  <span className="material-symbols-outlined text-[12px] text-[#494847]">share</span>
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Wallet */}
      <div>
        <div className="flex justify-between items-center mb-2">
          <h2 className="font-headline font-bold text-sm text-white">Wallet</h2>
          <div className="font-headline font-bold text-[#8eff71] text-sm">
            {iusdBalance ? `${Number(iusdBalance).toLocaleString(undefined, { maximumFractionDigits: 0 })} iUSD` : '— iUSD'}
          </div>
        </div>
        <div className="space-y-2">
          <button onClick={() => { clearSteps(); claimFaucet(); }} disabled={loading}
            className="w-full bg-[#262626] text-[#8eff71] font-headline font-bold py-3 rounded-lg disabled:opacity-50 active:scale-95 transition-transform">
            {loading && steps[0]?.label.includes('faucet') ? 'Claiming...' : 'Claim 1000 iUSD (Testnet Faucet)'}
          </button>
          <button onClick={() => { clearSteps(); approveAndDeposit('10', 24); }} disabled={loading}
            className="w-full ape-gradient text-[#0b5800] font-headline font-bold py-3 rounded-lg disabled:opacity-50 active:scale-95 transition-transform">
            {loading && steps[0]?.label.includes('Approve') ? 'Depositing...' : 'Deposit 10 iUSD (24h Session)'}
          </button>
          <button onClick={() => { clearSteps(); closeSession(); }} disabled={loading}
            className="w-full bg-[#262626] border border-[#ff7166]/30 text-[#ff7166] font-headline font-bold py-3 rounded-lg disabled:opacity-50 active:scale-95 transition-transform">
            {loading && steps[0]?.label.includes('session') ? 'Withdrawing...' : 'Withdraw (Close Session)'}
          </button>
        </div>

        {/* Transaction Steps */}
        {steps.length > 0 && (
          <div className="mt-3 bg-[#131313] rounded-lg p-3 space-y-2">
            {steps.map((s, i) => (
              <div key={i} className="space-y-1">
                <div className="flex items-center gap-2 text-xs">
                  <span className={
                    s.status === 'success' ? 'text-[#8eff71]' :
                    s.status === 'error' ? 'text-[#ff7166]' :
                    s.status === 'pending' ? 'text-[#bf81ff] animate-pulse' : 'text-[#494847]'
                  }>
                    {s.status === 'success' ? '✓' : s.status === 'error' ? '✗' : s.status === 'pending' ? '◉' : '○'}
                  </span>
                  <span className="text-[#adaaaa]">{s.label}</span>
                </div>
                {s.txHash && (
                  <a href={explorerTxUrl(s.txHash)} target="_blank" rel="noopener noreferrer"
                    className="text-[10px] text-[#8eff71] ml-5 flex items-center gap-1 hover:underline">
                    {s.txHash.slice(0, 10)}...{s.txHash.slice(-6)}
                    <span className="material-symbols-outlined text-[10px]">open_in_new</span>
                  </a>
                )}
                {s.error && <div className="text-[10px] text-[#ff7166] ml-5">{s.error}</div>}
              </div>
            ))}
          </div>
        )}

        {/* Global error */}
        {error && !steps.some(s => s.error) && (
          <div className="mt-2 bg-[#ff7166]/10 border border-[#ff7166]/20 p-2 rounded-lg">
            <div className="text-[#ff7166] text-xs">{error}</div>
          </div>
        )}
      </div>
    </div>
  );
}
