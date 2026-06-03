// import { usePrivy } from '@privy-io/react-auth';
import { useQuery } from '@tanstack/react-query';
import { config, shareToX, explorerTxUrl, normalizeAddress, isXLayer } from '../config';
import { useSession } from '../hooks/useSession';
import { useIUSDBalance } from '../hooks/useIUSDBalance';
import { useConviction } from '../hooks/useConviction';
import { useWallet } from '../hooks/useWallet';
import CardHand from '../components/CardHand';

// ── Persona + mood (pure derive — single responsibility, inlined per scope) ──
type Persona = { emoji: string; name: string; color: string; tagline: string };

function derivePersona(opts: {
  total: number; wins: number; convTotal: number; convCorrect: number;
  bestStreak: number; rep: number; achievements: number;
}): Persona {
  const { total, wins, convTotal, convCorrect, bestStreak, rep, achievements } = opts;
  const accuracy = total > 0 ? (wins / total) * 100 : 0;
  const convAcc  = convTotal > 0 ? (convCorrect / convTotal) * 100 : 0;
  // Highest tier wins; check from top down so promotion is sticky.
  if (achievements >= 3 || rep >= 5000 || (total >= 30 && accuracy >= 70))
    return { emoji: '🐉', name: 'Conviction Sage', color: '#bf81ff',
             tagline: 'You read the tape before it printed.' };
  if (bestStreak >= 5 || convAcc >= 65)
    return { emoji: '🪨', name: 'Diamond Hands', color: '#8eff71',
             tagline: 'Held when the timeline screamed.' };
  if (total >= 20 || rep >= 100)
    return { emoji: '🐺', name: 'Lone Apex', color: '#8eff71',
             tagline: 'Your conviction has volume.' };
  if (total >= 5)
    return { emoji: '🐒', name: 'Curious Ape', color: '#ffb84d',
             tagline: 'You smell alpha — keep sniffing.' };
  return { emoji: '🌱', name: 'Fresh Mind', color: '#adaaaa',
           tagline: 'Your first APE writes the chain.' };
}

function deriveMood(opts: { total: number; wins: number; curStreak: number }): string {
  const { total, wins, curStreak } = opts;
  if (total === 0)              return 'Your first APE writes the chain.';
  if (curStreak >= 5)           return "Don't let euphoria pick your next swipe.";
  if (curStreak >= 3)           return 'Hot. Quiet. Disciplined.';
  if (total > 0 && wins === 0)  return 'Even diamonds were carbon once.';
  return 'Patience is alpha.';
}

