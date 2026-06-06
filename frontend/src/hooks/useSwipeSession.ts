import { useCallback, useEffect, useMemo, useState } from 'react';
import { encodeFunctionData, keccak256, parseEther, toHex } from 'viem';
import { useChainId } from 'wagmi';
import { useInterwovenKit } from '@initia/interwovenkit-react';
import { useWallet } from './useWallet';
import { config } from '../config';
import type { Card } from './useCards';

/**
 * useSwipeSession — local-queue + multi-call settle for Initia Signal.
 *
 * Goal: 50 swipes = 2 wallet popups (start + settle), 0 chain calls per swipe.
 * Oracle is NOT in this path (resolution-only); all entry/target prices come
 * from the off-chain card data already on screen.
 *
 * State machine:
 *   idle (no session) → active (queue grows locally + mirrors to backend)
 *                     → settling (one InterwovenKit requestTxBlock fires N msgs)
 *                     → idle (queue cleared, redirect to /session/:txHash)
 *
 * Atomic mode (default ON):
 *   uses InterwovenKit's requestTxBlock → ONE Cosmos tx with all EVM MsgCalls
 *   bundled. msg.sender is preserved as the user for every internal call.
 *   Toggle off via localStorage key `kinetic_atomic_mode=false` to fall back
 *   to sequential sendTx (legacy behavior, debug only).
 *
 * Recovery: queue is persisted in localStorage; partial settle failures land
 * via chain_operations idempotency on the backend mirror. Resume banner shows
 * if mount finds a non-empty queue with an active session.
 */

const QUEUE_KEY = 'kinetic_swipe_queue_v1';
const SESSION_KEY = 'kinetic_swipe_session_v1';
const ATOMIC_MODE_KEY = 'kinetic_atomic_mode';

// Per-swipe cost charged at settle (backend uses this for SessionVault.payFromSession).
// Keep in sync with backend pricing — currently $0.01 / 50 swipes = $0.0002 each in iUSD.
const COST_PER_SWIPE_WEI = parseEther('0.0002');
const SESSION_DEPOSIT_IUSD = '10';   // 10 iUSD lasts 50_000 swipes
const SESSION_DURATION_HOURS = 24;

export interface QueuedSwipe {
  card_id: number;
  card_hash: string;            // hex 0x… (placeholder until Session-Ritual Task 1 lands a canonical hash)
  asset: `0x${string}`;
  is_bull: boolean;             // ape=true, fade=false
  score: number;                // conviction 1-100
  is_tradeable: boolean;        // APE only — controls whether createSignal fires
  entry_wei: string;            // 18-dec, off-chain card price
  target_wei: string;           // off-chain ±1.5% of entry
  queued_at: number;
  /** Token symbol — populated since Somnia Agentathon (chain 50312) needs the
   * raw symbol string for the on-chain agent prompt. Optional so legacy queue
   * entries (pre-2026-05-28) deserialise without breaking. */
  symbol?: string;
}

export interface SwipeSession {
  session_id: string;           // SessionVault.sessions.length-1 from createSession event
  user: `0x${string}`;
  started_at: number;
  expires_at: number;
}

const SESSION_VAULT_ABI = [
  { name: 'createSession', type: 'function', stateMutability: 'nonpayable',
    inputs: [{ name: 'amount', type: 'uint256' }, { name: 'durationSeconds', type: 'uint256' }],
    outputs: [{ name: 'sessionId', type: 'uint256' }] },
  { name: 'payFromSession', type: 'function', stateMutability: 'nonpayable',
    inputs: [{ name: 'sessionId', type: 'uint256' },
             { name: 'amount', type: 'uint256' },
             { name: 'serviceId', type: 'string' }],
    outputs: [] },
] as const;

const CONVICTION_ABI = [
  { name: 'commitConviction', type: 'function', stateMutability: 'nonpayable',
    inputs: [{ name: 'cardHash', type: 'bytes32' },
             { name: 'score', type: 'uint8' },
             { name: 'isBull', type: 'bool' }],
    outputs: [{ name: '', type: 'uint256' }] },
] as const;

