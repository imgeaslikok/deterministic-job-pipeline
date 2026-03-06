import time

from sqlalchemy.engine import Engine


def wait_for_db(
    engine: Engine, *, max_attempts: int = 30, sleep_seconds: float = 1.0
) -> None:
    """
    Wait until the database is reachable.
    Useful for Docker Compose where Postgres may start after the API container.

    Raises:
        RuntimeError: if DB is not reachable within max_attempts.
    """
    last_exc: Exception | None = None

    for _ in range(max_attempts):
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return
        except Exception as exc:
            last_exc = exc
            time.sleep(sleep_seconds)

    raise RuntimeError("Database not ready") from last_exc
