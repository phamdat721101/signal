# Trading Tinder — Comprehensive Product Context

Agent reference document. Synthesized from source code analysis + Notion requirements.

---

## 1. Two Product Visions (Current State vs Target)

### Current Codebase: "Initia Signal"
AI-powered on-chain trading signal platform on Initia EVM appchain. Desktop-first dashboard. Signals generated via EMA/RSI technical analysis, stored on-chain, executed with one-click auto-signing.

### Target Vision (Notion): "Ape or Fade" (Trading Tinder)
Mobile-first, privacy-preserving token discovery app. TikTok-style vertical card feed. Swipe right = Ape (buy), swipe left = Fade (skip). AI-generated sarcastic/hype summaries. ZK-private trade execution on Base Network. L402 micropayments.

### Gap Analysis
| Dimension | Current (Initia Signal) | Target (Ape or Fade) |
|-----------|------------------------|---------------------|
| Platform | Desktop web (React SPA) | Mobile-first (React Native + Expo) |
| Chain | Initia EVM appchain | Base Network (Ethereum L2) |
| UX | Dashboard + signal feed + charts | TikTok-style swipe cards |
| AI | EMA/RSI technical indicators | OpenAI LLM content generation + DexScreener data |
| Privacy | Public on-chain signals | ZK proofs via Noir (anonymous trades) |
| Payments | MPP Session Vault (iUSD) | L402/x402 micropayments (USDC) |
| Data Source | Slinky Oracle + CoinGecko | DexScreener API + GeckoTerminal |
| Trade Execution | Signal recording (no actual swap) | Real token swaps via 1inch on Base |
| Content Style | Technical analysis (patterns, RSI) | Sarcastic AI roasts + meme imagery |

---

## 2. Target Product: "Ape or Fade" — Full Spec

### 2.1 What Is It
A mobile-first, privacy-preserving token discovery app. Replaces order books and candle charts with a TikTok-style vertical card feed. Each card introduces one obscure crypto token with an AI-generated, sarcastic or hype summary drawn from live on-chain data. No charts to read. No wallets to manually connect. No public traces. Just swipe.

### 2.2 Core Actions
- **Swipe Right → APE**: Buy the token. ZK proof generated on-device, trade executed anonymously via relayer on Base.
- **Swipe Left → FADE**: Skip the token. AI logs preference silently. $0.05 USDC deducted via L402.

### 2.3 Three Engines

#### Engine 1 — Content Engine
- **Powered by**: OpenAI, DexScreener API, GeckoTerminal
- **Function**: Always-on AI agent that polls DexScreener every 5 minutes for trending/anomalous tokens on Base Network
- **Detects**: Liquidity spikes, dev wallet locks, whale accumulation, abnormal volume
- **Output**: Structured card object with token name, hook (sarcastic one-liner), roast (AI analysis), metrics (volume, liquidity, whale activity), AI image prompt
- **Storage**: Supabase real-time database
- **Card JSON example**:
```json
{
  "token": "$WOJAK",
  "hook": "Another dog coin? Groundbreaking.",
  "roast": "But a whale just bought 5% of supply 3 mins ago and the dev wallet is locked. Ape at your own risk.",
  "metrics": ["🚨 Volume +400% in 1h", "🔒 Liquidity Locked 180d", "🐋 Whale wallet entered @ $0.0003"],
  "ai_image_prompt": "wojak crying in front of a rocket going to the moon"
}
```

#### Engine 2 — Execution Engine
- **Powered by**: L402 Protocol, x402 on Base, Base Network
- **No subscription, no in-app purchases** — every action is a micro-transaction ($0.05 USDC) settled on Base
- **Every API call returns HTTP 402 Payment Required** → background wallet auto-pays
- **User pre-authorizes up to $5/day** in micro-payments at onboarding
- **On "Ape" swipe**: routes full trade size ($10/$50/$100 USDC) to ZK Relayer for execution

