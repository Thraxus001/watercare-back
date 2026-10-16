from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_url: str = ""
    database_url: str = ""
    mongodb_db_name: str = "watercare"

    secret_key: str = "change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    first_admin_email: str = "admin@yourcompany.com"
    first_admin_password: str = "ChangeMe123!"
    first_admin_name: str = "System Admin"

    @property
    def effective_mongo_url(self) -> str:
        url = getattr(self, "mongodb_url", None)
        if url and str(url).strip():
            return str(url).strip()
        db_url = getattr(self, "database_url", None)
        if db_url and (str(db_url).startswith("mongodb://") or str(db_url).startswith("mongodb+srv://")):
            return str(db_url).strip()
        return "mongodb://localhost:27017/watercare"


settings = Settings()
