import { useState, useCallback, useEffect } from 'react';
import { isConnected, requestAccess, getAddress, signTransaction } from '@stellar/freighter-api';

/**
 * Stellar wallet hook using @stellar/freighter-api.
 * Handles connection, address retrieval, and XDR signing for escrow funding.
 */
export function useStellarWallet() {
  const [address, setAddress] = useState('');
  const [connected, setConnected] = useState(false);
  const [installed, setInstalled] = useState<boolean | null>(null);

  useEffect(() => {
    isConnected().then(({ isConnected: ok }) => {
      setInstalled(ok);
      if (ok) {
        getAddress().then(({ address: addr }) => {
          if (addr) { setAddress(addr); setConnected(true); }
        });
      }
    });
  }, []);

  const connect = useCallback(async () => {
    const { isConnected: ok } = await isConnected();
    if (!ok) {
      window.open('https://www.freighter.app/', '_blank');
      return;
    }
    const { address: addr, error } = await requestAccess();
    if (error) throw new Error(error);
    if (addr) { setAddress(addr); setConnected(true); }
  }, []);

  const signXdr = useCallback(async (xdr: string): Promise<string> => {
    const { signedTxXdr, error } = await signTransaction(xdr, { network: 'TESTNET' });
    if (error) throw new Error(error);
    return signedTxXdr;
  }, []);

  const disconnect = useCallback(() => {
    setAddress('');
    setConnected(false);
  }, []);

  return { address, connected, installed, connect, disconnect, signXdr };
}
