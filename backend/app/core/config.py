from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_parse_none_str="")

    app_env: str = "development"
    app_secret: str = "development-only-change-me"
    admin_password: str = "change-me"
    database_url: str = "sqlite:///./data/app.db"
    data_dir: Path = Path("./data")
    model_cache_dir: Path = Path("./data/models")
    schedule_hour: int = Field(default=8, ge=0, le=23)
    schedule_timezone: str = "Asia/Shanghai"
    llm_provider: str = Field(default="auto", pattern="^(auto|api|codex|disabled)$")
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_input_price_rmb_per_million: float | None = Field(default=None, ge=0)
    llm_output_price_rmb_per_million: float | None = Field(default=None, ge=0)
    llm_monthly_budget_rmb: float = Field(default=50, ge=0)
    codex_command: str = "codex"
    codex_model: str | None = None
    codex_timeout_seconds: int = Field(default=300, ge=30, le=600)
    feishu_webhook: str | None = None
    public_base_url: str = "http://localhost:8000"
    max_upload_bytes: int = 10 * 1024 * 1024
    max_backup_bytes: int = 500 * 1024 * 1024
    session_hours: int = 24
    login_attempts: int = 5
    login_window_seconds: int = 300

    @property
    def secure_cookie(self) -> bool:
        return self.app_env == "production"

    def ensure_directories(self) -> None:
        for child in ("uploads", "generated", "backups"):
            (self.data_dir / child).mkdir(parents=True, exist_ok=True)
        self.model_cache_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
