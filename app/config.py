from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/watercare"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    first_admin_email: str = "admin@yourcompany.com"
    first_admin_password: str = "ChangeMe123!"
    first_admin_name: str = "System Admin"


settings = Settings()
