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
    enable_payment_gating: bool = True
    free_signals_per_day: int = 3
    # Supabase/Postgres
    database_url: str = ""

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
