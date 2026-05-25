import { useState } from 'react';
import { useReadContract, useReadContracts } from 'wagmi';
import { config, isXLayer, explorerTxUrl } from '../config';
import { useCloseTransaction } from '../hooks/useCloseTransaction';

/**
 * CardHand — user's unplayed SignalCardNFT collection on X Layer.
 *
 * SOLID single responsibility: render the hand + a tiny manage modal.
 * The modal is inlined (no separate file) because it has no other consumer.
 *
 * Renders nothing on chains other than X Layer — Initia's mint flow is
 * different (cards are off-chain rows, not NFTs) and that surface lives
 * elsewhere.
 */

const CARD_NFT_ABI = [
  { name: 'balanceOf', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'owner', type: 'address' }],
    outputs: [{ name: '', type: 'uint256' }] },
  { name: 'tokenOfOwnerByIndex', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'owner', type: 'address' }, { name: 'index', type: 'uint256' }],
    outputs: [{ name: '', type: 'uint256' }] },
  { name: 'cardData', type: 'function', stateMutability: 'view',
    inputs: [{ name: 'cardId', type: 'uint256' }],
    outputs: [{ name: '', type: 'tuple', components: [
      { name: 'tokenSymbol',    type: 'string' },
      { name: 'stopTickHint',   type: 'int24' },
      { name: 'targetTickHint', type: 'int24' },
      { name: 'riskScore',      type: 'uint16' },
      { name: 'rarity',         type: 'uint8' },
      { name: 'isBull',         type: 'bool' },
      { name: 'expiresAt',      type: 'uint64' },
      { name: 'played',         type: 'bool' },
    ] }] },
] as const;

const RARITY_NAME = ['Common', 'Rare', 'Epic', 'Legendary', 'Mythic'];
const RARITY_COLOR = ['#adaaaa', '#bf81ff', '#ff7b3a', '#ffd700', '#ff0080'];
const RARITY_EMOJI = ['🥉', '✨', '⚔️', '👑', '🐉'];

interface CardData {
  tokenId: bigint;
  tokenSymbol: string;
  riskScore: number;
  rarity: number;
  isBull: boolean;
  expiresAt: bigint;
  played: boolean;
}

interface Props {
  address: string;
  chainId: number;
}