const SIGNAL_REGISTRY_ABI = [
  { name: 'createSignal', type: 'function', stateMutability: 'nonpayable',
    inputs: [{ name: 'asset', type: 'address' }, { name: 'isBull', type: 'bool' },
             { name: 'confidence', type: 'uint8' }, { name: 'targetPrice', type: 'uint256' },
             { name: 'entryPrice', type: 'uint256' }],
    outputs: [{ name: '', type: 'uint256' }] },
] as const;

// Somnia executor — batchExecuteFromQueue takes an array of {symbol, context}.
// One sendTx settles N validator-consensus agent calls atomically per-card.
const SOMNIA_EXECUTOR_ABI = [
  { name: 'batchExecuteFromQueue', type: 'function', stateMutability: 'payable',
    inputs: [{ name: 'queue', type: 'tuple[]', components: [
      { name: 'symbol',  type: 'string' },
      { name: 'context', type: 'string' },
    ] }],
    outputs: [{ name: 'verdictIds', type: 'uint256[]' }] },
] as const;

function symbolToAddress(symbol: string): `0x${string}` {
  const known: Record<string, string> = {
    BTC: '0x0000000000000000000000000000000000000001',
    ETH: '0x0000000000000000000000000000000000000002',
    INIT: '0x0000000000000000000000000000000000000003',
  };
  const upper = symbol.toUpperCase();
  if (known[upper]) return known[upper] as `0x${string}`;
  const hash = keccak256(toHex(upper));
  return `0x${hash.slice(2, 42)}` as `0x${string}`;
}

function placeholderCardHash(card: Card): `0x${string}` {
  // Until docs/PRDs/PRD-OnChain-TradingCard-SessionRitual.md Task 1 lands the canonical
  // backend-computed card_hash, derive a stable per-card hash on the client. This keeps
  // ConvictionEngine commitConviction reachable today; backend resolveCard uses the same
  // recipe so the values match.
  return keccak256(toHex(`${card.id}|${card.token_symbol}|${card.verdict || ''}|${card.created_at}`));
}

