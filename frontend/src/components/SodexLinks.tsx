/**
 * SodexLinks — verifiable proof-of-execution links for a SoDex trade row.
 *
 * Single Responsibility: render up to three icon-buttons (Pair · Portfolio
 * · Explorer) that open the corresponding SoDex web URL in a new tab, plus
 * an optional fills toggle that lazily fetches the live fills list.
 *
 * Two render modes:
 *   1. Symbol-only (no `tradeId`):   pair + portfolio + explorer.
 *   2. Trade-row (with `tradeId`):   above + fills toggle button.
 *
 * SOLID:
 *   - SRP: only renders links + manages its own expand state. No global
 *     concerns; no business logic; props are the contract.
 *   - DIP: backend URL is read once from `config.backendUrl` (already the
 *     project-wide convention) — never hardcoded.
 *
 * Used by:
 *   - History.tsx (per ⚡ EXECUTE row)
 *   - Portfolio.tsx (per Live SoDex Position row)
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { config } from '../config';

interface SodexLinksPayload {
  symbol_url: string;
  portfolio_url: string;
  explorer_url: string;
  fills?: Array<{ price: string; qty: string; fee: string; ts: number; side: string }>;
}

interface Props {
  /** Token symbol (e.g. `BTC`) — required for the symbol pair URL. */
  symbol: string;
  /** Trade row id; if present, fills toggle is shown and lazy-fetched. */
  tradeId?: number | null;
  /** Compact (icons only) vs labelled (icons + small labels). */
  size?: 'sm' | 'md';
}

const ICON_BTN =
  'inline-flex items-center justify-center w-7 h-7 rounded-md ' +
  'bg-[#1f1f1f] hover:bg-[#2a2a2a] text-[#bf81ff] transition';

function buildSymbolOnlyPayload(symbol: string): SodexLinksPayload {
  // Mirrors backend `sodex_links.build_links` — kept tiny + duplicated
  // intentionally so the FE renders instantly for position rows that
  // don't need a backend round-trip just to know the SoDex pair URL.
  const norm = symbol.toUpperCase().replace(/^V/, '').split(/[-/_]/)[0];
  const pair = `${norm}_USDC`;
  return {
    symbol_url: `https://sodex.com/trade/futures/${pair}`,
    portfolio_url: 'https://sodex.com/portfolio',
    explorer_url: 'https://sodex.com/explorer?blocktype=futures',
  };
}

export default function SodexLinks({ symbol, tradeId, size = 'sm' }: Props) {
  const [expanded, setExpanded] = useState(false);

  // Fills lazy-load: only when expanded AND tradeId provided.
  const { data, isLoading } = useQuery<SodexLinksPayload>({
    queryKey: ['sodex-links', tradeId],
    queryFn: async () => {
      const r = await fetch(`${config.backendUrl}/api/trades/${tradeId}/sodex-links`);
      if (!r.ok) throw new Error('not found');
      return r.json();
    },
    enabled: !!tradeId && expanded,
    staleTime: 60_000,
    retry: 0,
  });

  const payload = data ?? buildSymbolOnlyPayload(symbol);
  const fills = payload.fills ?? [];
  const showLabels = size === 'md';

  return (
    <div className="flex flex-col gap-1.5" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center gap-1.5">
        <a className={ICON_BTN} href={payload.symbol_url} target="_blank" rel="noreferrer" title="View pair on SoDex">
          <span className="material-symbols-outlined text-[14px]">candlestick_chart</span>
        </a>
        <a className={ICON_BTN} href={payload.portfolio_url} target="_blank" rel="noreferrer" title="Open SoDex portfolio">
          <span className="material-symbols-outlined text-[14px]">account_balance_wallet</span>
        </a>
        <a className={ICON_BTN} href={payload.explorer_url} target="_blank" rel="noreferrer" title="View on ValueChain explorer">
          <span className="material-symbols-outlined text-[14px]">deployed_code</span>
        </a>
        {tradeId ? (
          <button
            type="button"
            className={ICON_BTN}
            onClick={() => setExpanded((v) => !v)}
            title={expanded ? 'Hide fills' : 'Show fills'}
          >
            <span className="material-symbols-outlined text-[14px]">
              {expanded ? 'expand_less' : 'expand_more'}
            </span>
          </button>
        ) : null}
        {showLabels && (
          <span className="font-label text-[9px] text-[#494847] uppercase tracking-widest ml-1">
            Verify on SoDex
          </span>
        )}
      </div>

      {expanded && tradeId ? (
        <div className="bg-[#0d0d0d] rounded-md p-2 text-[10px] text-[#adaaaa] font-mono">
          {isLoading ? (
            <span>Loading fills…</span>
          ) : fills.length === 0 ? (
            <span>No fills available</span>
          ) : (
            <ul className="space-y-0.5">
              {fills.slice(0, 5).map((f, i) => (
                <li key={i} className="flex justify-between gap-3">
                  <span>{f.side?.toUpperCase()} {f.qty} @ ${f.price}</span>
                  <span className="text-[#494847]">fee ${f.fee}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