#### Engine 3 — Privacy Engine
- **Powered by**: Noir Lang, Ethereum ZK Proofs, Base Network
- **Users deposit USDC into a shared smart contract pool** on Base (not personal wallet)
- **On swipe right**: app generates ZK Proof locally on-device (~1-2 seconds)
- **ZK Proof communicates only**: "A valid user with sufficient funds wants to buy $50 of Token X" — without revealing who
- **Relayer** validates proof, executes trade anonymously via 1inch API
- **Result**: Front-running and copy-trading become impossible

### 2.4 User Flow

**Phase 1 — Onboarding (< 2 minutes)**
1. Download app
2. Connect/create wallet (email/social login via embedded wallet — Privy or Dynamic)
3. Deposit USDC into ZK Pool on Base (e.g., $100)
4. Set default "Ape" size: $10 / $50 / $100 per swipe
5. Authorize daily L402 micro-payment limit (e.g., $5/day)
6. Feed starts loading

Key rule: No seed phrases. No gas fee warnings. No chain selection. Just deposit and go.

**Phase 2 — The Scroll (Core Loop)**
Each token card contains: token name + chain, AI-generated meme image, sarcastic/hype summary, live metrics (volume, liquidity, whale activity), Ape/Fade buttons.

- Swipe Left (Fade): Card dismissed, AI logs preference, next card loads, $0.05 deducted via L402
- Swipe Right (Ape): $0.05 L402 payment, ZK Proof generated (~1-2s), proof sent to relayer, 1inch routes swap, rocket animation, trade confirmation in ~3-5s, P&L tracking begins

**Phase 3 — Retention & Gamification**
- "I Told You So" Notification Engine: AI roasts you for fading a 10x token, celebrates your wins
- ZK Leaderboards: Cryptographic "Proof of Profit" showing win rate/ROI without revealing wallet/identity
- Shareable "Proof of Alpha" cards for Twitter/X
- AI Personalization Loop: Every swipe trains the AI on risk tolerance and preferences

### 2.5 Implementation Modules

**Module 1 — Data Scraper & AI Content Engine**
- Tech: Python or Node.js backend, DexScreener API, OpenAI API, Supabase
- Components: Token Scraper Service, AI Card Generator, Card Storage & Feed API

**Module 2 — L402 Micro-Payment Paywall**
- Tech: x402-express middleware, Base Network, USDC
- Components: L402 Middleware Layer, Background Wallet Client (Mobile), Payment Receipt Verification

**Module 3 — ZK Execution Relayer**
- Tech: Noir Lang, Ethers.js, 1inch API, Base Network
- Components: USDC Deposit Pool Contract (Solidity), ZK Circuit (Noir), ZK Proof Generator (Mobile), Relayer Service (Node.js)

**Module 4 — Mobile Frontend (React Native)**
- Tech: React Native + Expo, react-native-deck-swiper, Privy/Dynamic embedded wallet, react-native-reanimated
- Components: Onboarding Screens, Token Card Component, Trade Execution Flow, Portfolio & P&L Screen, Notification Engine, ZK Leaderboard Screen

Builder's Principle: Ship one engine at a time. Module 1 first → validate content. Then payments. Then privacy. Then full UI.

---

## 3. Existing Codebase Assets (Reusable)

### 3.1 Backend (Python FastAPI) — Partially Reusable
| Component | Reusability | Notes |
|-----------|-------------|-------|
| `signal_engine.py` | Refactor | Replace EMA/RSI with DexScreener scraper + OpenAI card generation |
| `main.py` | Refactor | API structure reusable, add L402 middleware, new card endpoints |
| `config.py` | Reuse | Pydantic settings pattern works, update env vars for Base |
| `scheduler.py` | Reuse | APScheduler for polling DexScreener every 5 min |
| `db.py` | Reuse | Supabase integration already built |
| `mpp_middleware.py` | Replace | Replace MPP with x402/L402 protocol |
| `chain.py` | Refactor | Switch from Initia to Base Network web3 connection |

