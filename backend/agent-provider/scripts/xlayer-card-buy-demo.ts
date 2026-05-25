/**
 * X Layer Card-Buy Demo — Agent path for Hook the Future hackathon.
 *
 * Flow:
 *   1. Agent hits POST /api/cards/{id}/buy → gets 402 challenge
 *   2. Agent pays via x402-fetch (uses Uniswap-AI pay-with-any-token if available)
 *   3. Agent receives card NFT
 *   4. Agent calls SignalCardRouter.playCard → LP opens via SignalCardHook
 *
 * Run:
 *   export AGENT_PRIVATE_KEY=0x...   # funded with MockOKB on X Layer testnet
 *   export AGENT_API_URL=https://ai.overguild.com
 *   export ROUTER_ADDRESS=0x...      # from .env.testnet
 *   npx tsx scripts/xlayer-card-buy-demo.ts
 */
import { createWalletClient, http, encodeFunctionData, parseEther } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { defineChain } from "viem";

const xlayerTestnet = defineChain({
  id: 1952,
  name: "X Layer Testnet",
  nativeCurrency: { name: "OKB", symbol: "OKB", decimals: 18 },
  rpcUrls: { default: { http: ["https://testrpc.xlayer.tech/terigon"] } },
});

const PK = process.env.AGENT_PRIVATE_KEY as `0x${string}`;
const BASE = (process.env.AGENT_API_URL ?? "http://localhost:8001").replace(/\/$/, "");
const ROUTER = process.env.ROUTER_ADDRESS as `0x${string}`;
const CARD_ID = Number(process.env.CARD_ID ?? "1");

if (!PK) { console.error("Set AGENT_PRIVATE_KEY"); process.exit(1); }
if (!ROUTER) { console.error("Set ROUTER_ADDRESS"); process.exit(1); }

const account = privateKeyToAccount(PK);
const wallet = createWalletClient({ account, chain: xlayerTestnet, transport: http() });

console.log("Agent:", account.address);
console.log("Card:", CARD_ID);

// Step 1: Buy card (get 402 challenge)
console.log("\n[1] POST /api/cards/" + CARD_ID + "/buy → expect 402");
const buyResp = await fetch(`${BASE}/api/cards/${CARD_ID}/buy`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ address: account.address }),
});
console.log("Status:", buyResp.status);

if (buyResp.status === 402) {
  const challenge = await buyResp.json();
  console.log("Challenge:", JSON.stringify(challenge.accepts[0], null, 2));

  // Step 2: Pay (simplified for testnet — send x-payment header)
  console.log("\n[2] Paying with x-payment header (testnet mock)...");
  const paidResp = await fetch(`${BASE}/api/cards/${CARD_ID}/buy`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-payment": "testnet-mock-payment",
    },
    body: JSON.stringify({ address: account.address }),
  });
  const paidData = await paidResp.json();
  console.log("Paid:", paidData);
}

// Step 3: Play card via Router
console.log("\n[3] Playing card via SignalCardRouter.playCard...");
const PLAY_ABI = [{
  type: "function", name: "playCard",
  inputs: [
    { name: "cardId", type: "uint256" },
    { name: "liquidity", type: "uint128" },
    { name: "amount0Max", type: "uint256" },
    { name: "amount1Max", type: "uint256" },
    { name: "deadline", type: "uint256" },
  ],
  outputs: [], stateMutability: "nonpayable",
}] as const;

const data = encodeFunctionData({
  abi: PLAY_ABI,
  functionName: "playCard",
  args: [
    BigInt(CARD_ID),
    parseEther("1000"),       // liquidity
    parseEther("100"),        // amount0Max (MockOKB)
    BigInt(100_000_000),      // amount1Max (MockUSDC, 6 dec → 100 USDC)
    BigInt(Math.floor(Date.now() / 1000) + 3600),
  ],
});

const hash = await wallet.sendTransaction({ to: ROUTER, data });
console.log("TX hash:", hash);
console.log("Explorer: https://www.okx.com/web3/explorer/xlayer-test/tx/" + hash);
console.log("\n✅ Card summoned! LP position opened via SignalCardHook.");
