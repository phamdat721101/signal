import type { ReactNode } from 'react';
import { useChains } from 'wagmi';
import { useWallet } from '../hooks/useWallet';

/**
 * Per-page chain gate.
 *
 * Renders `children` only when the connected wallet is on `chainId`. Falls
 * back to a cyber-terminal CTA otherwise (Connect → Switch). Used to wrap any
 * surface that mutates chain state (signs typed-data, reads contracts, etc.)
 * so the rest of the page can render normally on any chain.
 *
 * SOLID:
 *  - Single responsibility: gate one chain, render one CTA per state.
 *  - Open/closed: chain id is a prop. Add a future gate by reusing this
 *    component, no logic changes.
 *  - Resolves chain name from the registered wagmi chains so adding a chain
 *    to main.tsx is enough to surface its label here.
 */
export default function ChainGate({ chainId, children }: { chainId: number; children: ReactNode }) {
  const { isConnected, login, isCorrectChain, switchToCorrect, isSwitchingChain, switchChainError } =
    useWallet({ expectedChainId: chainId });
  const chainName = useChains().find((c) => c.id === chainId)?.name ?? `chain ${chainId}`;

  if (!isConnected) {
    return (
      <div className="border border-cyber-outline bg-cyber-surface p-6 text-center font-cyber">
        <p className="text-cyber-green text-sm uppercase tracking-widest mb-3">Wallet Required</p>
        <p className="text-white/70 text-xs mb-4">Connect to use paid agent services on {chainName}.</p>
        <button onClick={login}
          className="bg-cyber-green text-cyber-carbon font-cyber-display font-bold uppercase px-6 py-2 hover:bg-cyber-green-dim active:scale-95 transition">
          Connect Wallet
        </button>
      </div>
    );
  }

  if (!isCorrectChain) {
    return (
      <div className="border border-cyber-outline bg-cyber-surface p-6 text-center font-cyber">
        <p className="text-cyber-green text-sm uppercase tracking-widest mb-3">Switch Network</p>
        <p className="text-white/70 text-xs mb-4">Paid agent services run on <span className="text-cyber-green">{chainName}</span> only.</p>
        <button onClick={switchToCorrect} disabled={isSwitchingChain}
          className="bg-cyber-green text-cyber-carbon font-cyber-display font-bold uppercase px-6 py-2 hover:bg-cyber-green-dim active:scale-95 transition disabled:opacity-50">
          {isSwitchingChain ? 'Switching…' : `Switch to ${chainName}`}
        </button>
        {switchChainError && (
          <p className="text-cyber-pink text-[10px] mt-3 font-cyber">{switchChainError.message}</p>
        )}
      </div>
    );
  }

  return <>{children}</>;
}
