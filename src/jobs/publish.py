from __future__ import annotations

from src.db.session import SessionLocal
from src.outbox import service as outbox_service

from .dispatch import dispatch_job


def publish_job_dispatch_events(*, limit: int = 100) -> int:
    with SessionLocal() as db:
        return outbox_service.publish_pending_events(
            db,
            dispatch_job=dispatch_job,
            limit=limit,
        )
