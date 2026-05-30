import { NavLink, useLocation } from 'react-router-dom';
import { useRef, useState } from 'react';
import type { ReactNode } from 'react';
// import { usePrivy } from '@privy-io/react-auth';
import { useQuery } from '@tanstack/react-query';
import { useSwitchChain, useChains } from 'wagmi';
import { config } from '../config';
import { useWallet } from '../hooks/useWallet';
import { useFeedMode } from '../hooks/useFeedMode';
import NetworkBadge from './NetworkBadge';
import ModePicker from './ModePicker';

const navItems = [
  { to: '/', icon: 'bolt', label: 'Feed', fill: true },
  { to: '/agent', icon: 'smart_toy', label: 'Agent' },
  { to: '/portfolio', icon: 'account_balance_wallet', label: 'Portfolio' },
  { to: '/profile', icon: 'person', label: 'Profile' },
];

/** Persistent testnet notice. Copy is chain-neutral; actions are chain-keyed. */
const FAUCETS: Record<number, { label: string; url: string }> = {
  1952: { label: 'Get OKB', url: 'https://www.okx.com/xlayer/faucet' },
  2124225178762456: { label: 'Get INIT', url: 'https://app.testnet.initia.xyz/faucet' },
  2910: { label: 'Get Hoodi ETH', url: import.meta.env.VITE_MORPH_HOODI_FAUCET_URL || 'https://hoodi.ethpandaops.io/' },
};

