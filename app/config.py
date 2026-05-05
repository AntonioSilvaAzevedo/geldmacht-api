from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Geldmacht API"
    database_url: str = "sqlite:///./geldmacht.db"
    debug: bool = True

    # CORS — lista separada por vírgula
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Pasta de dados reais (raiz do projeto)
    data_dir: Path = Path(__file__).parent.parent.parent.parent / "data"

    # Auth — JWT
    secret_key: str = "dev-secret-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""


settings = Settings()
