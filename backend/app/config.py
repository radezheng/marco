from __future__ import annotations

from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Preferred: set DATABASE_URL directly.
    # Alternative: set PGHOST/PGUSER/PGPORT/PGDATABASE/PGPASSWORD and let us compose it.
    database_url: str | None = None

    pg_host: str | None = Field(default=None, validation_alias="PGHOST")
    pg_user: str | None = Field(default=None, validation_alias="PGUSER")
    pg_port: int | None = Field(default=None, validation_alias="PGPORT")
    pg_database: str | None = Field(default=None, validation_alias="PGDATABASE")
    pg_password: str | None = Field(default=None, validation_alias="PGPASSWORD")
    pg_sslmode: str | None = Field(default=None, validation_alias="PGSSLMODE")

    @model_validator(mode="after")
    def _compose_database_url(self) -> "Settings":
        if self.database_url:
            return self

        any_pg = any(
            [
                self.pg_host,
                self.pg_user,
                self.pg_port is not None,
                self.pg_database,
                self.pg_password,
            ]
        )
        if not any_pg:
            self.database_url = "postgresql+psycopg://marco:marco@localhost:5432/marco"
            return self

        if not (self.pg_host and self.pg_user and self.pg_database):
            raise ValueError(
                "DATABASE_URL is missing. To use PG* env vars, set at least PGHOST, PGUSER, PGDATABASE (PGPORT/PGPASSWORD optional)."
            )

        port = self.pg_port or 5432
        if self.pg_password:
            password = quote_plus(self.pg_password)
            auth = f"{self.pg_user}:{password}@"
        else:
            auth = f"{self.pg_user}@"

        base = f"postgresql+psycopg://{auth}{self.pg_host}:{port}/{self.pg_database}"
        if self.pg_sslmode:
            sslmode = quote_plus(self.pg_sslmode)
            base = f"{base}?sslmode={sslmode}"

        self.database_url = base
        return self

    cors_origins: str = "http://localhost:5173"

    azure_openai_endpoint: str | None = Field(default=None, validation_alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_key: str | None = Field(default=None, validation_alias="AZURE_OPENAI_API_KEY")
    azure_openai_deployment: str = Field(default="gpt-5.2-chat", validation_alias="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = Field(default="2024-10-01-preview", validation_alias="AZURE_OPENAI_API_VERSION")

    telemetry_enabled: bool = True
    telemetry_salt: str = "marco-telemetry-salt"

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
