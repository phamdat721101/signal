import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePrivy } from '@privy-io/react-auth';
import { useQuery } from '@tanstack/react-query';
import { createPublicClient, http } from 'viem';
import { useCards } from '../hooks/useCards';
import { config } from '../config';
import TokenCard from '../components/TokenCard';
import Onboarding from '../components/Onboarding';
import BridgePrompt from '../components/BridgePrompt';
import Paywall from '../components/Paywall';
import { useApeTransaction } from '../hooks/useApeTransaction';

const publicClient = createPublicClient({ chain: config.chain, transport: http() });

export default function Feed() {
  const [showOnboarding, setShowOnboarding] = useState(!localStorage.getItem('kinetic_onboarded'));
  const [index, setIndex] = useState(0);
  const [dragX, setDragX] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [exiting, setExiting] = useState<'left' | 'right' | null>(null);
  const startX = useRef(0);
  const [showPaywall, setShowPaywall] = useState(false);
  const { data, isLoading } = useCards(0, 50);
  const { user, login } = usePrivy();
  const initiaAddress = user?.wallet?.address || "";
  const navigate = useNavigate();
  const { apeOnChain } = useApeTransaction();

  const { data: balance } = useQuery({
    queryKey: ['balance', initiaAddress],
    queryFn: () => publicClient.getBalance({ address: initiaAddress as `0x${string}` }),
    enabled: !!initiaAddress,
  });

  const [notification, setNotification] = useState<string | null>(null);
  const { data: resolvedData } = useQuery({
    queryKey: ['resolved', initiaAddress],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/trades/${initiaAddress}/resolved-recent`);
      return resp.ok ? resp.json() : { trades: [] };
    },
    enabled: !!initiaAddress,
    staleTime: 300_000,
  });
  useEffect(() => {
    const trades = resolvedData?.trades || [];
    if (trades.length > 0) {
      const t = trades[0];
      const won = (t.pnl_usd || 0) > 0;
      setNotification(won
        ? `\u2705 Your $${t.token_symbol} prediction was RIGHT! +${(t.pnl_pct || 0).toFixed(1)}% \uD83E\uDDE0`
        : `\u274C Your $${t.token_symbol} prediction was wrong. ${(t.pnl_pct || 0).toFixed(1)}%. Keep learning!`);
      setTimeout(() => setNotification(null), 5000);
    }
  }, [resolvedData]);

  const cards = data?.cards ?? [];
  const current = cards[index];

  if (showOnboarding) {
    return <Onboarding onComplete={() => { localStorage.setItem('kinetic_onboarded', 'true'); setShowOnboarding(false); login(); }} />;
  }

  const handleApe = async () => {
    if (!current) return;
    const address = initiaAddress || '';
    let txHash: string | undefined;
    if (address) {
      try { txHash = (await apeOnChain(current)) || undefined; } catch (e) { console.warn('On-chain ape failed:', e); }
    }
    const resp = await fetch(`${config.backendUrl}/api/cards/${current.id}/ape`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address, tx_hash: txHash }),
    });
    if (resp.status === 402) { setShowPaywall(true); return; }
    const data = await resp.json();
    navigate(`/trade-success/${current.id}`, { state: { trade: data.trade } });
  };

  const handleFade = async () => {
    if (!current) return;
    const address = initiaAddress || '';
    const resp = await fetch(`${config.backendUrl}/api/cards/${current.id}/fade`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address }),
    });
    if (resp.status === 402) { setShowPaywall(true); return; }
    setIndex((i) => i + 1);
  };

  const onDragStart = (clientX: number) => { startX.current = clientX; setDragging(true); };
  const onDragMove = (clientX: number) => { if (dragging) setDragX(clientX - startX.current); };
  const onDragEnd = () => {
    setDragging(false);
    if (dragX > 100) { setExiting('right'); setTimeout(() => { handleApe(); setExiting(null); setDragX(0); }, 300); }
    else if (dragX < -100) { setExiting('left'); setTimeout(() => { handleFade(); setExiting(null); setDragX(0); }, 300); }
    else setDragX(0);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">Loading feed...</div>
      </div>
    );
  }

  if (initiaAddress && balance === 0n) {
    return <BridgePrompt address={initiaAddress} />;
  }

  if (!current) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6 text-center">
        <span className="material-symbols-outlined text-6xl text-[#494847]">explore</span>
        <p className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">No more cards</p>
        <p className="text-[#494847] text-xs">Check back soon for fresh tokens</p>
        <button onClick={() => setIndex(0)} className="mt-2 bg-[#262626] px-6 py-2 rounded-lg text-[#adaaaa] font-label text-sm">
          Refresh Feed
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center h-full p-4">
      {showPaywall && <Paywall onDismiss={() => setShowPaywall(false)} />}
      {notification && (
        <div className="fixed top-16 left-4 right-4 z-50 bg-[#131313] border border-[#494847]/20 p-3 rounded-xl text-center animate-pulse">
          <div className="text-sm text-white">{notification}</div>
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
          {/* Swipe overlay indicators */}
          {dragX > 50 && <div className="absolute inset-0 rounded-xl border-4 border-[#8eff71] bg-[#8eff71]/10 z-10 flex items-center justify-center"><span className="text-[#8eff71] font-headline text-4xl font-black">APE</span></div>}
          {dragX < -50 && <div className="absolute inset-0 rounded-xl border-4 border-[#ff7166] bg-[#ff7166]/10 z-10 flex items-center justify-center"><span className="text-[#ff7166] font-headline text-4xl font-black">FADE</span></div>}
          <TokenCard card={current} onApe={handleApe} onFade={handleFade} />
        </div>
      </div>
    </div>
  );
}