function TestnetBanner() {
  const { openBridge, isConnected, chainId } = useWallet();
  const faucet = chainId !== undefined ? FAUCETS[chainId] : undefined;
  const showBridge = isConnected && chainId === 2124225178762456;
  return (
    <div className="bg-[#1a1a00] border-b border-[#ffb84d]/20 px-4 py-2 flex items-center justify-between gap-2 shrink-0">
      <span className="text-[11px] text-[#ffb84d] font-label">
        ⚠️ The Kinetic App works on testnet only.
      </span>
      <div className="flex gap-2 shrink-0">
        {faucet && (
          <a
            href={faucet.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] font-bold text-[#0e0e0e] bg-[#ffb84d] px-2 py-0.5 rounded"
          >
            {faucet.label}
          </a>
        )}
        {showBridge && (
          <button
            onClick={() => openBridge({ srcChainId: 'initiation-2', srcDenom: 'uinit', dstChainId: config.chainId, dstDenom: 'uinit' })}
            className="text-[10px] font-bold text-[#ffb84d] border border-[#ffb84d]/40 px-2 py-0.5 rounded"
          >
            Bridge to evm-1
          </button>
        )}
      </div>
    </div>
  );
}

/** Header wallet pill — current chain + clickable dropdown to switch networks + disconnect.
 *
 * SOLID single-responsibility: owns wallet identity + network selection. The chain
 * list is sourced from the registered wagmi chains so adding a chain is a one-line
 * config edit, no UI changes. Disconnect is the trailing action.
 */
function WalletPill({ address, streak, onLogout }: {
  address: string;
  streak: number;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const { chainId } = useWallet();
  const { switchChainAsync, isPending } = useSwitchChain();
  // Source of truth: registered wagmi chains (main.tsx). Adding a chain is a
  // one-line edit there + one row in NetworkBadge.META. No UI changes here.
  const chains = useChains().map(c => c.id);

  const pick = async (id: number) => {
    try { await switchChainAsync({ chainId: id }); } catch { /* user cancelled or wallet rejected */ }
    setOpen(false);
  };

  return (
    <div className="relative">
      <button onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 bg-[#131313] px-3 py-1.5 rounded-lg border border-[#494847]/15">
        <NetworkBadge chainId={chainId} />
        <span className="text-[#8eff71] font-label font-bold text-sm tracking-tight">
          {address.slice(0, 6)}...{address.slice(-4)}
        </span>
        {streak > 0 && <span className="text-[#ff7166] font-headline font-bold text-sm">🔥{streak}</span>}
      </button>
      {open && (
        <>
          {/* click-outside dismiss */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute top-full right-0 mt-1 bg-[#131313] rounded-lg border border-[#494847]/30 min-w-[220px] z-50 shadow-xl">
            <div className="px-3 py-2 text-[10px] font-label uppercase tracking-widest text-[#494847]">Network</div>
            {chains.map(id => (
              <button key={id} disabled={isPending} onClick={() => pick(id)}
                className="w-full flex items-center justify-between px-3 py-2 hover:bg-[#262626] disabled:opacity-50">
                <NetworkBadge chainId={id} size="md" />
                {chainId === id && <span className="text-[#8eff71] text-xs">✓</span>}
              </button>
            ))}
            <div className="border-t border-[#494847]/20 mt-1">
              <button onClick={() => { setOpen(false); onLogout(); }}
                className="w-full text-left px-3 py-2 text-[#ff7166] font-label text-sm hover:bg-[#262626]">
                Disconnect
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { address: walletAddress, isConnected: authenticated, login, logout } = useWallet();
  const location = useLocation();
  // The mode picker only makes sense on the feed (which lives at '/').
  const isFeed = location.pathname === '/';
  const { activeMode, setActiveMode } = useFeedMode();
  const [pickerOpen, setPickerOpen] = useState(false);
  const pillRef = useRef<HTMLButtonElement>(null);

  const { data: rewardsData } = useQuery({
    queryKey: ['rewards', walletAddress],
    queryFn: async () => {
      const resp = await fetch(`${config.backendUrl}/api/rewards/${walletAddress}`);
      return resp.ok ? resp.json() : null;
    },
    enabled: !!walletAddress,
    staleTime: 60_000,
  });
  const streak = rewardsData?.currentStreak || 0;

  return (
    <div className="h-screen flex flex-col bg-[#0e0e0e] overflow-hidden">
      {/* Testnet Banner */}
      <TestnetBanner />
      {/* Header */}
      <header className="flex justify-between items-center px-5 py-3 shrink-0 z-50">
        <div className="flex items-center gap-2 sm:gap-3 min-w-0">
          <img src="/app.png" alt="KINETIC" className="w-8 h-8 rounded-full object-cover shrink-0" />
          <h1 className="text-xl sm:text-2xl font-black text-[#8eff71] italic font-headline tracking-tight">KINETIC</h1>
          {isFeed && (
            <button
              ref={pillRef}
              onClick={() => setPickerOpen((o) => !o)}
              aria-haspopup="dialog"
              aria-expanded={pickerOpen}
              className="ml-1 flex items-center gap-1.5 bg-[#131313] px-2.5 py-1.5 rounded-lg border border-[#494847]/30 hover:border-[#8eff71]/40 active:scale-95 transition-all"
            >
              <span className="text-base leading-none">{activeMode.emoji}</span>
              <span className="hidden sm:inline text-[#adaaaa] font-label font-bold text-xs">{activeMode.label}</span>
              <span className="text-[#494847] text-[10px] leading-none">▾</span>
            </button>
          )}
        </div>
        {authenticated && walletAddress ? (
          <WalletPill address={walletAddress} streak={streak} onLogout={logout} />
        ) : (
          <button onClick={login}
            className="ape-gradient px-4 py-1.5 rounded-lg text-[#0b5800] font-headline font-bold text-sm">
            Connect
          </button>
        )}
      </header>
      {isFeed && (
        <ModePicker
          open={pickerOpen}
          onOpenChange={setPickerOpen}
          activeId={activeMode.id}
          onSelect={setActiveMode}
          anchorRef={pillRef}
        />
      )}

      {/* Main */}
      <main className="flex-1 overflow-y-auto overflow-x-hidden">
        {children}
      </main>

      {/* Bottom Nav */}
      <nav className="shrink-0 flex justify-around items-center px-4 pb-6 pt-2 bg-[#0e0e0e]/80 backdrop-blur-md z-50">
        {navItems.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === '/'}
            className={({ isActive }) =>
              `flex flex-col items-center justify-center transition-colors ${isActive ? 'text-[#8eff71] scale-110' : 'text-[#adaaaa] opacity-50 hover:text-[#bf81ff]'
              }`
            }>
            <span className="material-symbols-outlined"
              style={item.fill ? { fontVariationSettings: "'FILL' 1" } : undefined}>
              {item.icon}
            </span>
            <span className="font-body font-semibold text-[10px] uppercase tracking-widest mt-1">
              {item.label}
            </span>
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
