from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://buchhaltung:change-me@db:5432/buchhaltung_ai"
    storage_root: Path = Path("/data/storage")
    initial_admin_email: str | None = None
    initial_admin_password: str | None = None
    session_cookie_name: str = "buchhaltung_session"
    session_cookie_secure: bool = True
    session_days: int = 30

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