export default function CardHand({ address, chainId }: Props) {
  const [selected, setSelected] = useState<CardData | null>(null);
  const { close, isLoading: isClosing, error: closeError } = useCloseTransaction();

  // Render nothing if the user is not on X Layer (cards live there only for v1).
  if (!isXLayer(chainId) || !address || config.xlayer.cardNftAddress === '0x0000000000000000000000000000000000000000') {
    return null;
  }

  const { data: balance } = useReadContract({
    address: config.xlayer.cardNftAddress,
    abi: CARD_NFT_ABI,
    functionName: 'balanceOf',
    args: [address as `0x${string}`],
    chainId,
  });

  const count = Number(balance ?? 0n);

  const { data: tokenIds } = useReadContracts({
    contracts: Array.from({ length: count }, (_, i) => ({
      address: config.xlayer.cardNftAddress,
      abi: CARD_NFT_ABI,
      functionName: 'tokenOfOwnerByIndex' as const,
      args: [address as `0x${string}`, BigInt(i)] as const,
      chainId,
    })),
    query: { enabled: count > 0 },
  });

  const ids = (tokenIds || [])
    .map(r => (r.status === 'success' ? (r.result as bigint) : null))
    .filter((x): x is bigint => x !== null);

  const { data: cards } = useReadContracts({
    contracts: ids.map(id => ({
      address: config.xlayer.cardNftAddress,
      abi: CARD_NFT_ABI,
      functionName: 'cardData' as const,
      args: [id] as const,
      chainId,
    })),
    query: { enabled: ids.length > 0 },
  });

  const hand: CardData[] = (cards || [])
    .map((r, i) => {
      if (r.status !== 'success' || !r.result) return null;
      const c = r.result as any;
      return {
        tokenId: ids[i],
        tokenSymbol: c.tokenSymbol,
        riskScore: Number(c.riskScore),
        rarity: Number(c.rarity),
        isBull: Boolean(c.isBull),
        expiresAt: BigInt(c.expiresAt),
        played: Boolean(c.played),
      };
    })
    .filter((x): x is CardData => x !== null);

  const unplayed = hand.filter(c => !c.played);
  const played = hand.filter(c => c.played);

  if (hand.length === 0) {
    return (
      <div className="bg-[#131313] rounded-xl p-4 border border-[#494847]/20">
        <h2 className="font-headline font-bold text-sm text-white mb-2">🃏 My Card Hand</h2>
        <p className="text-[10px] text-[#494847]">
          Your hand is empty. Swipe APE to summon your first card on X Layer.
        </p>
      </div>
    );
  }

  return (
    <>
      <div>
        <div className="flex justify-between items-center mb-2">
          <h2 className="font-headline font-bold text-sm text-white">🃏 My Card Hand</h2>
          <span className="text-[9px] font-label text-[#494847]">{unplayed.length} active · {played.length} played</span>
        </div>
        <div className="grid grid-cols-3 gap-2">
          {[...unplayed, ...played].map(card => {
            const color = RARITY_COLOR[card.rarity] || '#adaaaa';
            const emoji = RARITY_EMOJI[card.rarity] || '🥉';
            const expiresIn = Math.max(0, Number(card.expiresAt) - Math.floor(Date.now() / 1000));
            const hours = Math.floor(expiresIn / 3600);
            return (
              <button
                key={card.tokenId.toString()}
                onClick={() => setSelected(card)}
                className="bg-[#131313] rounded-xl p-2 border text-left active:scale-95 transition-transform"
                style={{ borderColor: `${color}33` }}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-headline font-bold text-xs text-white">${card.tokenSymbol}</span>
                  <span className="text-xs">{emoji}</span>
                </div>
                <div className="text-[9px] uppercase tracking-widest" style={{ color }}>
                  {RARITY_NAME[card.rarity]}
                </div>
                <div className="text-[10px] text-[#adaaaa] mt-1">
                  {card.isBull ? '📈 APE' : '📉 FADE'}
                </div>
                <div className="text-[9px] text-[#494847] mt-1">
                  {card.played ? '✅ Played' : `${hours}h left`}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {selected && (
        <div
          className="fixed inset-0 z-[60] bg-black/80 flex items-center justify-center p-6"
          onClick={() => setSelected(null)}
        >
          <div className="bg-[#131313] rounded-2xl max-w-sm w-full p-6 space-y-3" onClick={e => e.stopPropagation()}>
            <h3 className="font-headline font-bold text-lg text-white">
              ${selected.tokenSymbol} · {RARITY_NAME[selected.rarity]}
            </h3>
            <div className="text-sm text-[#adaaaa] space-y-1">
              <div>Token ID: <span className="text-white">#{selected.tokenId.toString()}</span></div>
              <div>Risk score: <span className="text-white">{selected.riskScore}/100</span></div>
              <div>Direction: <span className="text-white">{selected.isBull ? 'APE (long)' : 'FADE (short)'}</span></div>
              <div>Expires: <span className="text-white">
                {new Date(Number(selected.expiresAt) * 1000).toLocaleString()}
              </span></div>
            </div>
            <a
              href={explorerTxUrl(selected.tokenId.toString(16), chainId)}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-xs text-[#bf81ff] underline text-center"
            >
              View on OKLink
            </a>
            {selected.played && (
              <button
                onClick={async () => {
                  const tx = await close(Number(selected.tokenId), chainId);
                  if (tx) setSelected(null);
                }}
                disabled={isClosing}
                className="w-full bg-[#ff7166]/20 text-[#ff7166] font-headline font-bold py-2 rounded-lg disabled:opacity-50"
              >
                {isClosing ? 'Closing...' : '🔥 Banish (Remove LP)'}
              </button>
            )}
            {closeError && <p className="text-xs text-[#ff7166] text-center">{closeError}</p>}
            <button
              onClick={() => setSelected(null)}
              className="w-full bg-[#262626] text-[#adaaaa] font-headline font-bold py-2 rounded-lg"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </>
  );
}
