import { useAccount, useChainId, useSendTransaction, useSwitchChain } from 'wagmi';
import { useInterwovenKit } from '@initia/interwovenkit-react';
import { config } from '../config';

/**
 * Unified wallet hook — single source of truth for EVM auth, tx, and chain state.
 * Wraps wagmi (EVM connector) + InterwovenKit (Initia auto-sign / Cosmos UX)
 * so pages never reach into either dependency directly.
 *
 * @param expectedChainId Optional override for the page-level expected chain.
 *   Defaults to `config.chain.id` (Initia testnet for the rest of the app).
 *   Pages that need a different chain (e.g. /agent → Morph Hoodi 2910) pass it
 *   explicitly. `isCorrectChain` and `switchToCorrect()` honor the override.
 */
export function useWallet(opts?: { expectedChainId?: number }) {
  const { address } = useAccount();
  const { isConnected, openConnect, disconnect, hexAddress, autoSign, openBridge } = useInterwovenKit();
  const { sendTransactionAsync } = useSendTransaction();
  const currentChainId = useChainId();
  const { switchChainAsync, isPending: isSwitchingChain, error: switchChainError } = useSwitchChain();

  const walletAddress = hexAddress || address || '';
  const expectedChainId = opts?.expectedChainId ?? config.chain.id;
  const isCorrectChain = !isConnected || currentChainId === expectedChainId;

  const sendTx = async (to: string, data: string, chainId?: number, value?: bigint): Promise<string> => {
    const hash = await sendTransactionAsync({
      to: to as `0x${string}`,
      data: data as `0x${string}`,
      // Caller can target any registered chain (e.g. X Layer 1952 from useSummonTransaction).
      // Defaults to expectedChainId (Initia) for legacy callers like useSwipeSession.
      chainId: chainId ?? expectedChainId,
      // Native value transfer for chains that need a deposit (e.g. Somnia
      // SomniaCardExecutor.batchExecuteFromQueue requires N × per-call STT).
      // Optional — existing callers (Initia / X Layer) leave undefined → 0.
      value: value ?? 0n,
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
