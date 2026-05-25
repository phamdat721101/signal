import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { config, isXLayer, isCardTradeable } from '../config';
import { useCloseTransaction } from '../hooks/useCloseTransaction';

/**
 * CardHand — user's played cards (APE'd positions).
 *
 * Fetches from backend API (not on-chain enumeration) so it works
 * regardless of which chain the wallet is currently on.
 * Shows "Banish" button for LP-eligible played cards.
 */

const RARITY_NAME = ['Common', 'Rare', 'Epic', 'Legendary', 'Mythic'];
const RARITY_COLOR = ['#adaaaa', '#bf81ff', '#ff7b3a', '#ffd700', '#ff0080'];

interface PlayedCard {
  id: number;
  token_symbol: string;
  price: number;
  card_type: string;
  rarity: string;
  risk_score: number;
  swiped_at: string;
}

interface Props {
  address: string;
  chainId: number;
}

export default function CardHand({ address, chainId }: Props) {
  const [selected, setSelected] = useState<PlayedCard | null>(null);
  const { close, isLoading: isClosing, error: closeError } = useCloseTransaction();

  const { data } = useQuery({
    queryKey: ['played-cards', address],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/cards/played/${address}`);
      if (!resp.ok) return { cards: [] };
      return resp.json() as Promise<{ cards: PlayedCard[] }>;
    },
    enabled: !!address,
    staleTime: 30_000,
  });

  const cards = (data?.cards || []).filter(c => isCardTradeable(c));

  if (cards.length === 0) return null;

  return (
    <>
      <div>
        <div className="flex justify-between items-center mb-2">
          <h2 className="font-headline font-bold text-sm text-white">🃏 My Played Cards</h2>
          <span className="text-[9px] font-label text-[#494847]">{cards.length} positions</span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {cards.slice(0, 9).map(card => {
            const rarityIdx = ['common','rare','epic','legendary','mythic'].indexOf(card.rarity || 'common');
            const color = RARITY_COLOR[Math.max(0, rarityIdx)];
            return (
              <button
                key={card.id}
                onClick={() => setSelected(card)}
                className="bg-[#131313] rounded-xl p-2 border text-left active:scale-95 transition-transform"
                style={{ borderColor: `${color}33` }}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-headline font-bold text-xs text-white">${card.token_symbol}</span>
                </div>
                <div className="text-[9px] uppercase tracking-widest" style={{ color }}>
                  {RARITY_NAME[Math.max(0, rarityIdx)]}
                </div>
                <div className="text-[10px] text-[#adaaaa] mt-1">🔮 Summoned</div>
              </button>
            );
          })}
        </div>
      </div>

      {selected && (
        <div className="fixed inset-0 z-[60] bg-black/80 flex items-center justify-center p-6" onClick={() => setSelected(null)}>
          <div className="bg-[#131313] rounded-2xl max-w-sm w-full p-6 space-y-3" onClick={e => e.stopPropagation()}>
            <h3 className="font-headline font-bold text-lg text-white">
              ${selected.token_symbol} · #{selected.id}
            </h3>
            <div className="text-sm text-[#adaaaa] space-y-1">
              <div>Risk: <span className="text-white">{selected.risk_score}/100</span></div>
              <div>Played: <span className="text-white">{new Date(selected.swiped_at).toLocaleDateString()}</span></div>
            </div>
            {isXLayer(chainId) ? (
              <button
                onClick={async () => {
                  const tx = await close(selected.id, chainId);
                  if (tx) setSelected(null);
                }}
                disabled={isClosing}
                className="w-full bg-[#ff7166]/20 text-[#ff7166] font-headline font-bold py-2 rounded-lg disabled:opacity-50"
              >
                {isClosing ? 'Closing...' : '🔥 Banish (Remove LP)'}
              </button>
            ) : (
              <p className="text-xs text-[#494847] text-center">Switch to X Layer to remove LP</p>
            )}
            {closeError && <p className="text-xs text-[#ff7166] text-center">{closeError}</p>}
            <button onClick={() => setSelected(null)}
              className="w-full bg-[#262626] text-[#adaaaa] font-headline font-bold py-2 rounded-lg">
              Close
            </button>
          </div>
        </div>
      )}
    </>
  );
}
