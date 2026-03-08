"""
Application metrics.

Provides Prometheus counters and histograms for the job pipeline
and outbox publisher. Requires prometheus_client to be installed.

Usage:
    from src.core.metrics import JOB_ATTEMPTS_TOTAL
    JOB_ATTEMPTS_TOTAL.labels(job_type="report", status="completed").inc()
"""

from __future__ import annotations

try:
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

except ImportError:  # pragma: no cover
    # prometheus_client not installed — metrics become no-ops so the rest
    # of the application continues to work without instrumentation.
    class _Noop:
        def labels(self, **_):
            return self

        def inc(self, *_):
            pass

        def observe(self, *_):
            pass

    JOB_ATTEMPTS_TOTAL = _Noop()  # type: ignore[assignment]
    JOB_DURATION_SECONDS = _Noop()  # type: ignore[assignment]
    OUTBOX_EVENTS_TOTAL = _Noop()  # type: ignore[assignment]
