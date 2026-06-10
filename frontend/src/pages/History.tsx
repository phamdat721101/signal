// import { usePrivy } from '@privy-io/react-auth';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { config, normalizeAddress } from '../config';
import { useWallet } from '../hooks/useWallet';
import SodexLinks from '../components/SodexLinks';
import { useConfirmAllocation } from '../hooks/useAllocateVault';

export default function History() {
  const { address: walletAddr } = useWallet();
  const initiaAddress = normalizeAddress(walletAddr);
  const qc = useQueryClient();
  const confirmAlloc = useConfirmAllocation();

  const { data, isLoading } = useQuery({
    queryKey: ['history', initiaAddress],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/cards/user/${initiaAddress}`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json() as Promise<{ swipes: any[]; total: number }>;
    },
    enabled: !!initiaAddress,
  });

  const swipes = data?.swipes ?? [];

  if (!initiaAddress) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 px-6">
        <span className="material-symbols-outlined text-6xl text-[#494847]">receipt_long</span>
        <p className="text-[#adaaaa] font-label text-sm uppercase tracking-widest">Connect wallet to view history</p>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="font-headline text-xl font-bold text-white">Terminal History</h1>
        <span className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest">{swipes.length} swipes</span>
      </div>

      <CrossChainSwipesSection userAddress={initiaAddress} />

      {isLoading ? (
        <div className="text-center text-[#adaaaa] font-label text-sm py-12">Loading...</div>
      ) : swipes.length === 0 ? (
        <div className="bg-[#131313] rounded-xl p-12 text-center">
          <span className="material-symbols-outlined text-5xl text-[#494847] mb-3">swipe</span>
          <p className="text-[#494847] text-sm">No swipes yet. Hit the feed.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {swipes.map((s: any) => {
            const isExecute = s.action === 'execute';
            const isApe = s.action === 'ape';
            const isAllocate = s.action === 'allocate';
            const ts = s.created_at ? new Date(s.created_at).toLocaleDateString() : '';
            // 4-way visual branch: APE / EXECUTE / FADE / ALLOCATE.
            const tone = isAllocate
              ? { bg: 'bg-[#bf81ff]/10', fg: 'text-[#bf81ff]', icon: 'anchor', filled: true,  badge: s.vault_status === 'confirmed' ? 'CONFIRMED' : 'PENDING', subtitle: s.hook || `${s.vault_kind} vault` }
              : isExecute
              ? { bg: 'bg-[#bf81ff]/10', fg: 'text-[#bf81ff]', icon: 'bolt', filled: true,  badge: 'EXECUTE',  subtitle: 'Order placed on SoDex testnet' }
              : isApe
              ? { bg: 'bg-[#8eff71]/10', fg: 'text-[#8eff71]', icon: 'bolt', filled: true,  badge: 'APE',      subtitle: s.hook || s.token_name || '' }
              : { bg: 'bg-[#ff7166]/10', fg: 'text-[#ff7166]', icon: 'close', filled: false, badge: 'FADE',     subtitle: s.hook || s.token_name || '' };
            return (
              <div key={s.id} className="bg-[#131313] p-4 rounded-xl flex flex-col gap-2">
                <div className="flex items-center gap-3">
                  {/* Action icon */}
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${tone.bg}`}>
                    <span className={`material-symbols-outlined text-lg ${tone.fg}`}
                      style={tone.filled ? { fontVariationSettings: "'FILL' 1" } : undefined}>
                      {tone.icon}
                    </span>
                  </div>

                  {/* Token info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-headline font-bold text-white text-sm">${s.token_symbol}</span>
                      <span className={`text-[9px] font-label font-bold px-2 py-0.5 rounded ${tone.bg} ${tone.fg}`}>
                        {tone.badge}
                      </span>
                    </div>
                    <div className="font-label text-[10px] text-[#adaaaa] mt-0.5">{tone.subtitle}</div>
                  </div>

                  {/* Price + date */}
                  <div className="text-right shrink-0">
                    {isApe && s.price_change_24h != null && (
                      <div className={`font-headline font-bold text-sm ${s.price_change_24h >= 0 ? 'text-[#8eff71]' : 'text-[#ff7166]'}`}>
                        {s.price_change_24h >= 0 ? '+' : ''}{s.price_change_24h.toFixed(1)}%
                      </div>
                    )}
                    <div className="font-label text-[10px] text-[#adaaaa]">{ts}</div>
                  </div>
                </div>

                {/* Verifiable proof links — only on EXECUTE rows that have a backing trade row. */}
                {isExecute && s.trade_id ? (
                  <div className="pl-13">
                    <SodexLinks symbol={s.token_symbol} tradeId={s.trade_id} />
                  </div>
                ) : null}

                {/* On-chain proof — render an explorer link for any swipe that has a tx hash. */}
                {s.explorer_url ? (
                  <div className="pl-13">
                    <a
                      href={s.explorer_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[10px] font-label text-sky-400 hover:underline"
                      aria-label="View transaction on block explorer"
                    >
                      🔗 View tx on explorer
                    </a>
                  </div>
                ) : null}

                {/* Vault allocation: confirm button on PENDING rows. */}
                {isAllocate && s.vault_status === 'pending' && s.vault_allocation_id ? (
                  <div className="pl-13 flex items-center gap-2">
                    <a className="text-[10px] font-label text-[#bf81ff] underline"
                       href={s.vault_target_url || '#'} target="_blank" rel="noreferrer">
                      Open SoDex →
                    </a>
                    <button
                      type="button"
                      disabled={confirmAlloc.isPending}
                      onClick={() => {
                        confirmAlloc.mutate(
                          { allocationId: s.vault_allocation_id, address: initiaAddress },
                          { onSuccess: () => qc.invalidateQueries({ queryKey: ['history', initiaAddress] }) },
                        );
                      }}
                      className="text-[10px] font-label font-bold uppercase tracking-widest px-2 py-1 rounded bg-[#bf81ff] text-black hover:bg-[#a865e6] disabled:bg-[#494847] disabled:text-[#adaaaa]"
                    >
                      {confirmAlloc.isPending ? '…' : 'Mark as deposited'}
                    </button>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}



// ─────────────────────────────────────────────────────────────────
//  CrossChainSwipesSection — v3 cross-chain history surface.
//  Reads `/api/v3/lifi-intents/by-user/:addr` and renders rows with
//  verdict + outcome flags + 3 click-through proof links.
//
//  SOLID:
//    - SRP: a self-contained section. The legacy swipe table above
//      is untouched.
//    - DIP: depends only on fetch + the typed response shape.
// ─────────────────────────────────────────────────────────────────
type CrossChainIntent = {
  intent_id: string;
  prophecy_market_id: number;
  swipe_stake_usdc: number;
  status: 'PENDING' | 'DELIVERED' | 'EXECUTED' | 'FAILED_REFUNDED';
  verdict_id: number | null;
  verdict_str: 'APE' | 'FADE' | null;
  outcome_resolved: boolean;
  outcome_correct: boolean | null;
  arbiscan_url: string | null;
  somnscan_url: string | null;
  prophecy_market_url: string | null;
  created_at: string | null;
  outcome_resolved_at: string | null;
};

function CrossChainSwipesSection({ userAddress }: { userAddress: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['cross-chain-history', userAddress],
    enabled: !!userAddress,
    refetchInterval: 15_000,
    queryFn: async () => {
      const r = await fetch(`${config.backendUrl}/api/v3/lifi-intents/by-user/${userAddress}`);
      if (!r.ok) throw new Error('Failed');
      return r.json() as Promise<{ intents: CrossChainIntent[]; total: number }>;
    },
  });
  const intents = data?.intents ?? [];

  if (!userAddress) return null;
  if (isLoading) return <p className="text-[#adaaaa] text-xs">Loading cross-chain swipes…</p>;
  if (intents.length === 0) return null;   // hide section entirely if no rows

  return (
    <section className="bg-[#131313] rounded-xl p-4 space-y-3">
      <header className="flex items-center justify-between">
        <h2 className="font-headline text-sm font-bold text-white">Cross-chain swipes</h2>
        <span className="text-[10px] font-label text-[#adaaaa] uppercase tracking-widest">{intents.length} rows</span>
      </header>
      <ul className="space-y-2">
        {intents.map((i) => <CrossChainSwipeRow key={i.intent_id} intent={i} />)}
      </ul>
    </section>
  );
}

function CrossChainSwipeRow({ intent }: { intent: CrossChainIntent }) {
  const stake = (intent.swipe_stake_usdc / 1_000_000).toFixed(2);
  const verdictColor =
    intent.verdict_str === 'APE'  ? 'text-emerald-400' :
    intent.verdict_str === 'FADE' ? 'text-rose-400'    : 'text-zinc-500';
  const statusBadge =
    intent.status === 'EXECUTED'        ? { tint: 'bg-sky-500/15',    fg: 'text-sky-300',    label: 'EXECUTED' } :
    intent.status === 'FAILED_REFUNDED' ? { tint: 'bg-rose-500/15',   fg: 'text-rose-300',   label: 'REFUNDED' } :
                                          { tint: 'bg-amber-500/15',  fg: 'text-amber-300',  label: intent.status };
  const outcomeBadge =
    !intent.outcome_resolved             ? { tint: 'bg-zinc-700/40',     fg: 'text-zinc-400',  label: 'PENDING' } :
    intent.outcome_correct === true      ? { tint: 'bg-emerald-500/20',  fg: 'text-emerald-300', label: 'WIN'  } :
    intent.outcome_correct === false     ? { tint: 'bg-rose-500/20',     fg: 'text-rose-300',   label: 'LOSS' } :
                                           { tint: 'bg-zinc-700/40',     fg: 'text-zinc-400',   label: 'NO VERDICT' };

  return (
    <li className="bg-[#0d0d0d] rounded-lg p-3 space-y-2 border border-white/5">
      <div className="flex items-center justify-between text-[11px] font-mono text-zinc-400">
        <span>market #{intent.prophecy_market_id}</span>
        <span>${stake}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className={`text-sm font-bold ${verdictColor}`}>
          {intent.verdict_str ?? '—'}
        </span>
        <span className={`text-[10px] px-2 py-0.5 rounded ${statusBadge.tint} ${statusBadge.fg}`}>
          {statusBadge.label}
        </span>
        <span className={`text-[10px] px-2 py-0.5 rounded ${outcomeBadge.tint} ${outcomeBadge.fg}`}>
          {outcomeBadge.label}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-[11px]">
        {intent.arbiscan_url && (
          <a href={intent.arbiscan_url} target="_blank" rel="noopener noreferrer"
             className="text-sky-400 hover:underline" aria-label="View origin transaction on Arbiscan">
            🔗 Arbiscan
          </a>
        )}
        {intent.somnscan_url && (
          <a href={intent.somnscan_url} target="_blank" rel="noopener noreferrer"
             className="text-sky-400 hover:underline" aria-label="View destination transaction on Somnscan">
            🔗 Somnscan
          </a>
        )}
        {intent.prophecy_market_url && (
          <a href={intent.prophecy_market_url} target="_blank" rel="noopener noreferrer"
             className="text-sky-400 hover:underline" aria-label="View prophecy market">
            🔗 Market
          </a>
        )}
      </div>
    </li>
  );
}
