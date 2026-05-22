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
    # ── Initia-Native helpers (this PRD; populated post-deploy) ──
    oracle_adapter_address: str = ""
    cosmos_utils_view_address: str = ""
    cosmos_dispatcher_address: str = ""
    ibc_settlement_hook_address: str = ""
    vip_score_adapter_address: str = ""
    connect_oracle_address: str = ""        # ConnectOracle precompile/contract on the chain
    # x402 Agent Payment (Base/USDC)
    x402_receiver_address: str = ""
    x402_facilitator_url: str = "https://api.cdp.coinbase.com/platform/v2/x402"
    x402_network: str = "eip155:84532"
    x402_public_base_url: str = ""  # e.g. https://ai.overguild.com/agent-api — for Bazaar resource URLs
    cdp_api_key_id: str = ""
    cdp_api_key_secret: str = ""

    # ── Morph Rails x402 (parallel rail; toggle via morph_x402_enabled) ──
    # Defaults target Morph Hoodi testnet (chain 2910, facilitator
    # morph-rails-hoodi.morph.network/x402). Mainnet swap: eip155:2818 +
    # facilitator morph-rails.morph.network/x402 + USDC
    # 0xe34c91815d7fc18A9e2148bcD4241d0a5848b693.
    morph_x402_enabled: bool = False
    morph_facilitator_url: str = "https://morph-rails-hoodi.morph.network/x402"
    morph_network: str = "eip155:2910"
    morph_receiver_address: str = ""        # falls back to x402_receiver_address
    morph_asset_address: str = "0xEcF966Cc754BC411E1F1106fbb4e343b835E85E4"
    morph_asset_decimals: int = 18
    morph_asset_name: str = "HoodiTestToken"
    morph_asset_version: str = "1.0"
    morph_access_key: str = ""              # morph_ak_... — from x402 console
    morph_access_secret: str = ""           # morph_sk_... — never log
    morph_public_base_url: str = ""         # e.g. https://ai.overguild.com/morph-api
    # Supabase/Postgres
    database_url: str = ""
    # Claude AI (Bedrock)
    aws_region: str = "us-east-1"
    aws_bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    aws_bearer_token_bedrock: str = ""

    # SoDex DEX integration
    sodex_enabled: bool = False
    sodex_private_key: str = ""
    sodex_account_id: str = ""
    sodex_chain_id: int = 286623
    sodex_max_order_usd: float = 100.0

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
