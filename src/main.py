"""
FastAPI application factory and startup lifecycle.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool

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
        """Readiness probe."""
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        from fastapi.responses import Response
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
