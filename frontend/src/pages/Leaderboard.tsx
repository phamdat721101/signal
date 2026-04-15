import { useQuery } from '@tanstack/react-query';
import { config } from '../config';

const BADGES: Record<string, { label: string; color: string }> = {
  whale: { label: '🐋 Whale', color: 'bg-[#8eff71]/10 text-[#8eff71] border-[#8eff71]/20' },
  degen: { label: '🦍 Degen', color: 'bg-[#bf81ff]/10 text-[#bf81ff] border-[#bf81ff]/20' },
  paper: { label: '🧻 Paper', color: 'bg-[#ff7166]/10 text-[#ff7166] border-[#ff7166]/20' },
};

function getBadge(entry: any) {
  if (entry.apes >= 20) return BADGES.whale;
  if (entry.total_trades >= 10) return BADGES.degen;
  if (entry.fades > entry.apes) return BADGES.paper;
  return null;
}

export default function Leaderboard() {
  const { data, isLoading } = useQuery({
    queryKey: ['leaderboard'],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/leaderboard`);
      if (!resp.ok) throw new Error('Failed');
      return resp.json() as Promise<{ leaderboard: any[] }>;
    },
  });

  const entries = data?.leaderboard ?? [];

  return (
    <div className="p-5 space-y-4">
      <div className="text-center py-4">
        <h1 className="font-headline text-2xl font-black text-white tracking-tight">ALPHA LEADERBOARD</h1>
        <p className="font-label text-[10px] text-[#adaaaa] uppercase tracking-widest mt-1">Top traders by conviction</p>
      </div>

      {isLoading ? (
        <div className="text-center text-[#adaaaa] font-label text-sm py-12">Loading...</div>
      ) : entries.length === 0 ? (
        <div className="bg-[#131313] rounded-xl p-12 text-center">
          <span className="material-symbols-outlined text-5xl text-[#494847] mb-3">leaderboard</span>
          <p className="text-[#494847] text-sm">No traders yet. Be the first to ape.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {entries.map((entry: any, i: number) => {
            const badge = getBadge(entry);
            const addr = entry.user_address || '';
            return (
              <div key={addr} className="bg-[#131313] p-4 rounded-xl flex items-center gap-4">
                {/* Rank */}
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center font-headline font-black text-lg ${
                  i === 0 ? 'bg-[#8eff71]/20 text-[#8eff71]' : i === 1 ? 'bg-[#bf81ff]/20 text-[#bf81ff]' : i === 2 ? 'bg-[#ff7166]/20 text-[#ff7166]' : 'bg-[#262626] text-[#adaaaa]'
                }`}>
                  {i + 1}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="font-headline font-bold text-white text-sm truncate">
                    {addr ? `${addr.slice(0, 6)}...${addr.slice(-4)}` : 'Anon'}
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="font-label text-[10px] text-[#adaaaa]">{entry.total_trades} trades</span>
                    {badge && (
                      <span className={`text-[9px] font-label font-bold px-2 py-0.5 rounded border ${badge.color}`}>
                        {badge.label}
                      </span>
                    )}
                  </div>
                </div>

                {/* Stats */}
                <div className="text-right">
                  <div className="font-headline font-bold text-[#8eff71] text-sm">{entry.apes} apes</div>
                  <div className="font-label text-[10px] text-[#adaaaa]">{entry.fades} fades</div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
