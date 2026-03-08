"""
Application configuration.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.enums import JobDispatchMode


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    redis_url: str = "redis://localhost:6379/0"
    environment: str = "dev"
    job_dispatcher: str = JobDispatchMode.CELERY.value
    job_executors: list[str] = [
        "src.apps.reports.executors",
    ]
    job_max_retries: int = 3
    job_default_retry_delay: int = 2
    job_retry_backoff_base: int = 2
    job_retry_backoff_cap_seconds: int = 60


settings = Settings()
