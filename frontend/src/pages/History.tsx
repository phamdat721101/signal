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
