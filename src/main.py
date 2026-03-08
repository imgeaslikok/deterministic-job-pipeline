"""
FastAPI application factory and startup lifecycle.
"""

from contextlib import asynccontextmanager
from http import HTTPStatus

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from src.api.common.middleware import RequestIdMiddleware
from src.api.v1.exceptions import register_exception_handlers
from src.api.v1.router import router as v1_router
from src.config.settings import settings
from src.db.session import engine
from src.db.utils import wait_for_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Wait for the database to become reachable on startup."""
    await run_in_threadpool(wait_for_db, engine)
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Task Queue API",
        version="0.1.0",
        debug=settings.environment == "dev",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    app.include_router(v1_router, prefix="/api/v1")

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        """Liveness probe."""
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        """Readiness probe — verifies DB and broker connectivity."""
        errors: dict[str, str] = {}

        def _check_db():
            with engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")

        def _check_redis():
            import redis as redis_lib

            client = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
            try:
                client.ping()
            finally:
                client.close()

        for name, check in (("db", _check_db), ("broker", _check_redis)):
            try:
                await run_in_threadpool(check)
            except Exception as exc:
                errors[name] = str(exc)

        if errors:
            return JSONResponse(
                {"status": "unavailable", "errors": errors},
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            )

        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
