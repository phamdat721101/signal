from pydantic_settings import BaseSettings
from pathlib import Path

_ENV_FILE = str(Path(__file__).resolve().parent.parent / ".env")


class Settings(BaseSettings):
    network: str = "local"
    local_json_rpc_url: str = "http://localhost:8545"
    local_lcd_url: str = "http://localhost:1317"
    testnet_json_rpc_url: str = "https://jsonrpc-evm-1.anvil.asia-southeast.initia.xyz"
    testnet_lcd_url: str = "https://lcd.preyominet-1.initia.tech"
    private_key: str = ""
    contract_address: str = ""
    signal_interval_minutes: int = 2
    signal_resolve_timeout_hours: int = 24
    # MPP Session Vault
    session_vault_address: str = ""
    mock_iusd_address: str = ""
    payment_gateway_address: str = ""
    reward_engine_address: str = ""
    proof_of_alpha_address: str = ""
    conviction_engine_address: str = ""
    tucana_router_address: str = ""
    enable_payment_gating: bool = True
    free_signals_per_day: int = 3
    # Energy gating — when False, /ape and /fade skip consume_energy and
    # /api/energy returns is_premium=true unconditionally. Default False so
    # demos and judge runs aren't blocked by daily-swipe caps.
    energy_gating_enabled: bool = False
    # ── Initia-Native helpers (this PRD; populated post-deploy) ──
    oracle_adapter_address: str = ""
    cosmos_utils_view_address: str = ""
    cosmos_dispatcher_address: str = ""
    ibc_settlement_hook_address: str = ""
    vip_score_adapter_address: str = ""
    connect_oracle_address: str = ""        # ConnectOracle precompile/contract on the chain
    # ── X Layer (Hook the Future) — chain 1952 testnet, 196 mainnet ──
    xlayer_testnet_json_rpc_url: str = "https://testrpc.xlayer.tech"
    xlayer_mainnet_json_rpc_url: str = "https://rpc.xlayer.tech"
    signal_card_nft_address: str = ""
    signal_card_hook_address: str = ""
    signal_card_router_address: str = ""
    okb_address_xlayer: str = ""
    usdc_address_xlayer: str = ""
    xlayer_pool_manager_address: str = ""
    # ── Somnia testnet (chain 50312) ──
    somnia_signal_registry_address: str = ""
    somnia_conviction_engine_address: str = ""
    somnia_oracle_adapter_address: str = ""
    somnia_signal_agent_address: str = ""
    somnia_session_vault_address: str = ""
    somnia_mock_stt_address: str = ""
    # Agentathon additions: executor + B2B verdict market.
    somnia_card_executor_address: str = ""
    somnia_agent_market_address: str = ""
    # Somnia x402 REST rail (parallel to Base CDP; route prefix /somnia-api).
    # Toggle via SOMNIA_X402_ENABLED=true. Receiver falls back to x402_receiver_address.
    somnia_x402_enabled: bool = False
    somnia_x402_network: str = "eip155:50312"
    somnia_x402_facilitator_url: str = "https://api.cdp.coinbase.com/platform/v2/x402"
    somnia_x402_receiver_address: str = ""
    somnia_x402_public_base_url: str = ""
    # ── Flap on X-Layer (PRD: Flap Hidden Gems on X-Layer v1) ──
    flap_portal_xlayer_address: str = "0xb30D8c4216E1f21F27444D2FfAee3ad577808678"
    flap_taxed_fun_board_url: str = "https://xlayer.taxed.fun/v2/board"
    # x402 Agent Payment (Base/USDC)
    x402_receiver_address: str = ""
    x402_facilitator_url: str = "https://api.cdp.coinbase.com/platform/v2/x402"
    x402_network: str = "eip155:84532"
    x402_public_base_url: str = ""  # e.g. https://ai.overguild.com/agent-api — for Bazaar resource URLs
    cdp_api_key_id: str = ""
    cdp_api_key_secret: str = ""

    # Supabase/Postgres
    database_url: str = ""
    # Claude AI (Bedrock)
    aws_region: str = "us-east-1"
    aws_bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    aws_bearer_token_bedrock: str = ""

    # SoDex DEX integration
    sodex_enabled: bool = False
    sodex_private_key: str = ""           # legacy (master wallet); kept for backward-compat
    sodex_api_key_name: str = ""          # name string passed in `X-API-Key` (e.g. "kinetic-bot-01")
    sodex_api_key_privkey: str = ""       # private key whose pubkey is the API-key's registered EVM addr
    sodex_account_id: str = ""
    sodex_chain_id: int = 138565          # default = SoDex testnet (mainnet = 286623)
    sodex_max_order_usd: float = 25.0     # tight risk cap (Wave-2 demo)
    sodex_max_leverage: int = 2           # tight risk cap
    sodex_daily_executes_per_user: int = 5
    sodex_trading_enabled: bool = False   # global kill-switch for /execute endpoint
    sodex_target_assets: str = "BTC,ETH,SOL,AVAX,SUI,ARB,OP,LINK,INIT,ATOM"
    # Master account address for the public read of pool balance (no signing
    # required by SoDex). Defaults to the known testnet master so the Profile
    # "SoDex Trading Pool" panel works even when the trading client is off.
    sodex_master_address: str = "0x100690a32B562fd45e685BC2E63bbfF566d452db"

    # SosoValue
    sosovalue_api_key: str = ""

    # News sources
    cryptopanic_api_key: str = ""

    # Stellar / Trustless Work
    trustless_api_key: str = ""
    trustless_api_url: str = "https://dev.api.trustlesswork.com"
    stellar_network: str = "testnet"
    stellar_platform_address: str = ""
    stellar_platform_secret: str = ""
    stellar_fee_address: str = ""
    stellar_admin_address: str = ""

    # Energy System (Tinder model)
    energy_max: int = 5
    energy_cost_standard: int = 1
    energy_cost_premium: int = 2

    # Admin
    admin_token: str = ""

    # Scalability
    db_pool_min: int = 5
    db_pool_max: int = 20
    log_level: str = "INFO"
    log_json: bool = False  # set true in production for structured logs

    @property
    def json_rpc_url(self) -> str:
        return self.testnet_json_rpc_url if self.network == "testnet" else self.local_json_rpc_url

    @property
    def lcd_url(self) -> str:
        return self.testnet_lcd_url if self.network == "testnet" else self.local_lcd_url

    # ── EVM gas params (network-derived; documented in product_context.md) ──
    # Initia evm-1 testnet quirk: forge gas estimator under-counts ~60k of
    # Cosmos-layer fee accounting. CALL txs need ≥250k limit and ≥0.1 gwei
    # gas price. Local minievm accepts gasPrice=0 and lower limits.
    @property
    def evm_gas_price_wei(self) -> int:
        return 100_000_000 if self.network == "testnet" else 0  # 0.1 gwei vs free

    @property
    def evm_min_gas_limit(self) -> int:
        return 250_000 if self.network == "testnet" else 100_000

    class Config:
        env_file = _ENV_FILE


_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
