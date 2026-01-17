from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://marco:marco@localhost:5432/marco"
    cors_origins: str = "http://localhost:5173"

    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_deployment: str = "gpt-5.2-chat"
    azure_openai_api_version: str = "2024-10-01-preview"

    telemetry_enabled: bool = True
    telemetry_salt: str = "marco-telemetry-salt"

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
