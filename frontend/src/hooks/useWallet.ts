import { useAccount, useSendTransaction } from 'wagmi';
import { useInterwovenKit } from '@initia/interwovenkit-react';
import { config } from '../config';

/**
 * Unified wallet hook replacing all Privy usage.
 * Single source of truth for auth state and transaction sending.
 */
export function useWallet() {
  const { address } = useAccount();
  const { isConnected, openConnect, disconnect, hexAddress, autoSign } = useInterwovenKit();
  const { sendTransactionAsync } = useSendTransaction();

  const walletAddress = hexAddress || address || '';

  const sendTx = async (to: string, data: string): Promise<string> => {
    const hash = await sendTransactionAsync({
      to: to as `0x${string}`,
      data: data as `0x${string}`,
      chainId: config.chain.id,
    });
    return hash;
  };

  return {
    address: walletAddress,
    isConnected,
    login: openConnect,
    logout: disconnect,
    sendTx,
    autoSign,
  };
}
