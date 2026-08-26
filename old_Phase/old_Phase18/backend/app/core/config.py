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
    # Longer than verification's 24h - accepting an invite to join a
    # company is less time-sensitive than "verify the email you just
    # used two minutes ago", and an invitee might reasonably not check
    # their inbox again for a few days.
    INVITE_TOKEN_EXPIRE_HOURS: int = 168  # 7 days

    # --- Real email delivery (added after Phase 13 shipped with no
    # provider connected) ---
    # Empty string, not required - unlike JWT_SECRET_KEY, the app must
    # still boot and run fully without this configured (every test, CI
    # run, and local dev session doesn't have one). app/services/email.py
    # checks this and falls back to console logging when it's empty.
    RESEND_API_KEY: str = ""
    # The real deployed frontend URL, used to build the links inside
    # verification/reset emails. Defaults to localhost for local dev;
    # MUST be set to the real Vercel URL in Render's environment for
    # production, or every emailed link will point at localhost.
    FRONTEND_URL: str = "http://localhost:3000"

    # --- Scheduled jobs (GitHub Actions cron, not a paid Render worker -
    # Render's own Cron Jobs feature has no free tier) ---
    # A shared secret, not a user JWT - these two endpoints run with no
    # human logged in, triggered by GitHub's servers on a timer. Empty by
    # default and the dependency in deps.py REJECTS every request when
    # this is empty, rather than silently allowing unauthenticated access -
    # same fail-closed posture as JWT_SECRET_KEY, just without forcing the
    # whole app to refuse to boot, since these two endpoints are optional.
    CRON_SECRET: str = ""

    # --- Real file storage (Cloudflare R2 - checked current pricing
    # before choosing it: R2's free tier is genuinely permanent - 10GB
    # storage, 1M writes/10M reads per month, zero egress fees, forever -
    # unlike S3's free tier, which expires after 12 months) ---
    # All empty by default, same posture as RESEND_API_KEY - the app
    # must still boot and run fully without these configured; the
    # upload/download endpoints return a clear error instead of
    # crashing when storage isn't set up yet.
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""
    MAX_UPLOAD_SIZE_MB: int = 10

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
