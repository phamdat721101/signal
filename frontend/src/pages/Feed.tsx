import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePrivy } from '@privy-io/react-auth';
import { useCards, useSwipe } from '../hooks/useCards';
import TokenCard from '../components/TokenCard';

export default function Feed() {
  const [index, setIndex] = useState(0);
  const { data, isLoading } = useCards(0, 50);
  const apeMutation = useSwipe('ape');
  const fadeMutation = useSwipe('fade');
  const { user } = usePrivy();
  const initiaAddress = user?.wallet?.address || "";
  const navigate = useNavigate();

  const cards = data?.cards ?? [];
  const current = cards[index];

  const handleApe = () => {
    if (!current) return;
    const address = initiaAddress || '';
    apeMutation.mutate({ cardId: current.id, address });
    navigate(`/trade-success/${current.id}`);
  };

  const handleFade = () => {
    if (!current) return;
    const address = initiaAddress || '';
    fadeMutation.mutate({ cardId: current.id, address });
    setIndex((i) => Math.min(i + 1, cards.length - 1));
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
        <span className="material-symbols-outlined text-6xl text-[#494847]">explore</span>
        <p className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">No cards yet</p>
        <p className="text-[#494847] text-xs">The AI content engine is generating new tokens. Check back soon.</p>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center h-full p-4">
      <TokenCard card={current} onApe={handleApe} onFade={handleFade} />
    </div>
  );
}
