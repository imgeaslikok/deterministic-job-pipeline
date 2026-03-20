"""
Application configuration.
"""

from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.enums import Environment, JobDispatchMode


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    # Core Infrastructure

    database_url: str = Field(
        default="postgresql+psycopg://app:app@localhost:5432/app",
        description="PostgreSQL connection string",
    )

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection string (Celery broker/result backend)",
    )

    # Runtime

    environment: Environment = Field(
        default=Environment.DEV,
        description="Application environment",
    )

    job_dispatcher: JobDispatchMode = Field(
        default=JobDispatchMode.CELERY,
        description="Job dispatch mode (celery or noop)",
    )

    # Executors

    job_executors: List[str] = Field(
        default_factory=lambda: ["src.apps.reports.executors"],
        description="Executor modules imported at worker startup",
    )

    # Job Execution

    job_max_retries: int = Field(default=3, ge=0)
    job_default_retry_delay: int = Field(default=2, ge=0)
    job_retry_backoff_base: int = Field(default=2, ge=1)
    job_retry_backoff_cap_seconds: int = Field(default=60, ge=1)
    job_max_execution_seconds: int = Field(default=300, ge=1)

    # Outbox & Sweeper

    outbox_publish_interval_seconds: float = Field(default=2.0, gt=0)
    stuck_job_sweep_interval_seconds: float = Field(default=60.0, gt=0)

    # Database Pool

    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout: int = Field(default=30, ge=1)


settings = Settings()

