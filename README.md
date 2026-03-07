# deterministic-job-pipeline

A production-oriented background job processing pipeline built with **FastAPI**, **Celery**, **PostgreSQL**, and the **Transactional Outbox pattern**. The pipeline provides reliable, deterministic job dispatch and execution with full attempt auditing, retry orchestration, and a dead letter queue.

The pipeline is domain-agnostic. Domains integrate by registering executors. A **report generation domain** is included as a working example.

---

## What This Project Does

This system solves a common reliability problem in distributed backends: how do you guarantee that a background job is *always* dispatched after a database commit, even if the process crashes between the two?

The answer implemented here is the **Transactional Outbox Pattern**: the job row and a dispatch event are written in the same database transaction. A periodic publisher then reads pending events and dispatches them to Celery. This decouples dispatch reliability from the API request lifecycle.

Once dispatched, jobs are executed under row-level locks with full attempt tracking. Retries use exponential backoff. Jobs that exhaust retries or fail permanently are moved to a dead letter queue (DLQ) and can be retried manually via the API.

---

## Architecture Overview

```
Client
  │
  ▼
FastAPI (HTTP API)
  │   reads Idempotency-Key / X-Request-Id headers
  ▼
Application Service (e.g. reports/service.py)
  │   orchestrates domain + job submission atomically
  ▼
jobs/service.submit_job()
  │   creates Job row + OutboxEvent in one DB transaction
  ▼
outbox/service.publish_pending_events()   ← Celery Beat (every 2s)
  │   claims events via FOR UPDATE SKIP LOCKED
  │   dispatches to Celery
  ▼
jobs/tasks.process_job(job_id)            ← Celery Worker
  │   acquires row lock on Job
  │   creates JobAttempt row
  │   invokes registered Executor
  │   finalizes attempt + updates Job status
  ▼
Domain Executor (e.g. reports/executors.py)
  │   performs domain work inside the active UoW transaction
  ▼
Domain state update committed
```

---

## Project Structure

```
src/
├── api/
│   ├── common/
│   │   ├── exception_registry.py   # Auto-discovers and registers domain exception handlers
│   │   ├── middleware.py           # RequestIdMiddleware (X-Request-Id propagation)
│   │   └── responses.py           # Shared error_response() helper
│   └── v1/
│       ├── jobs/                  # Job inspection and retry endpoints
│       │   ├── router.py
│       │   ├── schemas.py
│       │   └── exceptions.py      # Domain → HTTP exception mapping
│       ├── reports/               # Report creation and retrieval endpoints
│       │   ├── router.py
│       │   ├── schemas.py
│       │   └── exceptions.py
│       ├── exceptions.py          # Wires exception handlers at startup
│       └── router.py              # Mounts all v1 sub-routers
│
├── apps/
│   └── reports/                   # Example domain: report generation
│       ├── executors.py           # @register("report.generate") executor
│       ├── service.py             # Report creation, completion, idempotency
│       ├── repository.py          # DB access helpers for reports
│       ├── models.py              # Report ORM model
│       ├── enums.py               # ReportStatus
│       ├── exceptions.py          # Domain exceptions
│       ├── job_types.py           # Job type string constant
│       └── messages.py            # Error message constants
│
├── jobs/                          # Core job pipeline (domain-agnostic)
│   ├── tasks.py                   # Celery task entrypoints: process_job, publish_job_dispatch_events
│   ├── pipeline.py                # begin_attempt / finalize_attempt (state transitions under locks)
│   ├── service.py                 # submit_job, retry_from_dlq, list_dlq, list_attempts
│   ├── repository.py              # DB access helpers for jobs and attempts
│   ├── registry.py                # Executor registry (@register decorator, get_executor)
│   ├── dispatch.py                # CeleryJobDispatcher / NoopJobDispatcher (switchable)
│   ├── publish.py                 # Outbox → dispatcher bridge
│   ├── ports.py                   # JobSubmitter Protocol (dependency inversion)
│   ├── types.py                   # ExecutionResult, JobContext, AttemptResult, Executor
│   ├── models.py                  # Job, JobAttempt ORM models
│   ├── enums.py                   # JobStatus, AttemptStatus, JobEvent
│   ├── exceptions.py              # JobError hierarchy + execution signal exceptions
│   ├── messages.py                # Error message templates
│   └── utils.py                   # load_executors, retry_countdown, task_log, is_eager
│
├── outbox/                        # Transactional outbox implementation
│   ├── service.py                 # publish_pending_events, create_event, retry logic
│   ├── repository.py              # DB access including claim_pending_batch_ids (SKIP LOCKED)
│   ├── models.py                  # OutboxEvent ORM model
│   ├── config.py                  # MAX_PUBLISH_RETRIES, backoff constants, batch limit
│   ├── enums.py                   # OutboxStatus
│   ├── events.py                  # Event type string constants
│   ├── exceptions.py              # UnsupportedOutboxEventType
│   ├── messages.py                # Error message helpers
│   └── utils.py                   # publisher_log, backoff_delay_seconds, is_terminal_publish_error
│
├── db/                            # Database infrastructure
│   ├── session.py                 # Engine, SessionLocal, get_db, get_uow
│   ├── unit_of_work.py            # UnitOfWork context manager
│   ├── base.py                    # SQLAlchemy declarative base
│   ├── repository.py              # save(), save_and_refresh()
│   ├── mixins.py                  # IdMixin (UUID PK), TimestampMixin
│   ├── types.py                   # enum_value_type() helper
│   ├── constants.py               # Column length constants
│   └── utils.py                   # wait_for_db startup probe
│
├── core/
│   ├── context.py                 # Request ID contextvars (X-Request-Id propagation)
│   ├── enums.py                   # LogLevel
│   ├── logging.py                 # build_log_extra() structured log helper
│   └── utils.py                   # now_utc()
│
├── config/
│   ├── settings.py                # Pydantic Settings (env vars)
│   └── celery.py                  # Celery app, beat schedule, test eager mode
│
├── tests/
│   ├── conftest.py                # Shared fixtures: db_session, uow, registry reset
│   ├── factories.py               # create_job, run_job, create_report_with_job
│   ├── utils.py                   # generate_idempotency_key
│   ├── api/                       # HTTP-level API tests
│   ├── jobs/                      # Pipeline integration tests (test_pipeline.py)
│   ├── outbox/                    # Outbox behavior tests
│   └── reports/                   # Reports domain tests (executors, service)
│
└── main.py                        # FastAPI app factory + lifespan
```

