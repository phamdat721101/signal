import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePrivy } from '@privy-io/react-auth';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createPublicClient, http } from 'viem';
import { useCards } from '../hooks/useCards';
import { config, shareToX, normalizeAddress } from '../config';
import TokenCard from '../components/TokenCard';
import { InsightCard } from '../components/InsightCard';
import { OracleWidget } from '../components/OracleWidget';
import Onboarding from '../components/Onboarding';
import Paywall from '../components/Paywall';
import { useApeTransaction } from '../hooks/useApeTransaction';
import { useSession } from '../hooks/useSession';

const publicClient = createPublicClient({ chain: config.chain, transport: http() });

const WIN_LINES = [
  "The chart whispered. You listened.",
  "Built different.",
  "Your portfolio thanks you.",
  "Sigma move.",
  "The alpha was inside you all along.",
];
const LOSS_LINES = [
  "The market had other plans.",
  "Pain is temporary. Bags are forever.",
  "Even Buffett takes L's.",
  "You faded yourself.",
  "At least it's on-chain forever. 💀",
];

function pickRandom(arr: string[]) { return arr[Math.floor(Math.random() * arr.length)]; }

function fmtPrice(p: number): string {
  if (p >= 1) return `$${p.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  return `$${p.toFixed(6)}`;
}

/* ── Resolution Celebration Modal ── */
function ResolutionModal({ trade, onDismiss }: { trade: any; onDismiss: () => void }) {
  const won = (trade.pnl_usd || 0) > 0;
  const pnl = (trade.pnl_pct || 0).toFixed(1);
  const accent = won ? '#8eff71' : '#ff7166';
  const line = won ? pickRandom(WIN_LINES) : pickRandom(LOSS_LINES);
  const conviction = trade.conviction_score || trade.conviction?.score;
  const shareText = won
    ? `Called $${trade.token_symbol}${conviction ? ` with ${conviction}% conviction` : ''}. +${pnl}% 🧠 On-chain proof. @KineticApp #ProofOfConviction`
    : `Aped $${trade.token_symbol}${conviction ? ` at ${conviction}% conviction` : ''}. ${pnl}%. 😭 @KineticApp #ProofOfConviction`;

  return (
    <div className="fixed inset-0 z-[60] bg-black/90 flex items-center justify-center p-6" onClick={onDismiss}>
      <div className="bg-[#131313] rounded-2xl max-w-sm w-full overflow-hidden" onClick={e => e.stopPropagation()}>
        {/* Top accent bar */}
        <div className="h-1.5" style={{ background: `linear-gradient(90deg, ${accent}, ${accent}88)` }} />

        <div className="p-6 flex flex-col items-center text-center gap-4">
          {/* Emoji */}
          <span className="text-7xl">{won ? '🧠' : '😭'}</span>

          {/* Headline */}
          <h1 className="font-headline text-3xl font-black uppercase" style={{ color: accent }}>
            {won ? 'CALLED IT' : 'REKT'}
          </h1>

          {/* Token + prices */}
          <div className="text-[#adaaaa] text-sm">
            <span className="font-bold text-white">${trade.token_symbol}</span>
            {' '}{fmtPrice(trade.entry_price)} → {fmtPrice(trade.exit_price || trade.entry_price)}
          </div>

          {/* PnL — the big number */}
          <div className="font-headline text-5xl font-black" style={{ color: accent }}>
            {(trade.pnl_pct || 0) >= 0 ? '+' : ''}{pnl}%
          </div>

          {/* Funny line */}
          <p className="text-[#adaaaa] text-sm italic">{line}</p>

          {/* Conviction badge */}
          {conviction && (
            <div className="bg-[#bf81ff]/10 border border-[#bf81ff]/20 px-4 py-2 rounded-lg flex items-center gap-2">
              <span className="font-label text-[9px] text-[#bf81ff] uppercase tracking-widest">Conviction</span>
              <span className="font-headline text-xl font-black text-[#bf81ff]">{conviction}%</span>
              <span className="text-[9px] text-[#494847]">on-chain ✓</span>
            </div>
          )}

          {/* Share button */}
          <button onClick={() => shareToX(shareText)}
            className="w-full font-headline font-bold py-3 rounded-lg flex items-center justify-center gap-2 active:scale-95 transition-transform"
            style={{ backgroundColor: `${accent}20`, color: accent, border: `1px solid ${accent}40` }}>
            <span className="material-symbols-outlined text-lg">share</span>
            {won ? 'Flex on X' : 'Share the Pain'}
          </button>

          {/* Continue */}
          <button onClick={onDismiss}
            className="w-full bg-[#262626] text-[#adaaaa] font-headline font-bold py-3 rounded-lg active:scale-95 transition-transform">
            Continue Swiping
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Conviction Overlay ── */
function ConvictionOverlay({ card, onConfirm, onCancel }: { card: any; onConfirm: () => void; onCancel: () => void }) {
  const score = Math.min(99, Math.max(1, card.risk_score || 70));
  return (
    <div className="fixed inset-0 z-[70] bg-black/90 flex items-center justify-center p-6" onClick={onCancel}>
      <div className="bg-[#131313] rounded-2xl max-w-sm w-full overflow-hidden" onClick={e => e.stopPropagation()}>
        <div className="h-1.5 bg-gradient-to-r from-[#bf81ff] to-[#8eff71]" />
        <div className="p-6 flex flex-col items-center text-center gap-4">
          <span className="text-5xl">🔥</span>
          <h2 className="font-headline text-2xl font-black text-white">COMMIT CONVICTION</h2>
          <p className="text-[#adaaaa] text-sm">
            Your conviction on <span className="text-white font-bold">${card.token_symbol}</span> will be recorded on-chain forever.
          </p>
          <div className="w-full bg-[#262626] rounded-xl p-4">
            <div className="flex justify-between items-center">
              <span className="font-label text-xs text-[#adaaaa] uppercase">Conviction Score</span>
              <span className="font-headline text-3xl font-black text-[#8eff71]">{score}%</span>
            </div>
            <div className="w-full bg-[#0e0e0e] rounded-full h-2 mt-2">
              <div className="h-2 rounded-full bg-gradient-to-r from-[#8eff71] to-[#bf81ff]" style={{ width: `${score}%` }} />
            </div>
            <div className="flex justify-between mt-2 text-[10px] text-[#494847]">
              <span>Low conviction</span><span>Max conviction</span>
            </div>
          </div>
          <div className="text-[10px] text-[#494847]">
            {card.verdict === 'APE' ? '📈 BULLISH' : '📉 BEARISH'} • Auto-resolves in 24h • On-chain proof
          </div>
          <button onClick={onConfirm}
            className="w-full ape-gradient text-[#0b5800] font-headline font-bold py-3 rounded-lg active:scale-95 transition-transform text-lg">
            🔥 COMMIT ON-CHAIN
          </button>
          <button onClick={onCancel}
            className="w-full bg-[#262626] text-[#adaaaa] font-headline font-bold py-2 rounded-lg text-sm">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Swipe Feedback Overlay ── */
function SwipeFeedback({ type }: { type: 'ape' | 'fade' }) {
  const isApe = type === 'ape';
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center pointer-events-none">
      <div className={`absolute inset-0 rounded-xl ${isApe ? 'bg-[#8eff71]/15' : 'bg-[#ff7166]/15'}`} />
      <div className="animate-[scaleIn_0.5s_ease-out] text-center">
        <span className="text-6xl">{isApe ? '🦍' : '💨'}</span>
        <div className={`font-headline text-3xl font-black mt-1 ${isApe ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>
          {isApe ? 'APED!' : 'FADED'}
        </div>
      </div>
    </div>
  );
}

/* ── Main Feed ── */
export default function Feed() {
  const [showOnboarding, setShowOnboarding] = useState(!localStorage.getItem('kinetic_onboarded'));
  const [index, setIndex] = useState(0);
  const [dragX, setDragX] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [exiting, setExiting] = useState<'left' | 'right' | null>(null);
  const startX = useRef(0);
  const [showPaywall, setShowPaywall] = useState(false);
  const [swipeFeedback, setSwipeFeedback] = useState<'ape' | 'fade' | null>(null);
  const [resolvedTrade, setResolvedTrade] = useState<any>(null);
  const [generating, setGenerating] = useState(false);
  const [showConviction, setShowConviction] = useState(false);
  const [pendingCard, setPendingCard] = useState<any>(null);
  const [fundingGas, setFundingGas] = useState(false);

  const { data, isLoading } = useCards(0, 50);
  const { user, login } = usePrivy();
  const initiaAddress = user?.wallet?.address || "";
  const navigate = useNavigate();
  const { apeOnChain } = useApeTransaction();
  const { claimGas } = useSession();
  const queryClient = useQueryClient();

  const evmAddress = normalizeAddress(initiaAddress);

  const { data: balance } = useQuery({
    queryKey: ['balance', evmAddress],
    queryFn: () => publicClient.getBalance({ address: evmAddress as `0x${string}` }),
    enabled: !!evmAddress,
  });

  // Auto-faucet gas for new users
  useEffect(() => {
    if (evmAddress && balance === 0n && !fundingGas) {
      setFundingGas(true);
      fetch(`${config.backendUrl}/api/faucet/gas?address=${evmAddress}`, { method: 'POST' })
        .then(() => queryClient.invalidateQueries({ queryKey: ['balance', evmAddress] }))
        .catch(() => {})
        .finally(() => setFundingGas(false));
    }
  }, [evmAddress, balance]);

  // Resolution detection
  const { data: resolvedData } = useQuery({
    queryKey: ['resolved', evmAddress],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/trades/${evmAddress}/resolved-recent`);
      return resp.ok ? resp.json() : { trades: [] };
    },
    enabled: !!initiaAddress,
    staleTime: 300_000,
  });
  useEffect(() => {
    const trades = resolvedData?.trades || [];
    if (trades.length > 0) setResolvedTrade(trades[0]);
  }, [resolvedData]);

  const cards = data?.cards ?? [];
  const current = cards[index];

  if (showOnboarding) {
    return <Onboarding onComplete={() => { localStorage.setItem('kinetic_onboarded', 'true'); setShowOnboarding(false); login(); }} />;
  }

  const handleApe = async () => {
    if (!current) return;
    setPendingCard(current);
    setShowConviction(true);
  };

  const confirmConviction = async () => {
    const card = pendingCard;
    if (!card) return;
    setShowConviction(false);
    setPendingCard(null);
    setSwipeFeedback('ape');
    const address = evmAddress || '';
    let txHash: string | undefined;
    if (address) {
      try { txHash = (await apeOnChain(card)) || undefined; } catch (e) { console.warn('On-chain ape failed:', e); }
    }
    const resp = await fetch(`${config.backendUrl}/api/cards/${card.id}/ape`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address, tx_hash: txHash }),
    });
    if (resp.status === 402) { setSwipeFeedback(null); setShowPaywall(true); return; }
    const data = await resp.json();
    setTimeout(() => {
      setSwipeFeedback(null);
      navigate(`/trade-success/${card.id}`, { state: { trade: data.trade, conviction: data.conviction } });
    }, 600);
  };

  const handleFade = async () => {
    if (!current) return;
    setSwipeFeedback('fade');
    const address = evmAddress || '';
    const resp = await fetch(`${config.backendUrl}/api/cards/${current.id}/fade`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address }),
    });
    if (resp.status === 402) { setSwipeFeedback(null); setShowPaywall(true); return; }
    setTimeout(() => { setSwipeFeedback(null); setIndex(i => i + 1); }, 400);
  };

  const onDragStart = (clientX: number) => { startX.current = clientX; setDragging(true); };
  const onDragMove = (clientX: number) => { if (dragging) setDragX(clientX - startX.current); };
  const onDragEnd = () => {
    setDragging(false);
    if (dragX > 100) { setExiting('right'); setTimeout(() => { handleApe(); setExiting(null); setDragX(0); }, 300); }
    else if (dragX < -100) { setExiting('left'); setTimeout(() => { handleFade(); setExiting(null); setDragX(0); }, 300); }
    else setDragX(0);
  };

  const generateCards = async () => {
    setGenerating(true);
    try {
      await fetch(`${config.backendUrl}/api/cards/generate`, { method: 'POST' });
      setTimeout(() => { setIndex(0); setGenerating(false); }, 3000);
    } catch { setGenerating(false); }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">Loading feed...</div>
      </div>
    );
  }

  if (!current) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6 text-center">
        <span className="text-6xl">🦍</span>
        <p className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">No more cards</p>
        <p className="text-[#494847] text-xs">Generate fresh AI-powered token cards</p>
        <button onClick={generateCards} disabled={generating}
          className="mt-2 ape-gradient px-6 py-3 rounded-lg text-[#0b5800] font-headline font-bold disabled:opacity-50">
          {generating ? 'Generating...' : '⚡ Generate Cards'}
        </button>
        <button onClick={() => setIndex(0)} className="bg-[#262626] px-6 py-2 rounded-lg text-[#adaaaa] font-label text-sm">
          Refresh Feed
        </button>
      </div>
    );
  }

  // If current card is an insight card, render InsightCard instead
  if (current && current.card_type === 'insight') {
    return (
      <div className="flex flex-col h-full p-4 max-w-md mx-auto">
        <OracleWidget />
        <InsightCard card={current as any} onDismiss={() => setIndex(i => i + 1)} />
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center h-full p-4">
      {showConviction && pendingCard && (
        <ConvictionOverlay card={pendingCard} onConfirm={confirmConviction} onCancel={() => { setShowConviction(false); setPendingCard(null); }} />
      )}
      {showPaywall && <Paywall onDismiss={() => setShowPaywall(false)} />}
      {resolvedTrade && <ResolutionModal trade={resolvedTrade} onDismiss={() => setResolvedTrade(null)} />}
      {fundingGas && (
        <div className="fixed top-16 left-4 right-4 z-50 bg-[#131313] border border-[#8eff71]/20 p-3 rounded-xl text-center">
          <div className="text-sm text-[#8eff71] animate-pulse">⛽ Funding your wallet...</div>
        </div>
      )}
      {evmAddress && balance != null && balance > 0n && balance < 10000000000000000n && !fundingGas && (
        <div className="fixed top-16 left-4 right-4 z-50 bg-[#131313] border border-[#ff7166]/20 p-3 rounded-xl flex items-center justify-between">
          <span className="text-xs text-[#adaaaa]">⛽ Low gas balance</span>
          <button onClick={claimGas} className="text-xs font-bold text-[#8eff71] bg-[#262626] px-3 py-1 rounded-lg">Get Gas</button>
        </div>
      )}

      <div className="relative w-full max-w-md mx-auto h-[520px]">
        {/* Next card peek */}
        {cards[index + 1] && (
          <div className="absolute inset-0 scale-95 opacity-50">
            <TokenCard card={cards[index + 1]} onApe={() => {}} onFade={() => {}} />
          </div>
        )}
        {/* Current card with drag */}
        <div
          className={`absolute inset-0 transition-transform ${exiting ? 'duration-300' : dragging ? 'duration-0' : 'duration-200'}`}
          style={{
            transform: exiting === 'right' ? 'translateX(120%) rotate(15deg)'
              : exiting === 'left' ? 'translateX(-120%) rotate(-15deg)'
              : `translateX(${dragX}px) rotate(${dragX * 0.05}deg)`,
            opacity: exiting ? 0 : 1,
          }}
          onMouseDown={(e) => onDragStart(e.clientX)}
          onMouseMove={(e) => onDragMove(e.clientX)}
          onMouseUp={onDragEnd}
          onMouseLeave={() => { if (dragging) onDragEnd(); }}
          onTouchStart={(e) => onDragStart(e.touches[0].clientX)}
          onTouchMove={(e) => onDragMove(e.touches[0].clientX)}
          onTouchEnd={onDragEnd}
        >
          {/* Drag overlay indicators */}
          {dragX > 50 && <div className="absolute inset-0 rounded-xl border-4 border-[#8eff71] bg-[#8eff71]/10 z-10 flex items-center justify-center"><span className="text-[#8eff71] font-headline text-4xl font-black">APE 🦍</span></div>}
          {dragX < -50 && <div className="absolute inset-0 rounded-xl border-4 border-[#ff7166] bg-[#ff7166]/10 z-10 flex items-center justify-center"><span className="text-[#ff7166] font-headline text-4xl font-black">FADE 💨</span></div>}
          {/* Swipe feedback animation */}
          {swipeFeedback && <SwipeFeedback type={swipeFeedback} />}
          <TokenCard card={current} onApe={handleApe} onFade={handleFade} />
        </div>
      </div>
    </div>
  );
}
