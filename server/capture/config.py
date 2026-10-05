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
    vlm_url: str = "http://127.0.0.1:8001/v1"  # vLLM's OpenAI-compatible API (self-hosted; spec §3)
    vlm_model: str = "Qwen/Qwen3-VL-8B-Instruct"  # an AWQ 4-bit variant on GPUs under 24 GB
    vlm_timeout_s: float = 120
    vlm_max_image_side: int = 1600  # pages are shrunk to this long side before they go to the model
    confidence_threshold: float = 0.85  # spec §5.2: below this a field is amber
    worker_poll_s: float = 2.0  # how long an idle worker waits before looking for jobs again
