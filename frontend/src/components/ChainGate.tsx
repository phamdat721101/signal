import type { ReactNode } from 'react';
import { useChainId, useChains } from 'wagmi';
import { useWallet } from '../hooks/useWallet';

/**
 * Per-page chain gate.
 *
 * Renders `children` when the connected wallet is on ANY of the accepted
 * chain ids. Otherwise shows a cyber-terminal CTA (Connect → Switch).
 *
 * SOLID:
 *  - Single responsibility: gate one or more chains, render one CTA per
 *    state. Nothing else.
 *  - Open/closed: chains is a prop. Add a future supported chain by
 *    appending to the array — no logic changes.
 *  - Resolves chain names from registered wagmi chains so adding a chain
 *    in `main.tsx` is enough to surface its label here.
 */
export default function ChainGate({
  chainIds,
  children,
}: {
  /** One or more chain IDs that satisfy the gate. */
  chainIds: number[];
  children: ReactNode;
}) {
  const currentChainId = useChainId();
  const allowed = chainIds.includes(currentChainId);
  // When on an unsupported chain, "Switch" defaults to the first listed.
  const target = allowed ? currentChainId : chainIds[0];
  const {
    isConnected, login, switchToCorrect, isSwitchingChain, switchChainError,
  } = useWallet({ expectedChainId: target });
  const allChains = useChains();
  const labels = chainIds
    .map((id) => allChains.find((c) => c.id === id)?.name ?? `chain ${id}`);

  if (!isConnected) {
    return (
      <div className="border border-cyber-outline bg-cyber-surface p-6 text-center font-cyber">
        <p className="text-cyber-green text-sm uppercase tracking-widest mb-3">Wallet Required</p>
        <p className="text-white/70 text-xs mb-4">
          Connect to use paid agent services on{' '}
          <span className="text-cyber-green">{labels.join(' or ')}</span>.
        </p>
        <button onClick={login}
          className="bg-cyber-green text-cyber-carbon font-cyber-display font-bold uppercase px-6 py-2 hover:bg-cyber-green-dim active:scale-95 transition">
          Connect Wallet
        </button>
      </div>
    );
  }

  if (!allowed) {
    const targetName = allChains.find((c) => c.id === target)?.name ?? `chain ${target}`;
    return (
      <div className="border border-cyber-outline bg-cyber-surface p-6 text-center font-cyber">
        <p className="text-cyber-green text-sm uppercase tracking-widest mb-3">Switch Network</p>
        <p className="text-white/70 text-xs mb-4">
          Paid agent services run on{' '}
          <span className="text-cyber-green">{labels.join(' or ')}</span>.
        </p>
        <button onClick={switchToCorrect} disabled={isSwitchingChain}
          className="bg-cyber-green text-cyber-carbon font-cyber-display font-bold uppercase px-6 py-2 hover:bg-cyber-green-dim active:scale-95 transition disabled:opacity-50">
          {isSwitchingChain ? 'Switching…' : `Switch to ${targetName}`}
        </button>
        {switchChainError && (
          <p className="text-cyber-pink text-[10px] mt-3 font-cyber">{switchChainError.message}</p>
        )}
      </div>
    );
  }

  return <>{children}</>;
}
