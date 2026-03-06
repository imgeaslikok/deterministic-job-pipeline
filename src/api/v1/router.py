"""
API v1 router aggregation.

Collects and exposes all v1 feature routers.
"""

from fastapi import APIRouter

from src.api.v1.jobs.router import router as jobs_router
from src.api.v1.reports.router import router as reports_router

router = APIRouter()

# Feature routers
router.include_router(jobs_router)
router.include_router(reports_router)
