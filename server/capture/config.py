from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration from CAPTURE_* environment variables (or server/.env)."""

    model_config = SettingsConfigDict(env_prefix="CAPTURE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://capture@localhost:5432/capture"
    storage_dir: Path = Path("storage")
    session_hours: int = 12
    cookie_secure: bool = True
    extraction_enabled: bool = False
    max_pages: int = 20
    max_page_bytes: int = 15 * 1024 * 1024