---

## Job Execution Flow

### 1. Submission (API → Database)

```
POST /api/v1/reports
  └─► reports_service.create_report()
        └─► jobs_service.submit_job()
              ├─► INSERT INTO jobs (status=pending, ...)
              └─► INSERT INTO outbox_events (event_type=job.dispatch.requested, ...)
              └─► COMMIT (both rows atomic)
```

### 2. Dispatch (Outbox Publisher → Celery)

```
Celery Beat triggers publish_job_dispatch_events every 2 seconds
  └─► outbox_service.publish_pending_events()
        ├─► SELECT ... FOR UPDATE SKIP LOCKED  (claim batch)
        ├─► COMMIT claim
        └─► For each event:
              ├─► SELECT ... FOR UPDATE         (re-claim per event)
              ├─► dispatch_job(job_id)          (apply_async to Celery)
              └─► UPDATE outbox_events SET status=published
              └─► COMMIT per event
```

### 3. Execution (Celery Worker → Database)

```
process_job(job_id)
  └─► pipeline.begin_attempt()
        ├─► SELECT jobs WHERE id=? FOR UPDATE
        ├─► Skip if job is terminal or duplicate attempt
        ├─► UPDATE jobs SET status=running, attempts=N
        └─► INSERT INTO job_attempts (status=running, ...)
  └─► executor = get_executor(job.job_type)
  └─► executor(ctx, job.payload)           ← domain work inside UoW
  └─► pipeline.finalize_attempt()
        ├─► UPDATE job_attempts SET status=succeeded|failed, ...
        └─► UPDATE jobs SET status=completed|dead|pending, ...
  └─► COMMIT
```

### 4. Retry / DLQ

```
RetryableJobError raised by executor
  └─► _classify_execution_error() → need_retry=True
  └─► retry_countdown(n) = min(2^n, 60) seconds
  └─► self.retry(countdown=N)             ← re-queued in Celery
  └─► Next attempt: begin_attempt() creates attempt_no N+1

After max_retries exhausted (default 3):
  └─► job.status = dead
  └─► Visible at GET /api/v1/jobs/dlq

Manual retry:
  └─► POST /api/v1/jobs/{id}/retry
        └─► job.status = pending
        └─► New outbox event created
        └─► Job re-dispatched on next outbox publish cycle
```

---

## API Endpoints

### Jobs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jobs/{id}` | Fetch a job by ID |
| `GET` | `/api/v1/jobs/{id}/attempts` | Fetch attempt history for a job |
| `GET` | `/api/v1/jobs/dlq` | List dead jobs (DLQ) |
| `POST` | `/api/v1/jobs/{id}/retry` | Reset and re-enqueue a dead job |

### Reports

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/reports` | Create a report (submits generation job) |
| `GET` | `/api/v1/reports/{id}` | Fetch a report by ID |

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Liveness probe |
| `GET` | `/readyz` | Readiness probe |

---

## Setup and Installation

### Prerequisites

- Docker and Docker Compose

### Start the System

```bash
make up
```

This starts:
- `postgres` — PostgreSQL 16
- `redis` — Redis 7
- `api` — FastAPI app (with auto-migration on startup)
- `worker` — Celery worker
- `beat` — Celery Beat scheduler (outbox publisher)

### Run Database Migrations Only

```bash
make migrate
```

### Reset (Wipe Volumes and Restart)

```bash
make reset
```

---

## Configuration

All configuration is loaded from environment variables (or a `.env` file). Defaults are suitable for local development.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://app:app@localhost:5432/app` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string (Celery broker/backend) |
| `ENVIRONMENT` | `dev` | Runtime environment. Set to `test` to enable Celery eager mode |
| `JOB_DISPATCHER` | `celery` | Dispatcher implementation. Set to `noop` to skip actual Celery dispatch (used in tests) |
| `JOB_EXECUTORS` | `["src.apps.reports.executors"]` | List of executor modules to import at worker startup |

