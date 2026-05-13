import { useState, useCallback } from 'react';

declare global {
  interface Window { freighterApi?: any; }
}

/**
 * Stellar wallet hook (Freighter extension).
 * Used for funding escrows on the Signal Marketplace.
 */
export function useStellarWallet() {
  const [address, setAddress] = useState('');
  const [connected, setConnected] = useState(false);

  const connect = useCallback(async () => {
    const freighter = window.freighterApi;
    if (!freighter) {
      window.open('https://www.freighter.app/', '_blank');
      return;
    }
    const { address: addr } = await freighter.getAddress();
    if (addr) {
      setAddress(addr);
      setConnected(true);
    }
  }, []);

  const signXdr = useCallback(async (xdr: string): Promise<string> => {
    const freighter = window.freighterApi;
    if (!freighter) throw new Error('Freighter not installed');
    const { signedTxXdr } = await freighter.signTransaction(xdr, { networkPassphrase: 'Test SDF Network ; September 2015' });
    return signedTxXdr;
  }, []);

  const disconnect = useCallback(() => {
    setAddress('');
    setConnected(false);
  }, []);

  return { address, connected, connect, disconnect, signXdr };
}
