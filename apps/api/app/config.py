from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./digital_twin.db"
    app_secret_key: str = "change-me-in-production"
    admin_api_secret: str = "change-me-admin-api-secret"
    cors_origins: str = "http://localhost:3000"
    public_web_url: str = "http://localhost:3000"
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_utility_model: str = ""
    openrouter_subagent_model: str = "deepseek/deepseek-v4-pro"
    openrouter_subagent_reasoning_effort: str = "high"
    openrouter_compaction_model: str = "deepseek/deepseek-v4-pro"
    openrouter_acp_council_models: str = ""
    openrouter_acp_council_min_successes: int = 3
    openrouter_acp_chair_model: str = ""
    openrouter_acp_council_timeout_seconds: float = 35.0
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: str = "http://localhost:3000"
    openrouter_app_name: str = "Digital Twin Prototype"
    openviking_base_url: str = ""
    openviking_api_key: str = ""
    openviking_timeout_seconds: float = 20.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def has_openrouter_key(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    @property
    def has_openviking_config(self) -> bool:
        return bool(self.openviking_base_url.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
