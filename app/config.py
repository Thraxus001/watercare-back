from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # pydantic-settings reads from .env if present, then falls back to defaults.
    # On a deployment host (Railway / Render) set these as environment variables.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── Database ───────────────────────────────────────────────────────────────
    mongodb_url: str = ""
    database_url: str = ""          # legacy alias – also accepted
    mongodb_db_name: str = "watercare"

    # ── JWT security ──────────────────────────────────────────────────────────
    secret_key: str = "Com03/008/23@42462419"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000", "https://allianzplantcare.netlify.app"]

    # ── First-run admin seed ───────────────────────────────────────────────────
    first_admin_email: str = "admin@watercare.local"
    first_admin_password: str = "ChangeMe123!"
    first_admin_name: str = "System Admin"

    @property
    def effective_mongo_url(self) -> str:
        """Return the best available MongoDB connection string."""
        for candidate in (self.mongodb_url, self.database_url):
            c = (candidate or "").strip()
            if c.startswith("mongodb://") or c.startswith("mongodb+srv://"):
                return c
        return "mongodb://localhost:27017/watercare"


settings = Settings()
