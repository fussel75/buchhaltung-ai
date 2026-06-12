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
    max_upload_size_bytes: int = 25 * 1024 * 1024
    email_import_host: str | None = None
    email_import_port: int = 993
    email_import_username: str | None = None
    email_import_password: str | None = None
    email_import_mailbox: str = "INBOX"
    email_import_use_ssl: bool = True
    email_import_mark_seen: bool = True
    email_import_limit: int = 20
    email_import_max_message_bytes: int = 30 * 1024 * 1024
    email_import_search: str = "ALL"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

