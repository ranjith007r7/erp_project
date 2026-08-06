"""
Central place for every setting the app needs.
Nothing else in the codebase should read an environment variable directly —
always come through here, so there's exactly ONE place to check when
something is misconfigured.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database ---
    # Local dev default points at the Postgres container from docker-compose.
    DATABASE_URL: str = "postgresql://erp_user:erp_password@localhost:5432/erp_db"

    # --- Auth / JWT ---
    JWT_SECRET_KEY: str = "change-this-to-a-long-random-string-before-deploying"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # --- CORS ---
    # Comma-separated list of frontend URLs allowed to call this API.
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]


settings = Settings()
