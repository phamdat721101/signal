/**
 * VaultConfigurator — full-screen sheet that captures the user's USD
 * intent for a SoDex vault deposit, then hands off to sodex.com.
 *
 * Single Responsibility: render the form + dispatch the allocation
 * mutation. The deposit itself happens on SoDex (wallet-signed) — this
 * sheet only records intent in `vault_allocations` and opens the deep
 * link in a new tab.
 */
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { Card } from '../hooks/useCards';
import { useWallet } from '../hooks/useWallet';
import { useAllocateVault } from '../hooks/useAllocateVault';

interface Props {
  card: Card;
  onClose: () => void;
}

interface VaultMeta {
  vault_kind?: string;
  accepted_assets?: string[];
  lockup_label?: string;
  yield_sources?: string[];
  min_deposit_usd?: number;
  short_name?: string;
}

export default function VaultConfigurator({ card, onClose }: Props) {
  const { address } = useWallet();
  const meta = ((card as unknown as { research_summary?: VaultMeta }).research_summary) || {};
  const minDep = meta.min_deposit_usd ?? 50;

  const [amount, setAmount] = useState<string>(String(minDep));
  const allocate = useAllocateVault();
  const qc = useQueryClient();

  const numeric = parseFloat(amount || '0');
  const tooLow = !numeric || numeric < minDep;

  const error = allocate.error
    ? (allocate.error.message || 'Allocation failed')
    : null;

  const submit = async () => {
    if (!address || tooLow) return;
    try {
      await allocate.mutateAsync({ cardId: card.id, address, intentAmountUsd: numeric });
      qc.invalidateQueries({ queryKey: ['history', address] });
      onClose();
    } catch {
      /* error surface handled below */
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-end sm:items-center justify-center p-3"
         onClick={onClose}>
      <div className="w-full max-w-sm rounded-2xl bg-[#0e0e0e] border border-[#262626] p-5 flex flex-col gap-4"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <div>
            <div className="font-headline font-bold text-white text-base">{card.token_name || card.token_symbol}</div>
            <div className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest">Allocate to Vault</div>
          </div>
          <button type="button" onClick={onClose}
                  className="text-[#adaaaa] hover:text-white">
            <span className="material-symbols-outlined text-xl">close</span>
          </button>
        </div>

        {/* Vault summary */}
        <div className="bg-[#131313] rounded-lg p-3 space-y-1.5">
          <div className="flex justify-between text-xs">
            <span className="text-[#adaaaa]">Accepted</span>
            <span className="text-white font-mono">{(meta.accepted_assets || []).join(' · ') || '—'}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-[#adaaaa]">Lockup</span>
            <span className="text-white text-right">{meta.lockup_label || 'Instant'}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-[#adaaaa]">Min Deposit</span>
            <span className="text-white">${minDep.toFixed(0)}</span>
          </div>
        </div>

        {/* Amount input */}
        <label className="flex flex-col gap-1.5">
          <span className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest">Amount (USD)</span>
          <input
            type="number"
            inputMode="decimal"
            min={minDep}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="bg-[#131313] rounded-lg px-3 py-2.5 text-white font-mono text-base outline-none border border-transparent focus:border-[#bf81ff]"
            placeholder={`${minDep}`}
          />
        </label>

        {/* Error */}
        {error ? (
          <div className="bg-[#ff7166]/10 text-[#ff7166] text-xs p-2 rounded">{error}</div>
        ) : null}

        {/* Hint */}
        <p className="text-[10px] text-[#494847] leading-snug">
          Tap to record your allocation intent — we'll open SoDex's vault page so you
          can complete the wallet-signed deposit. Mark it confirmed in History when done.
        </p>

        {/* CTA */}
        <button
          type="button"
          disabled={!address || tooLow || allocate.isPending}
          onClick={submit}
          className="bg-[#bf81ff] hover:bg-[#a865e6] disabled:bg-[#494847] disabled:text-[#adaaaa] text-black font-headline font-bold text-sm uppercase tracking-widest py-3 rounded-lg transition"
        >
          {allocate.isPending ? 'Recording…' : '⚓ OPEN ON SODEX'}
        </button>
      </div>
    </div>
  );
}
