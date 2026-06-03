import { useState, useRef, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
// import { usePrivy } from '@privy-io/react-auth';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { createPublicClient, http } from 'viem';
import { useCards } from '../hooks/useCards';
import { useFeaturedGem } from '../hooks/useFeaturedGem';
import { useFeedMode } from '../hooks/useFeedMode';
import { config, shareToX, normalizeAddress, isCardTradeable } from '../config';
import TokenCard, { TokenCardDetail, hasTokenCardDetail } from '../components/TokenCard';
import { MacroDeskCard, WhaleAlertCard } from '../components/TokenCard';
import { InsightCard } from '../components/InsightCard';
import LpBattleCard from '../components/LpBattleCard';
import TradingSignalCard from '../components/TradingSignalCard';
import { useExecuteSignal } from '../hooks/useExecuteSignal';
import LpConfigurator from '../components/LpConfigurator';
import Onboarding from '../components/Onboarding';
import Paywall from '../components/Paywall';
import { useApeTransaction } from '../hooks/useApeTransaction';
import { useWallet } from '../hooks/useWallet';
import SummonRitual from '../components/SummonRitual';

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

/** Map a structured execute error code to a user-facing line.
 *  Pure, no React, easy to unit-test. New codes only need one row. */
function humanizeExecError(code: string, raw?: string): string {
  switch (code) {
    case 'trading_disabled':         return 'Trading temporarily paused — try again later.';
    case 'symbol_not_listed_on_sodex': return 'This asset is not yet listed on SoDex testnet.';
    case 'symbol_not_supported':     return 'Asset not supported by Kinetic.';
    case 'already_executed':         return 'You already executed this card. Open positions in Portfolio.';
    case 'daily_cap_reached':        return 'Daily execution cap reached (5/day).';
    case 'qty_below_step':           return 'Order size too small for this asset — bump notional.';
    case 'notional_below_min':       return 'Notional below SoDex $10 minimum.';
    case 'sodex_rejected':           return raw ? `SoDex rejected: ${raw}` : 'SoDex rejected the order.';
    case 'missing_mark_price':       return 'No live price — try again in a moment.';
    case 'sodex_disabled':           return 'SoDex execution is disabled in this environment.';
    default:                         return raw || `Failed (${code}).`;
  }
}

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
            {typeof window !== 'undefined' && (window as any).__xlayer ? '🔮 SUMMON LP' : '🔥 COMMIT ON-CHAIN'}
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

/* ── Rare Card Reveal Effect ── */
const RARE_CAT: Record<string, { emoji: string; text: string; color: string }> = {
  rare: { emoji: '🐱', text: 'RARE FIND!', color: '#8eff71' },
  epic: { emoji: '😺', text: 'EPIC DROP!', color: '#bf81ff' },
  legendary: { emoji: '🙀', text: 'LEGENDARY!', color: '#fbbf24' },
};

function RareCardReveal({ rarity, onDone }: { rarity: string; onDone: () => void }) {
  const cfg = RARE_CAT[rarity];
  if (!cfg) return null;
  useEffect(() => { const t = setTimeout(onDone, 1800); return () => clearTimeout(t); }, [onDone]);
  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center pointer-events-none">
      <div className="absolute inset-0 bg-black/60 animate-[fadeIn_0.2s_ease-out]" />
      <div className="relative animate-[scaleIn_0.4s_ease-out] text-center">
        <div className="absolute inset-0 -m-8 rounded-full blur-3xl animate-pulse" style={{ background: `${cfg.color}20` }} />
        <div className="text-7xl animate-bounce">{cfg.emoji}</div>
        <div className="font-headline text-2xl font-black mt-2 tracking-wider" style={{ color: cfg.color }}>
          {cfg.text}
        </div>
        <div className="flex justify-center gap-1 mt-2">
          {['✨','⭐','✨','⭐','✨'].map((s, i) => (
            <span key={i} className="text-lg animate-ping" style={{ animationDelay: `${i * 0.15}s`, animationDuration: '1s' }}>{s}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ── Main Feed ── */
export default function Feed() {
  const [showOnboarding, setShowOnboarding] = useState(!localStorage.getItem('kinetic_onboarded'));
  const [showQuickOnboarding, setShowQuickOnboarding] = useState(() => !localStorage.getItem('onboarded'));
  // Active mode (URL ?mode=) + per-mode swipe index (localStorage). Single source of truth.
  const { activeMode, currentIndex: index, setCurrentIndex: setIndex } = useFeedMode();
  const [dragX, setDragX] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [exiting, setExiting] = useState<'left' | 'right' | null>(null);
  const startX = useRef(0);
  const startY = useRef(0);
  const axisLock = useRef<'x' | 'y' | null>(null);
  const wasDragged = useRef(false);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [showPaywall, setShowPaywall] = useState(false);
  const [swipeFeedback, setSwipeFeedback] = useState<'ape' | 'fade' | null>(null);
  const [resolvedTrade, setResolvedTrade] = useState<any>(null);
  const [generating, setGenerating] = useState(false);
  const [showConviction, setShowConviction] = useState(false);
  const [summonCard, setSummonCard] = useState<any>(null);
  const [pendingCard, setPendingCard] = useState<any>(null);
  const [showRareReveal, setShowRareReveal] = useState<string | null>(null);
  const [lpConfigCard, setLpConfigCard] = useState<any>(null);

  // Execute toast state — minimal, single source. Auto-dismisses (see effect below).
  const [execToast, setExecToast] = useState<{
    kind: 'success' | 'error';
    title: string;
    message: string;
    orderId?: string;
  } | null>(null);
  useEffect(() => {
    if (!execToast) return;
    const t = setTimeout(() => setExecToast(null), 6000);
    return () => clearTimeout(t);
  }, [execToast]);

  const { data, isLoading } = useCards(0, 50, activeMode.cardTypes as string[]);
  const { data: featuredGem } = useFeaturedGem();
  const { address: initiaAddress, login, isCorrectChain } = useWallet();
  const navigate = useNavigate();
  const { apeOnChain } = useApeTransaction();
  const executeSignal = useExecuteSignal();

  const evmAddress = normalizeAddress(initiaAddress);

  const queryClient = useQueryClient();
  const [localEnergy, setLocalEnergy] = useState<number>(() => {
    const stored = localStorage.getItem('kinetic_energy');
    const storedDate = localStorage.getItem('kinetic_energy_date');
    const today = new Date().toISOString().slice(0, 10);
    if (storedDate !== today) { localStorage.setItem('kinetic_energy_date', today); localStorage.setItem('kinetic_energy', '5'); return 5; }
    return stored ? parseInt(stored) : 5;
  });

  const { data: balance } = useQuery({
    queryKey: ['balance', evmAddress],
    queryFn: () => publicClient.getBalance({ address: evmAddress as `0x${string}` }),
    enabled: !!evmAddress,
  });

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

  const cards = useMemo(() => {
    const base = data?.cards ?? [];
    // Pin the freshest gem only inside the Tokens mode (News mode shouldn't
    // surface trade-able gem cards). Skip if no gem, or if already at the top.
    if (activeMode.id !== 'tokens') return base;
    if (!featuredGem || base[0]?.id === featuredGem.id) return base;
    return [featuredGem, ...base.filter(c => c.id !== featuredGem.id)];
  }, [data, featuredGem, activeMode.id]);
  const current = cards[index];

  // Reset detail expansion + scroll position whenever the visible card advances.
  useEffect(() => {
    setExpanded(false);
    scrollContainerRef.current?.scrollTo({ top: 0, behavior: 'auto' });
  }, [index, activeMode.id]);

  // Tap-to-expand: tapping the card body toggles the inline analysis panel.
  // Skip taps that landed on an interactive child (FADE/APE/Share buttons)
  // and taps that follow a real drag gesture (horizontal or vertical move
  // beyond 8px — tracked by the wasDragged ref in onDragMove).
  const handleCardTap = (e: React.MouseEvent<HTMLDivElement>) => {
    if (wasDragged.current) return;
    if ((e.target as Element).closest?.('button, a, [role="button"]')) return;
    if (!hasTokenCardDetail(current)) return;
    setExpanded(prev => !prev);
  };

  // Rare card reveal trigger
  useEffect(() => {
    if (!current) return;
    const r = current.rarity;
    if (r === 'rare' || r === 'epic' || r === 'legendary') {
      setShowRareReveal(r);
    }
  }, [index, current?.id]);

  if (showOnboarding) {
    return <Onboarding onComplete={() => { localStorage.setItem('kinetic_onboarded', 'true'); setShowOnboarding(false); login(); }} />;
  }

  const [showApeChoice, setShowApeChoice] = useState(false);

  const handleApe = async () => {
    if (!current) return;
    // Tradeable cards: show choice (Predict vs Summon LP).
    // Non-tradeable cards: go straight to conviction (prediction only).
    if (isCardTradeable(current)) {
      setShowApeChoice(true);
    } else {
      setPendingCard(current);
      setShowConviction(true);
    }
  };

  const handleChoosePredict = () => {
    setShowApeChoice(false);
    setPendingCard(current);
    setShowConviction(true);
  };

  const handleChooseSummon = () => {
    setShowApeChoice(false);
    setSummonCard(current);
  };

  const confirmConviction = async () => {
    const card = pendingCard;
    if (!card) return;
    setShowConviction(false);
    setPendingCard(null);
    setSwipeFeedback('ape');
    // Energy gating disabled — see backend Settings.energy_gating_enabled.
    // Local-state decrement kept for visual feedback only, never blocks swipes.
    if (!evmAddress) {
      const newE = Math.max(0, localEnergy - 1);
      setLocalEnergy(newE);
      localStorage.setItem('kinetic_energy', String(newE));
      // if (newE <= 0) { setShowPaywall(true); return; }  // disabled: unlimited swipes
    }
    // Advance immediately for snappy UX
    setTimeout(() => { setSwipeFeedback(null); setIndex(i => i + 1); }, 400);
    // Network in background
    const address = evmAddress || '';
    let txHash: string | undefined;
    if (address) {
      try { txHash = (await apeOnChain(card)) || undefined; } catch (e) { console.warn('On-chain ape failed:', e); }
    }
    const resp = await fetch(`${config.backendUrl}/api/cards/${card.id}/ape`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Wallet-Address': address },
      body: JSON.stringify({ address, tx_hash: txHash }),
    });
    // 402 no_energy can no longer fire (backend gate is off); kept tolerant.
    if (resp.status === 402) { /* setShowPaywall(true); */ return; }
    queryClient.invalidateQueries({ queryKey: ['energy'] });
    const data = await resp.json();
    if (data.trade) navigate(`/trade-success/${card.id}`, { state: { trade: data.trade, conviction: data.conviction } });
  };

  const handleExecute = async () => {
    if (!current || !evmAddress) {
      if (!evmAddress) login();
      return;
    }
    try {
      const r = await executeSignal.mutateAsync({ cardId: current.id, address: evmAddress });
      console.info('SoDex order placed:', r.order_id, r.symbol, r.side);
      // Refresh every surface that should reflect the new position so
      // the user sees their trade on Portfolio / Profile / History
      // without a manual reload.
      queryClient.invalidateQueries({ queryKey: ['trades', evmAddress] });
      queryClient.invalidateQueries({ queryKey: ['sodex-positions', evmAddress] });
      queryClient.invalidateQueries({ queryKey: ['sodex-pool'] });
      queryClient.invalidateQueries({ queryKey: ['history', evmAddress] });
      setExecToast({
        kind: 'success',
        title: '🎯 Order Filled',
        message: `${r.side.toUpperCase()} ${r.qty} ${r.symbol} @ $${r.avg_price}`,
        orderId: r.order_id,
      });
    } catch (e: unknown) {
      const err = e as { body?: { detail?: { code?: string; raw?: { error?: string } } | string }; message?: string };
      const detail = err.body?.detail;
      const code = (typeof detail === 'object' && detail?.code) || err.message || 'execute_failed';
      const raw = (typeof detail === 'object' && detail?.raw?.error) || '';
      console.warn('Execute failed:', code, raw);
      setExecToast({
        kind: 'error',
        title: '❌ Order Rejected',
        message: humanizeExecError(code, raw),
      });
    }
  };

  const handleFade = async () => {
    if (!current) return;
    setSwipeFeedback('fade');
    // Energy gating disabled — visual decrement only.
    if (!evmAddress) {
      const newE = Math.max(0, localEnergy - 1);
      setLocalEnergy(newE);
      localStorage.setItem('kinetic_energy', String(newE));
      // if (newE <= 0) { setShowPaywall(true); return; }  // disabled: unlimited swipes
    }
    // Advance immediately
    setTimeout(() => { setSwipeFeedback(null); setIndex(i => i + 1); }, 300);
    // Backend in background
    const address = evmAddress || '';
    fetch(`${config.backendUrl}/api/cards/${current.id}/fade`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Wallet-Address': address },
      body: JSON.stringify({ address }),
    }).then(_r => { /* 402 cannot fire while gating disabled */ });
    queryClient.invalidateQueries({ queryKey: ['energy'] });
  };

  const onDragStart = (clientX: number, clientY: number) => {
    startX.current = clientX;
    startY.current = clientY;
    axisLock.current = null;
    wasDragged.current = false;
    setDragging(true);
  };
  const onDragMove = (clientX: number, clientY: number) => {
    if (!dragging) return;
    const dx = clientX - startX.current;
    const dy = clientY - startY.current;
    // Decide axis on first meaningful move; once locked to vertical, let the
    // browser scroll. Once locked to horizontal, engage the swipe. Either
    // way, mark the gesture as a drag so the click that follows is ignored
    // by handleCardTap.
    if (axisLock.current === null && Math.abs(dx) + Math.abs(dy) > 8) {
      axisLock.current = Math.abs(dy) > Math.abs(dx) ? 'y' : 'x';
      wasDragged.current = true;
    }
    if (axisLock.current === 'x') setDragX(dx);
  };
  const onDragEnd = () => {
    setDragging(false);
    const lockedX = axisLock.current === 'x';
    axisLock.current = null;
    if (!lockedX) { setDragX(0); return; }
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

  // ─── Unified single-root layout (eliminates CLS across card types) ───

  return (
    <div className="flex flex-col h-full p-4 max-w-md mx-auto">
      {/* Modals/overlays (fixed, no CLS) */}
      {showQuickOnboarding && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-6" onClick={() => { localStorage.setItem('onboarded', 'true'); setShowQuickOnboarding(false); }}>
          <div className="bg-[#131313] border border-[#bf81ff]/30 rounded-2xl p-6 max-w-sm text-center space-y-3" onClick={e => e.stopPropagation()}>
            <div className="text-4xl">🦍</div>
            <h2 className="text-xl font-bold text-white">Ape or Fade?</h2>
            <p className="text-sm text-[#adaaaa]"><span className="text-[#8eff71] font-bold">APE</span> = Going up. Swipe right.<br/><span className="text-[#ff7166] font-bold">FADE</span> = Going down. Swipe left.</p>
            <p className="text-xs text-[#494847]">Every prediction is tracked on-chain.</p>
            <button onClick={() => { localStorage.setItem('onboarded', 'true'); setShowQuickOnboarding(false); }} className="mt-2 ape-gradient px-6 py-2 rounded-lg text-[#0b5800] font-bold text-sm">Let's Go 🚀</button>
          </div>
        </div>
      )}
      {showConviction && pendingCard && (
        <ConvictionOverlay card={pendingCard} onConfirm={confirmConviction} onCancel={() => { setShowConviction(false); setPendingCard(null); }} />
      )}
      <SummonRitual
        card={summonCard}
        open={!!summonCard}
        onClose={() => setSummonCard(null)}
        onSuccess={async (txHash, txChainId) => {
          setSummonCard(null);
          setIndex(i => i + 1);
          // Record LP tx for portfolio — awaited with one retry on transient
          // failure. Backend is idempotent on tx_hash UNIQUE (db.py:285), so
          // a retry can never double-insert. Worst case both fail: explorer
          // link still opens; user can re-summon to backfill.
          if (evmAddress && current) {
            const post = () => fetch(`${config.backendUrl}/api/lp/record`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ address: evmAddress, card_id: current.id, tx_hash: txHash, action: 'summon', chain_id: txChainId }),
            });
            try {
              const r = await post();
              if (!r.ok) throw new Error(`record failed: ${r.status}`);
            } catch (e) {
              console.warn('[summon] /api/lp/record retry:', e);
              try { await post(); } catch { /* swallow — backend reconciles on next user action */ }
            }
          }
          // Open explorer
          const url = txChainId === 1952
            ? `https://www.oklink.com/xlayer-test/tx/${txHash}`
            : `https://www.oklink.com/xlayer/tx/${txHash}`;
          window.open(url, '_blank');
          queryClient.invalidateQueries({ queryKey: ['cards'] });
          queryClient.invalidateQueries({ queryKey: ['played-cards'] });
          queryClient.invalidateQueries({ queryKey: ['lp-history'] });
        }}
      />
      {/* APE Choice: Predict vs Summon LP */}
      {showApeChoice && current && (
        <div className="fixed inset-0 z-[70] bg-black/85 flex items-center justify-center p-6" onClick={() => setShowApeChoice(false)}>
          <div className="bg-[#131313] rounded-2xl max-w-sm w-full overflow-hidden border border-[#494847]/20" onClick={e => e.stopPropagation()}>
            <div className="h-1.5 bg-gradient-to-r from-[#8eff71] to-[#bf81ff]" />
            <div className="p-6 flex flex-col gap-3">
              <h2 className="font-headline text-xl font-black text-white text-center">APE ${current.token_symbol}</h2>
              <p className="text-xs text-[#adaaaa] text-center">Choose how to play this card</p>
              <button onClick={handleChoosePredict}
                className="w-full bg-[#262626] border border-[#8eff71]/20 rounded-xl p-4 text-left active:scale-95 transition-transform">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">🔥</span>
                  <div>
                    <div className="font-headline font-bold text-white text-sm">Predict</div>
                    <div className="text-[10px] text-[#adaaaa]">Free · Build reputation · Resolves in 24h</div>
                  </div>
                </div>
              </button>
              <button onClick={handleChooseSummon}
                className="w-full bg-[#262626] border border-[#bf81ff]/20 rounded-xl p-4 text-left active:scale-95 transition-transform">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">🔮</span>
                  <div>
                    <div className="font-headline font-bold text-white text-sm">Summon LP</div>
                    <div className="text-[10px] text-[#adaaaa]">Earn swap fees · Requires OKB + USDC · X Layer</div>
                  </div>
                </div>
              </button>
              <button onClick={() => setShowApeChoice(false)}
                className="w-full text-[#494847] text-xs font-label py-2">Cancel</button>
            </div>
          </div>
        </div>
      )}
      {showPaywall && <Paywall onDismiss={() => setShowPaywall(false)} isConnected={!!evmAddress} onConnect={login} />}
      {resolvedTrade && <ResolutionModal trade={resolvedTrade} onDismiss={() => setResolvedTrade(null)} />}
      {lpConfigCard && <LpConfigurator card={lpConfigCard} onClose={() => setLpConfigCard(null)} />}

      {/* Execute toast — fixed bottom; success or error. SOLID: a single
          state drives one rendering surface; click to dismiss; auto-clear
          via the useEffect above. */}
      {execToast && (
        <div
          onClick={() => setExecToast(null)}
          className={`fixed bottom-24 left-4 right-4 z-50 max-w-md mx-auto rounded-xl p-4 cursor-pointer animate-[fadeIn_0.2s_ease-out] ${
            execToast.kind === 'success'
              ? 'bg-[#0e1a0e] border-2 border-[#8eff71] shadow-[0_0_24px_-6px_rgba(142,255,113,0.5)]'
              : 'bg-[#1a0e0e] border-2 border-[#ff7166] shadow-[0_0_24px_-6px_rgba(255,113,102,0.5)]'
          }`}
          role="status"
          aria-live="polite"
        >
          <div className={`font-headline font-bold text-sm ${execToast.kind === 'success' ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>
            {execToast.title}
          </div>
          <div className="text-white text-sm mt-1">{execToast.message}</div>
          {execToast.kind === 'success' && (
            <div className="flex items-center justify-between mt-2">
              {execToast.orderId && (
                <span className="text-[10px] text-[#adaaaa] font-mono">#{execToast.orderId}</span>
              )}
              <button
                onClick={(e) => { e.stopPropagation(); navigate('/portfolio'); }}
                className="text-[11px] font-headline font-bold text-[#bf81ff] uppercase tracking-widest hover:underline"
              >
                View Positions →
              </button>
            </div>
          )}
        </div>
      )}
      {evmAddress && isCorrectChain && balance != null && balance < 10000000000000000n && (
        <div className="fixed top-16 left-4 right-4 z-40 bg-[#131313] border border-[#bf81ff]/30 p-3 rounded-xl flex items-center justify-between">
          <span className="text-xs text-[#adaaaa]">⛽ Low INIT — bridge from L1 to trade</span>
          <a href={`https://bridge.initia.xyz/?to=initia-signal-1&address=${evmAddress}`}
             target="_blank" rel="noopener noreferrer"
             className="text-xs font-bold text-[#8eff71] bg-[#262626] px-3 py-1 rounded-lg">
            Bridge
          </a>
        </div>
      )}

      {/* Reserved header slot — fixed height prevents CLS */}

      {/* Tap-to-expand surface — single column. Tap the card body to toggle
          the analysis panel below; horizontal drag still drives APE/FADE.
          The previous 2-snap-point scroll layout was replaced because users
          could not discover the panel was below. */}
      <div
        ref={scrollContainerRef}
        className="relative w-full max-w-md mx-auto flex-1 overflow-y-auto no-scrollbar"
      >
        <div className="relative w-full pt-2">
          <div
            className={`relative w-full h-[520px] ${hasTokenCardDetail(current) ? 'cursor-pointer' : ''}`}
            onClick={handleCardTap}
          >
            {current.card_type === 'insight' ? (
              <InsightCard card={current as any} onApe={handleApe} onFade={handleFade} />
            ) : current.card_type === 'macro_desk' ? (
              <MacroDeskCard card={current} onApe={handleApe} onFade={handleFade} />
            ) : current.card_type === 'whale_alert' ? (
              <WhaleAlertCard card={current} onApe={handleApe} onFade={handleFade} />
            ) : current.card_type === 'pool' ? (
              <LpBattleCard
                card={current}
                onConfigure={() => setLpConfigCard(current)}
                onViewStrategy={() => setLpConfigCard(current)}
              />
            ) : current.card_type === 'trading_signal' ? (
              <TradingSignalCard
                card={current}
                onApe={handleApe}
                onFade={handleFade}
                onExecute={handleExecute}
                isExecuting={executeSignal.isPending}
              />
            ) : (
              <>
                {/* Next card peek */}
                {cards[index + 1] && (
                  <div className="absolute inset-0 scale-95 opacity-50 pointer-events-none">
                    <TokenCard card={cards[index + 1]} onApe={() => {}} onFade={() => {}} isTop={false} />
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
                  onMouseDown={(e) => onDragStart(e.clientX, e.clientY)}
                  onMouseMove={(e) => onDragMove(e.clientX, e.clientY)}
                  onMouseUp={onDragEnd}
                  onMouseLeave={() => { if (dragging) onDragEnd(); }}
                  onTouchStart={(e) => onDragStart(e.touches[0].clientX, e.touches[0].clientY)}
                  onTouchMove={(e) => onDragMove(e.touches[0].clientX, e.touches[0].clientY)}
                  onTouchEnd={onDragEnd}
                >
                  {dragX > 50 && <div className="absolute inset-0 rounded-xl border-4 border-[#8eff71] bg-[#8eff71]/10 z-10 flex items-center justify-center"><span className="text-[#8eff71] font-headline text-4xl font-black">APE 🦍</span></div>}
                  {dragX < -50 && <div className="absolute inset-0 rounded-xl border-4 border-[#ff7166] bg-[#ff7166]/10 z-10 flex items-center justify-center"><span className="text-[#ff7166] font-headline text-4xl font-black">FADE 💨</span></div>}
                  {swipeFeedback && <SwipeFeedback type={swipeFeedback} />}
                  {showRareReveal && <RareCardReveal rarity={showRareReveal} onDone={() => setShowRareReveal(null)} />}
                  <TokenCard card={current} onApe={handleApe} onFade={handleFade} isTop />
                </div>
              </>
            )}
          </div>

          {/* Tap-to-expand affordance — only when there is analysis to show. */}
          {hasTokenCardDetail(current) && !expanded && (
            <button
              onClick={() => setExpanded(true)}
              className="mt-3 w-full flex flex-col items-center py-2 active:text-[#8eff71] transition-colors"
              aria-controls="token-card-detail"
              aria-expanded={false}
            >
              <span className="text-[10px] text-[#adaaaa] font-label uppercase tracking-widest">tap card for analysis</span>
              <span className="text-2xl text-[#8eff71]" style={{ animation: 'chevronBounce 1.4s ease-in-out infinite' }}>↓</span>
            </button>
          )}

          {/* Expanded analysis — rendered inline; collapses on another tap on
              the card body or on this footer button. */}
          {hasTokenCardDetail(current) && expanded && (
            <div id="token-card-detail" className="w-full px-2 pb-6 pt-3 animate-[fadeIn_0.25s_ease-out]">
              <TokenCardDetail card={current} />
              <button
                onClick={() => setExpanded(false)}
                className="mt-4 w-full flex flex-col items-center py-3 text-[#adaaaa] hover:text-white active:text-[#8eff71] transition-colors"
                aria-controls="token-card-detail"
                aria-expanded={true}
              >
                <span className="text-2xl text-[#bf81ff]">↑</span>
                <span className="text-[10px] font-label uppercase tracking-widest">tap to collapse</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
