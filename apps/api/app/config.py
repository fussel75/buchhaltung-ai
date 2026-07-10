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
    partner_sync_tokens: str | None = None
    partner_app_api_base_url: str | None = None
    buha_api_key: str | None = None
    hapak_api_base_url: str | None = None
    hapak_api_key: str | None = None
    synology_hapak_base_url: str | None = None
    synology_hapak_username: str | None = None
    synology_hapak_password: str | None = None
    ai_extraction_enabled: bool = False
    ai_extraction_api_key: str | None = None
    ai_extraction_base_url: str = "https://openrouter.ai/api/v1"
    ai_extraction_model: str = "openai/gpt-4o-mini"
    ai_extraction_timeout_seconds: int = 45
    ai_extraction_min_confidence: float = 0.90
    ai_extraction_max_text_chars: int = 12000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()

