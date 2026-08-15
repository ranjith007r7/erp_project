"""
Central place for every setting the app needs.
Nothing else in the codebase should read an environment variable directly —
always come through here, so there's exactly ONE place to check when
something is misconfigured.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    # --- Database ---
    # Local dev default points at the Postgres container from docker-compose.
    DATABASE_URL: str = "postgresql://erp_user:erp_password@localhost:5432/erp_db"

    # --- Auth / JWT ---
    # NO default here, deliberately. A previous version of this file shipped
    # a placeholder default ("change-this-to-a-long-random-string...") baked
    # directly into source code — anyone who has ever seen this codebase (a
    # public GitHub repo, a shared zip, this very file) already knows that
    # exact string. If a deployment ever forgot to set the real env var, it
    # would boot successfully and silently sign every JWT with a secret the
    # whole internet effectively already has. Failing loudly at startup is
    # the correct behavior here, not a inconvenience to work around.
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # --- CORS ---
    # Comma-separated list of frontend URLs allowed to call this API.
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # --- Rate limiting ---
    MAX_FAILED_LOGIN_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15

    # --- Password reset / email verification token lifetime ---
    RESET_TOKEN_EXPIRE_MINUTES: int = 60
    VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def jwt_secret_must_be_real(cls, v: str) -> str:
        if not v or v.strip() == "" or "change-this" in v.lower():
            raise ValueError(
                "JWT_SECRET_KEY must be set to a real random value (never the placeholder "
                "text) — set it in your .env file or hosting provider's environment variables."
            )
        return v

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]


settings = Settings()
