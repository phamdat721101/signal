import { NavLink } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useInterwovenKit } from '@initia/interwovenkit-react';

const navItems = [
  { to: '/', icon: 'bolt', label: 'Feed', fill: true },
  { to: '/leaderboard', icon: 'leaderboard', label: 'Ranks' },
  { to: '/portfolio', icon: 'account_balance_wallet', label: 'Portfolio' },
  { to: '/history', icon: 'receipt_long', label: 'History' },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { initiaAddress, openConnect, openWallet } = useInterwovenKit();

  return (
    <div className="h-screen flex flex-col bg-[#0e0e0e] overflow-hidden">
      {/* Header */}
      <header className="flex justify-between items-center px-5 py-3 shrink-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-[#262626] flex items-center justify-center text-[#8eff71] font-bold text-sm">
            {initiaAddress ? initiaAddress.slice(-2).toUpperCase() : '??'}
          </div>
          <h1 className="text-2xl font-black text-[#8eff71] italic font-headline tracking-tight">KINETIC</h1>
        </div>
        {initiaAddress ? (
          <button onClick={openWallet}
            className="flex items-center bg-[#131313] px-3 py-1.5 rounded-lg border border-[#494847]/15">
            <span className="text-[#8eff71] font-label font-bold text-sm tracking-tight">
              {initiaAddress.slice(0, 6)}...{initiaAddress.slice(-4)}
            </span>
          </button>
        ) : (
          <button onClick={openConnect}
            className="ape-gradient px-4 py-1.5 rounded-lg text-[#0b5800] font-headline font-bold text-sm">
            Connect
          </button>
        )}
      </header>

      {/* Main */}
      <main className="flex-1 overflow-y-auto overflow-x-hidden">
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