---

## Running Tests

Tests require a running PostgreSQL instance (the Docker Compose stack provides one).

```bash
make test
```

This runs:
```bash
ENVIRONMENT=test JOB_DISPATCHER=noop alembic upgrade head
ENVIRONMENT=test JOB_DISPATCHER=noop pytest -q
```

With `ENVIRONMENT=test`:
- Celery runs in eager (synchronous) mode — no broker needed.
- `JOB_DISPATCHER=noop` — `apply_async` is replaced with a no-op so tests control dispatch explicitly via `run_job()`.

Tests are integration tests that run against a live database. Each test class/function uses an isolated `UnitOfWork` and the registry is reset between tests via the `_reset_registry` autouse fixture.

---

## Background Workers

### Celery Worker

Processes job tasks dispatched by the outbox publisher.

```bash
celery -A src.config.celery.celery worker -l INFO
```

### Celery Beat

Runs the outbox publisher on a 2-second schedule.

```bash
celery -A src.config.celery.celery beat -l INFO
```

Worker configuration:

| Setting | Value | Purpose |
|---------|-------|---------|
| `task_acks_late` | `True` | Acknowledge tasks after execution (prevents loss on worker crash) |
| `worker_prefetch_multiplier` | `1` | Prevents task hoarding per worker process |
| `max_retries` | `3` | Maximum retries before DLQ |
| `default_retry_delay` | `2s` | Base retry delay |
| Retry backoff | `min(2^n, 60)s` | Exponential backoff, capped at 60 seconds |

---

## Adding a New Job Type

1. Create an executor function in your domain module:

```python
# src/apps/myapp/executors.py
from src.jobs.registry import register
from src.jobs.types import ExecutionResult, JobContext
from src.jobs.exceptions import NonRetryableJobError, RetryableJobError

@register("myapp.do_something")
def do_something(ctx: JobContext, payload: dict) -> ExecutionResult:
    # ctx.uow — active UnitOfWork (transaction)
    # ctx.job_id, ctx.attempt_no, ctx.request_id
    # Raise NonRetryableJobError for permanent failures
    # Raise RetryableJobError for transient failures
    return ExecutionResult(result={"done": True})
```

2. Add your executor module to `JOB_EXECUTORS` in settings:

```python
job_executors: list[str] = [
    "src.apps.reports.executors",
    "src.apps.myapp.executors",
]
```

3. Submit jobs from your application service:

```python
from src.jobs.service import submit_job

job = submit_job(
    uow,
    job_type="myapp.do_something",
    payload={"key": "value"},
    idempotency_key="optional-idempotency-key",
    request_id=request_id,
)
```

---

## Key Design Decisions

### Transactional Outbox (not direct enqueue)

Job rows and dispatch events are written atomically. This guarantees that a dispatched job always has a corresponding database record, and that a committed job is always eventually dispatched — even across process crashes.

### Row-Level Locking for Concurrency Safety

`begin_attempt` uses `SELECT ... FOR UPDATE` on the job row and relies on a `UNIQUE(job_id, attempt_no)` constraint on `job_attempts` to safely handle concurrent duplicate task invocations. Duplicate attempts return `should_run=False` without an error.

### Executor Registry (not hardcoded dispatch)

The job type to executor mapping is resolved at runtime via a registry, allowing domains to register handlers without the pipeline needing to know about them. Executor modules are imported at worker startup via `JOB_EXECUTORS`.

### UnitOfWork in Executor Context

Executors receive an active `UnitOfWork` in their context. Domain updates (e.g. marking a report as ready) happen within the same transaction as the job state finalization — providing atomic domain + job state updates.

### Separate `RUNNING` → `DEAD` vs Retry Paths

Error classification is explicit: `RetryableJobError` signals a transient failure (retry until max, then DLQ), `NonRetryableJobError` signals an immediate DLQ transition, and unclassified exceptions propagate (causing Celery to re-queue the task based on the worker configuration).

---

## Limitations and Known Gaps

- **No stuck-RUNNING recovery**: If a worker is killed after `begin_attempt` but before `finalize_attempt`, the job remains in `RUNNING` state permanently. A periodic watchdog task to reset stuck jobs is not yet implemented.
- **No metrics**: There are no Prometheus or StatsD hooks for monitoring job throughput, failure rates, or DLQ size.
- **Single outbox publisher**: The Celery Beat scheduler runs on a single instance. Multiple Beat instances are not safe without external coordination.
- **No per-attempt result storage**: Only the final job result is persisted; intermediate attempt results are not stored.
- **No DLQ pagination cursor**: `GET /api/v1/jobs/dlq` supports a `limit` parameter but not cursor-based pagination.

---

## Development Utilities

```bash
make lint         # Run ruff linter (with auto-fix)
make format       # Run ruff formatter
make shell        # Open shell in api container
make worker-shell # Open shell in worker container
make logs         # Tail all container logs
make ps           # Show container status
```

---

## License

MIT License
