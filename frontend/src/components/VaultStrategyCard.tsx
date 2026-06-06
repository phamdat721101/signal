/**
 * VaultStrategyCard — feed-style card for `card_type === 'vault'`.
 *
 * Single Responsibility: render the vault descriptor + raise the
 * "ALLOCATE TO VAULT" intent via callback. No fetches, no allocation
 * logic, no chain calls — the parent (Feed.tsx) opens the Configurator
 * sheet which handles the rest.
 *
 * Visual spec aligns with LpBattleCard: same fixed feed-card height to
 * preserve CLS budget (Design Principle §10.2). Differentiator: ⚓ VAULT
 * pill in header, dual-yield label list, lockup banner, no token-pair
 * range chart (vaults aren't position-based).
 */
import type { Card } from '../hooks/useCards';

interface Props {
  card: Card;
  onAllocate: () => void;
}

interface VaultMeta {
  vault_kind?: string;
  accepted_assets?: string[];
  lockup_label?: string;
  yield_sources?: string[];
  min_deposit_usd?: number;
  short_name?: string;
  index_ticker?: string;
  live?: {
    nav_usd?: number;
    change_24h_pct?: number;
    roi_7d_pct?: number;
    roi_1m_pct?: number;
    roi_3m_pct?: number;
    roi_1y_pct?: number;
    ytd_pct?: number;
  };
}

function fmtPct(n?: number | null) {
  if (n == null || !isFinite(n)) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}
function fmtUsd(n?: number | null) {
  if (n == null || !isFinite(n)) return '—';
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export default function VaultStrategyCard({ card, onAllocate }: Props) {
  const meta = ((card as unknown as { research_summary?: VaultMeta }).research_summary) || {};
  const accepted = meta.accepted_assets ?? [card.token0_symbol, card.token1_symbol].filter(Boolean) as string[];
  const yields = meta.yield_sources ?? [];
  const lockup = meta.lockup_label ?? card.roast ?? '';
  const minDep = meta.min_deposit_usd ?? 50;
  const live = meta.live || {};
  const hasLive = (live.nav_usd ?? 0) > 0;
  const change = live.change_24h_pct ?? 0;
  const changeColor = change >= 0 ? '#8eff71' : '#ff7166';

  return (
    <div className="w-full max-w-sm mx-auto rounded-2xl overflow-hidden select-none">
      <div className="p-[2px] rounded-2xl bg-gradient-to-br from-[#bf81ff]/40 via-[#bf81ff]/10 to-[#8eff71]/40">
        <div className="bg-[#0e0e0e] rounded-2xl overflow-hidden p-4 flex flex-col gap-4 relative min-h-[480px]">
          <div className="absolute -top-10 -left-10 w-32 h-32 bg-[#bf81ff]/10 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute -bottom-10 -right-10 w-32 h-32 bg-[#8eff71]/10 rounded-full blur-3xl pointer-events-none" />

          {/* Header */}
          <div className="flex items-center justify-between relative z-10">
            <div className="flex items-center gap-2">
              <div className="w-10 h-10 rounded-lg bg-[#bf81ff]/15 flex items-center justify-center">
                <span className="material-symbols-outlined text-[#bf81ff] text-xl"
                      style={{ fontVariationSettings: "'FILL' 1" }}>anchor</span>
              </div>
              <div>
                <div className="font-headline font-bold text-white text-base">{card.token_name || card.token_symbol}</div>
                <div className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest">SoDEX Vault</div>
              </div>
            </div>
            <span className="text-[9px] font-label font-bold px-2 py-0.5 rounded bg-[#bf81ff]/15 text-[#bf81ff]">
              ⚓ VAULT
            </span>
          </div>

          {/* Live MAG7.SSI metrics — single SoSoValue snapshot covers both vaults. */}
          {hasLive ? (
            <div className="bg-[#131313] rounded-lg p-3 grid grid-cols-2 gap-2 relative z-10">
              <div className="flex flex-col">
                <span className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest">MAG7 NAV</span>
                <span className="font-headline text-lg font-bold text-white">{fmtUsd(live.nav_usd)}</span>
                <span className="text-[10px] font-mono" style={{ color: changeColor }}>{fmtPct(change)} · 24h</span>
              </div>
              <div className="grid grid-cols-2 gap-1.5 text-[10px] font-mono">
                <span className="text-[#adaaaa]">7d</span>
                <span className="text-right" style={{ color: (live.roi_7d_pct ?? 0) >= 0 ? '#8eff71' : '#ff7166' }}>{fmtPct(live.roi_7d_pct)}</span>
                <span className="text-[#adaaaa]">1m</span>
                <span className="text-right" style={{ color: (live.roi_1m_pct ?? 0) >= 0 ? '#8eff71' : '#ff7166' }}>{fmtPct(live.roi_1m_pct)}</span>
                <span className="text-[#adaaaa]">YTD</span>
                <span className="text-right" style={{ color: (live.ytd_pct ?? 0) >= 0 ? '#8eff71' : '#ff7166' }}>{fmtPct(live.ytd_pct)}</span>
              </div>
            </div>
          ) : null}

          {/* Narrative */}
          {card.hook ? (
            <p className="text-sm text-[#e6e6e6] leading-snug relative z-10">{card.hook}</p>
          ) : null}

          {/* Yield sources */}
          {yields.length > 0 && (
            <div className="relative z-10">
              <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest mb-1.5">Dual Yield</div>
              <ul className="space-y-1">
                {yields.map((y, i) => (
                  <li key={i} className="flex items-center gap-2 text-xs text-white">
                    <span className="material-symbols-outlined text-[14px] text-[#8eff71]">spark</span>
                    {y}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Accepted assets + lockup */}
          <div className="grid grid-cols-2 gap-2 relative z-10">
            <div className="bg-[#131313] rounded-lg p-2.5">
              <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest">Accepted</div>
              <div className="text-xs text-white font-mono mt-0.5 truncate">{accepted.join(' · ') || '—'}</div>
            </div>
            <div className="bg-[#131313] rounded-lg p-2.5">
              <div className="font-label text-[9px] text-[#adaaaa] uppercase tracking-widest">Lockup</div>
              <div className="text-xs text-white mt-0.5 leading-tight">{lockup || 'Instant'}</div>
            </div>
          </div>

          {/* Min deposit ribbon */}
          <div className="bg-[#131313] rounded-lg p-2.5 flex items-center justify-between relative z-10">
            <span className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest">Min Deposit</span>
            <span className="font-headline text-sm font-bold text-white">${minDep.toFixed(0)}</span>
          </div>

          {/* CTA */}
          <button
            type="button"
            onClick={onAllocate}
            className="mt-auto bg-[#bf81ff] hover:bg-[#a865e6] active:bg-[#9851d8] text-black font-headline font-bold text-sm uppercase tracking-widest py-3 rounded-lg transition relative z-10"
          >
            ⚓ ALLOCATE TO VAULT
          </button>
        </div>
      </div>
    </div>
  );
}
