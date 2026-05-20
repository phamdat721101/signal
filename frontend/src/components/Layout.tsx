import { NavLink } from 'react-router-dom';
import type { ReactNode } from 'react';
// import { usePrivy } from '@privy-io/react-auth';
import { useQuery } from '@tanstack/react-query';
import { config } from '../config';
import { useWallet } from '../hooks/useWallet';

const navItems = [
  { to: '/', icon: 'bolt', label: 'Feed', fill: true },
  { to: '/marketplace', icon: 'storefront', label: 'Market' },
  { to: '/agent', icon: 'smart_toy', label: 'Agent' },
  { to: '/portfolio', icon: 'account_balance_wallet', label: 'Portfolio' },
  { to: '/profile', icon: 'person', label: 'Profile' },
];

/** Inline banner — visible on every page when wallet is on the wrong EVM chain. */
function ChainSwitchBanner() {
  const { isConnected, isCorrectChain, isSwitchingChain, switchChainError, switchToCorrect, expectedChainName } = useWallet();
  if (!isConnected || isCorrectChain) return null;
  return (
    <div className="mx-4 mt-2 bg-[#131313] border border-[#ff7166]/30 rounded-xl px-3 py-2 flex items-center justify-between gap-3">
      <span className="text-xs text-[#adaaaa] truncate">
        ⚠️ Wrong network — switch to <span className="text-white font-bold">{expectedChainName}</span> to continue
        {switchChainError && <span className="block text-[10px] text-[#ff7166] mt-0.5">{switchChainError.message}</span>}
      </span>
      <button
        onClick={() => { void switchToCorrect(); }}
        disabled={isSwitchingChain}
        className="text-xs font-bold text-[#0b5800] ape-gradient px-3 py-1 rounded-lg disabled:opacity-50 shrink-0">
        {isSwitchingChain ? 'Switching...' : 'Switch'}
      </button>
    </div>
  );
}

/** Persistent testnet notice with gas faucet + bridge actions. */
function TestnetBanner() {
  const { openBridge, isConnected } = useWallet();
  return (
    <div className="bg-[#1a1a00] border-b border-[#ffb84d]/20 px-4 py-2 flex items-center justify-between gap-2 shrink-0">
      <span className="text-[11px] text-[#ffb84d] font-label">
        ⚠️ The Kinetic App is currently available only on Testnet.
      </span>
      <div className="flex gap-2 shrink-0">
        <a href="https://app.testnet.initia.xyz" target="_blank" rel="noopener noreferrer"
          className="text-[10px] font-bold text-[#0e0e0e] bg-[#ffb84d] px-2 py-0.5 rounded">
          Get INIT
        </a>
        {isConnected && (
          <button onClick={() => openBridge({ srcChainId: 'initiation-2', srcDenom: 'uinit', dstChainId: config.chainId, dstDenom: 'uinit' })}
            className="text-[10px] font-bold text-[#ffb84d] border border-[#ffb84d]/40 px-2 py-0.5 rounded">
            Bridge to evm-1
          </button>
        )}
      </div>
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { address: walletAddress, isConnected: authenticated, login, logout } = useWallet();
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
        <div className="flex items-center gap-3">
          <img src="/app.png" alt="KINETIC" className="w-8 h-8 rounded-full object-cover" />
          <h1 className="text-2xl font-black text-[#8eff71] italic font-headline tracking-tight">KINETIC</h1>
        </div>
        {authenticated && walletAddress ? (
          <button onClick={logout}
            className="flex items-center bg-[#131313] px-3 py-1.5 rounded-lg border border-[#494847]/15">
            <span className="text-[#8eff71] font-label font-bold text-sm tracking-tight">
              {walletAddress.slice(0, 6)}...{walletAddress.slice(-4)}
            </span>
            {streak > 0 && <span className="text-[#ff7166] font-headline font-bold text-sm ml-1">🔥{streak}</span>}
          </button>
        ) : (
          <button onClick={login}
            className="ape-gradient px-4 py-1.5 rounded-lg text-[#0b5800] font-headline font-bold text-sm">
            Connect
          </button>
        )}
      </header>

      {/* Main */}
      <main className="flex-1 overflow-y-auto overflow-x-hidden">
        <ChainSwitchBanner />
        {children}
      </main>

      {/* Bottom Nav */}
      <nav className="shrink-0 flex justify-around items-center px-4 pb-6 pt-2 bg-[#0e0e0e]/80 backdrop-blur-md z-50">
        {navItems.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === '/'}
            className={({ isActive }) =>
              `flex flex-col items-center justify-center transition-colors ${
                isActive ? 'text-[#8eff71] scale-110' : 'text-[#adaaaa] opacity-50 hover:text-[#bf81ff]'
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
