import { NavLink } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useInterwovenKit } from '@initia/interwovenkit-react';
import { truncateAddress } from '../config';

const navItems = [
  { to: '/', label: 'Dashboard', icon: 'H' },
  { to: '/signals', label: 'Signals', icon: 'S' },
  { to: '/portfolio', label: 'Portfolio', icon: 'P' },
  { to: '/leaderboard', label: 'Leaderboard', icon: 'L' },
  { to: '/report', label: 'Report', icon: 'R' },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { initiaAddress, openConnect, openWallet, openBridge } = useInterwovenKit();

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-[var(--color-border)] px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl font-bold text-white">Initia Signal</span>
          <span className="text-xs px-2 py-0.5 rounded bg-[var(--color-accent)] text-white">AI</span>
        </div>
        <nav className="hidden md:flex items-center gap-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `px-4 py-2 rounded-lg text-sm transition-colors ${
                  isActive
                    ? 'bg-[var(--color-surface)] text-white'
                    : 'text-[var(--color-muted)] hover:text-white'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <button
            onClick={() => openBridge({ srcChainId: 'initiation-2', srcDenom: 'uinit' })}
            className="px-3 py-1.5 text-xs bg-green-500/10 border border-green-500/30 text-green-400 rounded-lg hover:bg-green-500/20 transition-colors"
          >
            Bridge
          </button>
          {initiaAddress ? (
            <button
              onClick={openWallet}
              className="px-3 py-1.5 text-xs bg-[var(--color-surface)] border border-[var(--color-border)] text-white rounded-lg font-mono"
            >
              {truncateAddress(initiaAddress)}
            </button>
          ) : (
            <button
              onClick={openConnect}
              className="px-3 py-1.5 text-xs bg-[var(--color-accent)] text-white rounded-lg hover:opacity-90 transition-opacity"
            >
              Connect Wallet
            </button>
          )}
        </div>
      </header>

      {/* Main */}
      <main className="flex-1 p-6 max-w-7xl mx-auto w-full">
        {children}
      </main>

      {/* Mobile Nav */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-[var(--color-surface)] border-t border-[var(--color-border)] flex">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `flex-1 py-3 text-center text-xs transition-colors ${
                isActive ? 'text-white' : 'text-[var(--color-muted)]'
              }`
            }
          >
            <div className="text-lg">{item.icon}</div>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
