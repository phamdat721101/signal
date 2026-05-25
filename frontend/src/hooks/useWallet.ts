import { useAccount, useChainId, useSendTransaction, useSwitchChain } from 'wagmi';
import { useInterwovenKit } from '@initia/interwovenkit-react';
import { config } from '../config';

/**
 * Unified wallet hook — single source of truth for EVM auth, tx, and chain state.
 * Wraps wagmi (EVM connector) + InterwovenKit (Initia auto-sign / Cosmos UX)
 * so pages never reach into either dependency directly.
 *
 * Note: chain default is set in main.tsx via InterwovenKitProvider.defaultChainId,
 * not here — the wagmi connector inherits whatever chain the InterwovenKit wallet
 * boots on. switchToCorrect() remains available for any future case where the
 * wagmi config registers more than one chain.
 */
export function useWallet() {
  const { address } = useAccount();
  const { isConnected, openConnect, disconnect, hexAddress, autoSign, openBridge } = useInterwovenKit();
  const { sendTransactionAsync } = useSendTransaction();
  const currentChainId = useChainId();
  const { switchChainAsync, isPending: isSwitchingChain, error: switchChainError } = useSwitchChain();

  const walletAddress = hexAddress || address || '';
  const expectedChainId = config.chain.id;
  const isCorrectChain = !isConnected || currentChainId === expectedChainId;

  const sendTx = async (to: string, data: string, chainId?: number): Promise<string> => {
    const hash = await sendTransactionAsync({
      to: to as `0x${string}`,
      data: data as `0x${string}`,
      // Caller can target any registered chain (e.g. X Layer 1952 from useSummonTransaction).
      // Defaults to expectedChainId (Initia) for legacy callers like useSwipeSession.
      chainId: chainId ?? expectedChainId,
    });
    return hash;
  };

  const switchToCorrect = async () => {
    if (isCorrectChain) return;
    await switchChainAsync({ chainId: expectedChainId });
  };

  return {
    address: walletAddress,
    isConnected,
    login: openConnect,
    logout: disconnect,
    sendTx,
    autoSign,
    openBridge,
    chainId: currentChainId,
    expectedChainId,
    expectedChainName: config.chain.name,
    isCorrectChain,
    isSwitchingChain,
    switchChainError,
    switchToCorrect,
  };
}
