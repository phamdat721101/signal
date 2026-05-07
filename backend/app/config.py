from pydantic_settings import BaseSettings
from functools import lru_cache


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
    # x402 Agent Payment (Base/USDC)
    x402_receiver_address: str = ""
    x402_facilitator_url: str = "https://x402.org/facilitator"
    x402_network: str = "eip155:84532"
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

    @property
    def json_rpc_url(self) -> str:
        return self.testnet_json_rpc_url if self.network == "testnet" else self.local_json_rpc_url

    @property
    def lcd_url(self) -> str:
        return self.testnet_lcd_url if self.network == "testnet" else self.local_lcd_url

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