### 3.2 Frontend (React) — Major Rewrite Needed
| Component | Reusability | Notes |
|-----------|-------------|-------|
| `SignalCard.tsx` | Redesign | Replace with swipeable token card (TikTok-style) |
| `useSignalActions.ts` | Refactor | Replace InterwovenKit with Privy/Dynamic + ZK proof flow |
| `config/index.ts` | Refactor | Switch chain config from Initia to Base |
| Design system | Replace | Use "Kinetic Terminal" design system from signal-ui/ape_x_high_frequency/DESIGN.md |

### 3.3 Smart Contracts (Solidity) — Partial Rewrite
| Contract | Reusability | Notes |
|----------|-------------|-------|
| `SignalRegistry.sol` | Replace | Need USDC Deposit Pool + ZK Verifier contracts on Base |
| `SessionVault.sol` | Partial | Session concept maps to L402 pre-authorization |
| `MockIUSD.sol` | Drop | Use real USDC on Base |

### 3.4 Design Assets (signal-ui/) — Directly Usable
11 HTML mockups with screenshots already exist:
- `ape_or_fade_feed/` — Main swipe feed UI
- `trade_execution_success/` — Ape confirmation screen
- `proof_of_alpha_card/` — Shareable win card
- `proof_of_regret_card/` — "I told you so" roast card
- `fade_regret_radar/` — Missed opportunity tracker
- `portfolio_alpha_leaderboard/` — ZK leaderboard
- `onboarding_setup/` — Wallet setup flow
- `withdraw_funds/` — Fund withdrawal
- `withdrawal_success/` — Withdrawal confirmation
- `transaction_history/` — Trade history
- `ape_x_high_frequency/DESIGN.md` — Full "Kinetic Terminal" design system

---

## 4. Design System: "The Kinetic Terminal"

### Colors
- Background: `#0e0e0e` (Pure Void)
- Primary/Ape: `#8eff71` (Radioactive green — success, longing, ape-in)
- Tertiary/Fade: `#ff7166` (Danger red — shorting, liquidation)
- Secondary/ZK-AI: `#bf81ff` (Purple — AI insights, ZK features)

### Rules
- No 1px borders — use background color shifts for boundaries
- Glass & gradient effects on action buttons (135° gradient, 12px glow)
- Typography: Space Grotesk (bold numbers), Inter (body text)
- Sharp corners (max 0.75rem) — aggressive, precision-engineered aesthetic
- Numbers are the hero — massive typographic weight for data
- Purple exclusively for AI/ZK features to distinguish machine intelligence

---

## 5. Tech Stack Summary (Target)

| Layer | Stack |
|-------|-------|
| Mobile | React Native + Expo |
| Backend | Python FastAPI (or Node.js) |
| AI | OpenAI API (content generation) |
| Data | DexScreener API, GeckoTerminal, Supabase |
| Payments | x402/L402 protocol, USDC on Base |
| Privacy | Noir Lang (ZK circuits), on-device proof generation |
| Chain | Base Network (Ethereum L2) |
| Wallet | Privy or Dynamic (embedded wallet SDK) |
| Trade Routing | 1inch API |
| Animations | react-native-reanimated |
| Swipe UI | react-native-deck-swiper |

---

## 6. Key Protocols & Resources

| Protocol | Purpose | Link |
|----------|---------|------|
| x402 / L402 | Micro-payment paywall | https://l402.org/ |
| Noir Lang | ZK circuit language | https://noir-lang.org/ |
| DexScreener | Token data source | https://docs.dexscreener.com/ |
| OpenAI | LLM content generation | https://platform.openai.com/docs |
| 1inch | DEX aggregator / trade routing | https://docs.1inch.io/ |
| Base Network | Execution chain | https://base.org/ |
| Supabase | Real-time database | https://supabase.com/ |
| Privy | Embedded wallet SDK | https://www.privy.io/ |

---

*Generated 2026-04-15 — Synthesized from source code analysis + Notion "trading tinder" page (343ae753-f26b-803e-bb94-df7f602d8f57)*
