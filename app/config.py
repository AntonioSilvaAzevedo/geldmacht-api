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


settings = Settings()