function loadQueue(user: string): QueuedSwipe[] {
  try {
    const raw = window.localStorage.getItem(`${QUEUE_KEY}:${user.toLowerCase()}`);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveQueue(user: string, queue: QueuedSwipe[]) {
  try {
    window.localStorage.setItem(`${QUEUE_KEY}:${user.toLowerCase()}`, JSON.stringify(queue));
  } catch { /* quota */ }
}

function loadSession(user: string): SwipeSession | null {
  try {
    const raw = window.localStorage.getItem(`${SESSION_KEY}:${user.toLowerCase()}`);
    if (!raw) return null;
    const s = JSON.parse(raw) as SwipeSession;
    if (s.expires_at < Date.now() / 1000) return null;
    return s;
  } catch { return null; }
}

function saveSession(user: string, session: SwipeSession | null) {
  const k = `${SESSION_KEY}:${user.toLowerCase()}`;
  if (!session) window.localStorage.removeItem(k);
  else window.localStorage.setItem(k, JSON.stringify(session));
}

export function useSwipeSession() {
  const { address, sendTx, isConnected } = useWallet();
  const { requestTxBlock } = useInterwovenKit() as any;  // requestTxBlock typed loosely; SDK exposes it
  const chainId = useChainId();
  const [queue, setQueueState] = useState<QueuedSwipe[]>([]);
  const [session, setSessionState] = useState<SwipeSession | null>(null);
  const [isSettling, setIsSettling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const atomicMode = useMemo(() => {
    if (typeof window === 'undefined') return true;
    if (typeof requestTxBlock !== 'function') return false;  // SDK doesn't expose it → fallback
    return window.localStorage.getItem(ATOMIC_MODE_KEY) !== 'false';
  }, [requestTxBlock]);

  // Hydrate from localStorage on connect
  useEffect(() => {
    if (!address) {
      setQueueState([]); setSessionState(null);
      return;
    }
    setQueueState(loadQueue(address));
    setSessionState(loadSession(address));
  }, [address]);

  const setQueue = useCallback((next: QueuedSwipe[]) => {
    setQueueState(next);
    if (address) saveQueue(address, next);
  }, [address]);

  const setSession = useCallback((next: SwipeSession | null) => {
    setSessionState(next);
    if (address) saveSession(address, next);
  }, [address]);

  /** Start a new session: SessionVault.createSession(10 iUSD, 24h). SIG #1. */
  const startSession = useCallback(async (): Promise<SwipeSession | null> => {
    if (!address || !isConnected) {
      setError('Connect wallet first');
      return null;
    }
    setError(null);
    try {
      const data = encodeFunctionData({
        abi: SESSION_VAULT_ABI,
        functionName: 'createSession',
        args: [parseEther(SESSION_DEPOSIT_IUSD), BigInt(SESSION_DURATION_HOURS * 3600)],
      });
      // Note: this assumes the user has already approved iUSD to SessionVault via useSession.approveAndDeposit.
      // approveAndDeposit already does both approve + createSession — call that from the UI instead of
      // duplicating logic here. This start path is for the case where approval already exists.
      const txHash = await sendTx(config.sessionVaultAddress, data);
      // We don't decode the sessionId from the receipt here (cheap to skip); backend mirror writes it.
      const newSession: SwipeSession = {
        session_id: 'pending',
        user: address as `0x${string}`,
        started_at: Math.floor(Date.now() / 1000),
        expires_at: Math.floor(Date.now() / 1000) + SESSION_DURATION_HOURS * 3600,
      };
      setSession(newSession);
      // Mirror to backend (fire-and-forget — local state is truth)
      void fetch(`${config.backendUrl}/api/swipe-session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user: address, tx_hash: txHash, duration_hours: SESSION_DURATION_HOURS }),
      }).catch(() => {});
      return newSession;
    } catch (e: any) {
      setError(e?.message || 'startSession failed');
      return null;
    }
  }, [address, isConnected, sendTx, setSession]);

  /** Add a swipe to the local queue. Zero chain, zero oracle, zero popups. */
  const queueSwipe = useCallback((card: Card, action: 'ape' | 'fade', score: number) => {
    if (!session || !address) return;
    const isBull = action === 'ape';
    const entryWei = BigInt(Math.round(card.price * 1e18));
    const targetWei = isBull
      ? BigInt(Math.round(card.price * 1.015 * 1e18))
      : BigInt(Math.round(card.price * 0.985 * 1e18));
    const swipe: QueuedSwipe = {
      card_id: card.id,
      card_hash: placeholderCardHash(card),
      asset: symbolToAddress(card.token_symbol),
      is_bull: isBull,
      score: Math.min(100, Math.max(1, Math.round(score))),
      is_tradeable: isBull,
      entry_wei: entryWei.toString(),
      target_wei: targetWei.toString(),
      queued_at: Date.now(),
      symbol: card.token_symbol,
    };
    const next = [...queue, swipe];
    setQueue(next);
    // Mirror — fire and forget; local is truth.
    void fetch(`${config.backendUrl}/api/swipe-session/${session.session_id}/queue`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(swipe),
    }).catch(() => {});
  }, [queue, session, address, setQueue]);

  /** Build the multi-message MsgCall array for InterwovenKit. */
  const buildSettleMessages = useCallback(() => {
    if (!session) return [];
    const msgs: { to: `0x${string}`; data: `0x${string}` }[] = [];
    // 1. createSignal × M (APE only)
    for (const s of queue.filter(q => q.is_tradeable)) {
      msgs.push({
        to: config.contractAddress,
        data: encodeFunctionData({
          abi: SIGNAL_REGISTRY_ABI,
          functionName: 'createSignal',
          args: [s.asset, s.is_bull, s.score, BigInt(s.target_wei), BigInt(s.entry_wei)],
        }),
      });
    }
    // 2. commitConviction × N (every swipe)
    const convictionEngineAddr =
      (import.meta as any).env?.VITE_CONVICTION_ENGINE_ADDRESS as `0x${string}` | undefined;
    if (convictionEngineAddr && convictionEngineAddr !== '0x0000000000000000000000000000000000000000') {
      for (const s of queue) {
        msgs.push({
          to: convictionEngineAddr,
          data: encodeFunctionData({
            abi: CONVICTION_ABI,
            functionName: 'commitConviction',
            args: [s.card_hash as `0x${string}`, s.score, s.is_bull],
          }),
        });
      }
    }
    // 3. payFromSession × 1
    if (session.session_id !== 'pending' && config.sessionVaultAddress) {
      const totalCost = COST_PER_SWIPE_WEI * BigInt(queue.length);
      msgs.push({
        to: config.sessionVaultAddress,
        data: encodeFunctionData({
          abi: SESSION_VAULT_ABI,
          functionName: 'payFromSession',
          args: [BigInt(session.session_id), totalCost, 'swipe-batch'],
        }),
      });
    }
    return msgs;
  }, [queue, session]);

  /** Settle the queue. Atomic mode: 1 sig via requestTxBlock. Fallback: N sequential sigs. */
  const settleSession = useCallback(async (): Promise<string | null> => {
    if (!address || !session || queue.length === 0) return null;
    setIsSettling(true); setError(null);
    try {
      // ── Single chain-id switch point. CI grep must report exactly one
      // match for the literal Somnia branch below. The Initia path runs
      // unchanged through buildSettleMessages() further down.
      // Somnia mode: one sendTx into SomniaCardExecutor.batchExecuteFromQueue.
      // The executor fans out per-card validator-consensus agent calls; the
      // user signs once. Filtered to APE swipes (FADE has no on-chain side
      // effect on Somnia — it stays mirrored in the off-chain swipes table).
      if (chainId === 50312) {
        const executor = config.somnia.cardExecutorAddress;
        if (!executor || executor === '0x0000000000000000000000000000000000000000') {
          throw new Error('Somnia executor not configured');
        }
        const apeQueue = queue.filter(q => q.is_bull && (q.symbol || '').length > 0);
        if (apeQueue.length === 0) {
          // Nothing on-chain to settle — clear local queue (FADE-only batch).
          setQueue([]);
          setIsSettling(false);
          return null;
        }
        const swipesArg = apeQueue.map(q => ({
          symbol: q.symbol as string,
          context: `score=${q.score} entry_wei=${q.entry_wei} target_wei=${q.target_wei}`,
        }));
        const data = encodeFunctionData({
          abi: SOMNIA_EXECUTOR_ABI,
          functionName: 'batchExecuteFromQueue',
          args: [swipesArg],
        });
        // Per-call deposit: 0.07 STT × 3 validators + 0.07 floor ≈ 0.28 STT.
        // Overestimate slightly to stay above the floor under Somnia pricing tweaks.
        const depositPerCall = parseEther('0.3');
        const totalValue = depositPerCall * BigInt(apeQueue.length);
        const txHash = await sendTx(executor, data, /* chainId */ 50312, totalValue);
        if (txHash) {
          void fetch(`${config.backendUrl}/api/swipe-session/${session.session_id}/settle`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tx_hash: txHash, chain_id: 50312 }),
          }).catch(() => {});
        }
        setQueue([]);
        setIsSettling(false);
        return txHash;
      }

      const msgs = buildSettleMessages();
      if (msgs.length === 0) throw new Error('Nothing to settle');
      let txHash: string | null = null;
      if (atomicMode && typeof requestTxBlock === 'function') {
        // ONE Cosmos tx, all EVM MsgCalls, msg.sender preserved per message.
        const result = await requestTxBlock({
          messages: msgs.map(m => ({
            typeUrl: '/minievm.evm.v1.MsgCall',
            value: { sender: address, contract_addr: m.to, input: m.data, value: '0' },
          })),
        });
        txHash = result?.transactionHash || result?.tx_hash || null;
      } else {
        // Fallback: sequential sendTx (legacy; one wallet popup per call).
        for (const m of msgs) {
          // eslint-disable-next-line no-await-in-loop
          txHash = await sendTx(m.to, m.data);
        }
      }
      // Mirror settlement to backend (idempotent — same tx_hash returned on retry)
      if (txHash) {
        void fetch(`${config.backendUrl}/api/swipe-session/${session.session_id}/settle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tx_hash: txHash }),
        }).catch(() => {});
      }
      // Clear local queue on success
      setQueue([]);
      setIsSettling(false);
      return txHash;
    } catch (e: any) {
      setError(e?.message || 'settle failed');
      setIsSettling(false);
      return null;
    }
  }, [address, session, queue, atomicMode, chainId, requestTxBlock, sendTx, buildSettleMessages, setQueue]);

  const clearQueue = useCallback(() => setQueue([]), [setQueue]);
  const closeSession = useCallback(() => setSession(null), [setSession]);

  return {
    session, queue, isSettling, error, atomicMode,
    startSession, queueSwipe, settleSession, clearQueue, closeSession,
    canResume: queue.length > 0 && session !== null,
  };
}
