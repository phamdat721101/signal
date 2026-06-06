/**
 * useAllocateVault — POST /api/cards/{id}/allocate-vault
 *
 * Single Responsibility: HTTP adapter for the vault allocation intent.
 * On success, opens `target_url` in a new tab so the user can finish
 * the wallet-signed deposit on sodex.com (no programmatic deposit
 * endpoint exists in the SoDex Trading API).
 *
 * 409 (already allocated today) and 422 (below min deposit) surface as
 * structured errors the UI maps to friendly copy.
 */
import { useMutation } from '@tanstack/react-query';
import { config } from '../config';

export interface AllocateResult {
  allocation_id: number;
  target_url: string;
  vault_kind: string;
  intent_amount_usd: number;
  status: 'pending' | 'confirmed';
}

interface AllocateInput {
  cardId: number;
  address: string;
  intentAmountUsd: number;
}

async function postAllocate({ cardId, address, intentAmountUsd }: AllocateInput): Promise<AllocateResult> {
  const r = await fetch(`${config.backendUrl}/api/cards/${cardId}/allocate-vault`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address, intent_amount_usd: intentAmountUsd }),
  });
  if (!r.ok) {
    let detail = `HTTP_${r.status}`;
    try { const j = await r.json(); if (j?.detail) detail = String(j.detail); } catch {}
    const err = new Error(detail) as Error & { status: number };
    err.status = r.status;
    throw err;
  }
  return r.json();
}

export function useAllocateVault() {
  return useMutation({
    mutationFn: postAllocate,
    onSuccess: (r) => {
      // Hand off to SoDex web UI for the wallet-signed deposit.
      if (r.target_url) window.open(r.target_url, '_blank', 'noopener,noreferrer');
    },
  });
}

export interface ConfirmInput {
  allocationId: number;
  address: string;
}

async function postConfirm({ allocationId, address }: ConfirmInput): Promise<{ status: 'confirmed'; allocation_id: number }> {
  const r = await fetch(`${config.backendUrl}/api/vault-allocations/${allocationId}/confirm`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ address }),
  });
  if (!r.ok) throw new Error(`HTTP_${r.status}`);
  return r.json();
}

export function useConfirmAllocation() {
  return useMutation({ mutationFn: postConfirm });
}