export default function Profile() {
  const { address: walletAddr, isCorrectChain, isConnected, chainId } = useWallet();
  const address = normalizeAddress(walletAddr);
  const {
    claimFaucet, approveAndDeposit, closeSession, clearSteps,
    loading, error, steps, iusdBalance,
    iusdCooldownSeconds, mockIUSDConfigured,
  } = useSession();
  // Show what's locked in active SessionVault sessions — fixes the "where did
  // my 10 iUSD go?" UX gap after a deposit succeeds.
  const { sessionFormatted: vaultLockedFmt, sessionBalance: vaultLockedRaw } = useIUSDBalance();
  const { data: convictionData } = useConviction(address);

  const { data } = useQuery({
    queryKey: ['profile', address],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/profile/${address}`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json();
    },
    enabled: !!address,
  });

  // SoDex testnet pool balance — shared trading liquidity behind the
  // ⚡ Execute action on trading_signal cards. Hidden entirely when the
  // backend reports SoDex disabled (per Design Principle §10.1).
  const { data: sodexPool } = useQuery({
    queryKey: ['sodex-pool'],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/sodex/pool`);
      if (!resp.ok) return { enabled: false };
      return resp.json() as Promise<{
        enabled: boolean;
        balance?: string | null;
        free_margin?: string | null;
        chain?: string;
        updated_at?: number;
      }>;
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
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

  // Persona + mood — pure derivation from already-fetched data
  const persona = derivePersona({
    total:        summary.total_trades || 0,
    wins:         rewards.wins || 0,
    convTotal:    convictionData?.total_convictions || 0,
    convCorrect:  convictionData?.correct_calls || 0,
    bestStreak:   Math.max(rewards.bestStreak || 0, convictionData?.best_streak || 0),
    rep:          convictionData?.reputation_score || 0,
    achievements: (achievements.earned || []).length,
  });
  const mood = deriveMood({
    total:     summary.total_trades || 0,
    wins:      rewards.wins || 0,
    curStreak: rewards.currentStreak || 0,
  });

  return (
    <div className="p-5 space-y-5 pb-24">
      {/* Persona + Trading IQ — the vibe header */}
      <div className="text-center py-3">
        <div className="inline-flex items-center gap-2 bg-[#131313] border px-3 py-1 rounded-full mb-2"
             style={{ borderColor: `${persona.color}33` }}>
          <span className="text-base">{persona.emoji}</span>
          <span className="font-headline font-bold text-xs uppercase tracking-widest"
                style={{ color: persona.color }}>{persona.name}</span>
        </div>
        <div className="font-label text-[10px] text-[#bf81ff] uppercase tracking-widest">Trading IQ</div>
        <div className="font-headline text-5xl font-black text-[#8eff71]">{iq}</div>
        <div className="font-label text-[11px] text-[#adaaaa] mt-1 italic">{persona.tagline}</div>
        <div className="font-label text-[10px] text-[#494847] mt-1">{address.slice(0, 6)}...{address.slice(-4)}</div>
        <div className="font-label text-[10px] text-[#adaaaa] mt-3">{mood}</div>
        <button onClick={() => shareToX(
          `${persona.emoji} ${persona.name} on @KineticApp — Trading IQ ${iq} 🧠 ${persona.tagline} #ApeOrFade`
        )} className="mt-3 bg-[#262626] px-4 py-2 rounded-lg text-[#adaaaa] font-label text-xs flex items-center gap-2 mx-auto">
          <span className="material-symbols-outlined text-sm">share</span>
          Share Trading IQ
        </button>
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

      {/* Card Hand — X Layer SignalCardNFT collection (Hook the Future). */}
      {/* Renders nothing on Initia; CardHand handles the chain check internally. */}
      <CardHand address={address} chainId={chainId ?? 0} />

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

      {/* On-Chain Reputation — always shown; empty-state nudges first commit */}
      <div className="bg-[#131313] rounded-xl p-4 border border-[#bf81ff]/10">
        <div className="flex justify-between items-center mb-3">
          <h2 className="font-headline font-bold text-sm text-white">On-Chain Reputation</h2>
          <span className="text-[9px] font-label text-[#494847]">verified on-chain ✓</span>
        </div>
        {convictionData && convictionData.total_convictions > 0 ? (
          <>
            <div className="grid grid-cols-3 gap-2 mb-3">
              <div className="text-center">
                <div className={`font-headline text-xl font-bold ${(convictionData.reputation_score || 0) >= 0 ? 'text-[#bf81ff]' : 'text-[#ff7166]'}`}>
                  {convictionData.reputation_score || 0}
                </div>
                <div className="font-label text-[8px] text-[#adaaaa] uppercase">Rep Score</div>
              </div>
              <div className="text-center">
                <div className="font-headline text-xl font-bold text-[#8eff71]">{convictionData.accuracy || 0}%</div>
                <div className="font-label text-[8px] text-[#adaaaa] uppercase">Accuracy</div>
              </div>
              <div className="text-center">
                <div className="font-headline text-xl font-bold text-white">{convictionData.total_convictions || 0}</div>
                <div className="font-label text-[8px] text-[#adaaaa] uppercase">Convictions</div>
              </div>
            </div>
            <button onClick={() => shareToX(
              `My on-chain reputation: ${convictionData.reputation_score} REP | ${convictionData.accuracy}% accuracy | ${convictionData.best_streak} best streak 🧠 Verified on @KineticApp #ProofOfConviction`
            )} className="w-full bg-[#bf81ff]/10 border border-[#bf81ff]/20 py-2 rounded-lg text-[#bf81ff] font-headline font-bold text-xs flex items-center justify-center gap-2">
              <span className="material-symbols-outlined text-sm">share</span>
              Share Reputation
            </button>
          </>
        ) : (
          <div className="text-center py-2">
            <div className="font-label text-[11px] text-[#adaaaa] mb-1">No convictions yet</div>
            <div className="font-label text-[10px] text-[#494847]">
              Your next swipe writes a verifiable, slashing-grade conviction on-chain.
            </div>
          </div>
        )}
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
                <button onClick={() => shareToX(`I earned ${t.name} ${t.emoji} on @KineticApp — on-chain proof. #ApeOrFade`)}
                  className="bg-[#262626] px-2 py-1 rounded text-[10px] text-[#adaaaa] flex items-center gap-1">
                  <span className="material-symbols-outlined text-[12px]">share</span>Share
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* SoDex Trading Pool — shared testnet liquidity backing ⚡ Execute.
          Hidden when SoDex is disabled (no naked empty state). */}
      {sodexPool?.enabled && (
        <div>
          <div className="flex justify-between items-center mb-2">
            <h2 className="font-headline font-bold text-sm text-white">SoDex Trading Pool</h2>
            <span className="font-label text-[9px] text-[#494847] uppercase tracking-widest">
              {sodexPool.chain || 'sodex-testnet'}
            </span>
          </div>
          <div className="bg-[#0e1a0e] border border-[#8eff71]/30 rounded-xl p-4">
            <div className="flex items-end justify-between">
              <div>
                <div className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest mb-1">
                  Pool USDC
                </div>
                <div className="font-headline text-3xl font-black text-[#8eff71]">
                  {sodexPool.balance != null
                    ? Number(sodexPool.balance).toLocaleString(undefined, { maximumFractionDigits: 2 })
                    : '—'}
                  <span className="text-sm text-[#adaaaa] ml-1">vUSDC</span>
                </div>
              </div>
              <div className="text-right">
                <div className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest mb-1">
                  Free margin
                </div>
                <div className="font-headline font-bold text-sm text-white">
                  {sodexPool.free_margin != null
                    ? Number(sodexPool.free_margin).toLocaleString(undefined, { maximumFractionDigits: 2 })
                    : '—'} vUSDC
                </div>
              </div>
            </div>
            <div className="mt-3 font-label text-[10px] text-[#494847] italic">
              Shared liquidity for ⚡ Execute on Trading Signal cards.
            </div>
          </div>
        </div>
      )}

      {/* Wallet — Initia-only (faucet + SessionVault). Hidden on X Layer
          where Summon LP pays per-card from the connected wallet directly. */}
      {!isXLayer(chainId) && (
      <div>
        <div className="flex justify-between items-center mb-2">
          <h2 className="font-headline font-bold text-sm text-white">Wallet</h2>
          <div className="font-headline font-bold text-[#8eff71] text-sm">
            {iusdBalance ? `${Number(iusdBalance).toLocaleString(undefined, { maximumFractionDigits: 0 })} iUSD` : '— iUSD'}
          </div>
        </div>
        {vaultLockedRaw > 0n && (
          <div className="flex justify-between items-center -mt-1 mb-2 text-[11px]">
            <span className="text-[#adaaaa]">+ locked in active session</span>
            <span className="text-[#bf81ff] font-bold">
              {Number(vaultLockedFmt).toLocaleString(undefined, { maximumFractionDigits: 2 })} iUSD
            </span>
          </div>
        )}
        <div className="space-y-2">
          {(() => {
            const iusdDisabled = loading || !isConnected || !isCorrectChain || iusdCooldownSeconds > 0 || !mockIUSDConfigured;
            const iusdLabel =
              !isConnected ? 'Connect wallet to claim'
              : !isCorrectChain ? 'Switch to evm-1 first'
              : !mockIUSDConfigured ? 'Faucet unavailable'
              : iusdCooldownSeconds > 0 ? `Try again in ${Math.floor(iusdCooldownSeconds / 60)}m ${iusdCooldownSeconds % 60}s`
              : loading && steps[0]?.label.includes('faucet') ? 'Claiming...'
              : 'Claim 1000 iUSD (Testnet Faucet)';
            return (
              <button onClick={() => { clearSteps(); claimFaucet(); }} disabled={iusdDisabled}
                className="w-full bg-[#262626] text-[#8eff71] font-headline font-bold py-3 rounded-lg disabled:opacity-50 active:scale-95 transition-transform">
                {iusdLabel}
              </button>
            );
          })()}
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
      )}
    </div>
  );
}
