"""
Application metrics.

Provides Prometheus counters and histograms for the job pipeline
and outbox publisher. Requires prometheus_client to be installed.

Usage:
    from src.core.metrics import JOB_ATTEMPTS_TOTAL
    JOB_ATTEMPTS_TOTAL.labels(job_type="report", status="completed").inc()
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

JOB_ATTEMPTS_TOTAL = Counter(
    "job_attempts_total",
    "Total job attempts by job_type and terminal status",
    ["job_type", "status"],
)

JOB_DURATION_SECONDS = Histogram(
    "job_duration_seconds",
    "Job execution duration in seconds by job_type",
    ["job_type"],
)

OUTBOX_EVENTS_TOTAL = Counter(
    "outbox_events_total",
    "Total outbox events processed by outcome",
    ["outcome"],
)
