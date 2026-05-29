// Sanity test for n-payment v0.18 — fail fast if SDK shape drifts.
//
// Asserts the Morph Hoodi chain entry exists with the exact USDC address we
// committed to in the proposal. If this test fails, we know upstream changed
// something material before we touched product code.
import { CHAINS } from 'n-payment';

const REQUIRED_USDC = '0x7433b41C6c5e1d58D4Da99483609520255ab661B';
const c = CHAINS['morph-hoodi-testnet'];

if (!c) throw new Error('CHAINS["morph-hoodi-testnet"] missing — n-payment regressed?');
if (c.chainId !== 2910) throw new Error(`chainId expected 2910, got ${c.chainId}`);
if (c.tokens?.USDC !== REQUIRED_USDC) throw new Error(`USDC expected ${REQUIRED_USDC}, got ${c.tokens?.USDC}`);

console.log(`Morph Hoodi: chain ${c.chainId}, USDC ${c.tokens.USDC} ✓`);
console.log(`RPC: ${c.rpcUrl}`);
