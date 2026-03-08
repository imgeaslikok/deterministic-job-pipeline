# deterministic-job-pipeline

A production-oriented background job processing pipeline built with **FastAPI**, **Celery**, **PostgreSQL**, and the **Transactional Outbox pattern**. The pipeline provides reliable, deterministic job dispatch and execution with full attempt auditing, retry orchestration, a dead letter queue, and stuck-job recovery.

The pipeline is domain-agnostic. Domains integrate by registering executor functions. A **report generation domain** is included as a working reference implementation.

---

## What This Project Does

This system solves a core reliability problem in distributed backends: how do you guarantee that a background job is *always* dispatched after a database commit — even if the process crashes between the two?

The answer implemented here is the **Transactional Outbox Pattern**: the job row and a dispatch event are written in the same database transaction. A periodic publisher reads pending events and dispatches them to Celery. This decouples dispatch reliability from the API request lifecycle.

Once dispatched, jobs are executed under row-level locks with full attempt tracking. Retries use exponential backoff with full jitter. Jobs that exhaust retries or fail permanently are moved to a dead letter queue (DLQ) and can be retried manually via the API. A background sweeper task recovers jobs stuck in RUNNING state due to worker crashes.

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
  │   dispatches to Celery broker
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
Domain state update committed atomically with job status
```

---

## Project Structure

```
src/
├── api/        # FastAPI routers and HTTP layer
├── apps/       # Domain applications (example: reports)
├── jobs/       # Background job pipeline
├── outbox/     # Transactional outbox publisher
├── db/         # Database infrastructure
├── core/       # Shared utilities (logging, metrics, context)
├── config/     # Application configuration
└── tests/      # Integration tests
```

---

## Job Execution Flow

### 1. Job Submission

Client requests that create background work (e.g. `POST /reports`)
call the domain service which submits a job through `submit_job()`.

The submission transaction writes:

- a row in `jobs`
- a dispatch event in `outbox_events`

Both rows are committed atomically.

---

### 2. Outbox Dispatch

A Celery Beat task runs every 2 seconds and publishes pending
outbox events.

The publisher:

1. claims events using `SELECT ... FOR UPDATE SKIP LOCKED`
2. dispatches jobs to Celery (`process_job`)
3. marks the event as `published`

Each event is committed independently to guarantee durability.

---

### 3. Job Execution

Celery workers execute the `process_job` task.

Execution proceeds as:

1. acquire a row lock on the job
2. create a `job_attempt` record
3. invoke the registered executor
4. finalize the attempt and update job state

All state transitions happen inside a database transaction.

---

### 4. Retries and Dead Letter Queue

Executors signal failure type by raising exceptions:

- `RetryableJobError` → retry with exponential backoff
- `NonRetryableJobError` → immediate DLQ

Jobs exceeding `JOB_MAX_RETRIES` are moved to the dead letter queue.

Operators can retry DLQ jobs manually via the API.

---

### 5. Stuck Job Recovery

A periodic sweeper task runs every 60 seconds.

Jobs stuck in `RUNNING` longer than `JOB_MAX_EXECUTION_SECONDS`
are reset to `PENDING` and re-dispatched through the outbox.

---

## API Endpoints

### Jobs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/jobs/{id}` | Fetch a job by ID |
| `GET` | `/api/v1/jobs/{id}/attempts` | Fetch attempt history for a job |
| `GET` | `/api/v1/jobs/dlq` | List dead jobs (DLQ). Supports `?limit` and `?cursor=<last_job_id>` for pagination |
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
| `GET` | `/readyz` | Readiness probe (verifies DB connectivity) |
| `GET` | `/metrics` | Prometheus metrics endpoint |

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
- `redis` — Redis 7 (Celery broker and result backend)
- `api` — FastAPI app (runs Alembic migrations on startup)
- `worker` — Celery worker
- `beat` — Celery Beat scheduler (outbox publisher + sweeper)

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

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://app:app@localhost:5432/app` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string (Celery broker/backend) |
| `ENVIRONMENT` | `dev` | Runtime environment. Set to `test` to enable Celery eager mode |
| `JOB_DISPATCHER` | `celery` | Dispatcher implementation. Set to `noop` to skip Celery dispatch (used in tests) |
| `JOB_EXECUTORS` | `["src.apps.reports.executors"]` | Executor modules to import at worker startup |

### Job Execution Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `JOB_MAX_RETRIES` | `3` | Maximum retry attempts before DLQ |
| `JOB_DEFAULT_RETRY_DELAY` | `2` | Base retry delay in seconds |
| `JOB_RETRY_BACKOFF_BASE` | `2` | Exponential backoff base |
| `JOB_RETRY_BACKOFF_CAP_SECONDS` | `60` | Maximum retry delay cap in seconds |
| `JOB_MAX_EXECUTION_SECONDS` | `300` | Time after which a RUNNING job is considered stuck |

### Outbox and Sweeper Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `OUTBOX_PUBLISH_INTERVAL_SECONDS` | `2.0` | How often the outbox publisher runs |
| `STUCK_JOB_SWEEP_INTERVAL_SECONDS` | `60.0` | How often the stuck-job sweeper runs |

### Database Connection Pool

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_POOL_SIZE` | `5` | Number of persistent connections in the pool |
| `DB_MAX_OVERFLOW` | `10` | Maximum extra connections above `DB_POOL_SIZE` |
| `DB_POOL_TIMEOUT` | `30` | Seconds to wait for a connection before raising |

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

Tests are integration tests that run against a live database. Each test uses an isolated `UnitOfWork` and the executor registry is reset between tests via the `_reset_registry` autouse fixture.

---

## Background Workers

### Celery Worker

Processes job tasks dispatched by the outbox publisher.

```bash
celery -A src.config.celery.celery worker -l INFO
```

### Celery Beat

Runs the outbox publisher and stuck-job sweeper on their configured schedules.

```bash
celery -A src.config.celery.celery beat -l INFO
```

**Important**: Run exactly one Celery Beat instance. Multiple Beat instances will cause duplicate scheduling attempts. The outbox per-event lock and status re-check prevent actual double dispatch, but running multiple Beat instances is not a supported configuration.

### Worker Configuration

| Setting | Value | Purpose |
|---------|-------|---------|
| `task_acks_late` | `True` | Acknowledge tasks after execution (prevents loss on worker crash) |
| `task_acks_on_failure_or_timeout` | `False` | Nack on unhandled failure — broker requeues the task instead of silently consuming it |
| `worker_prefetch_multiplier` | `1` | Prevents task hoarding per worker process |

### Beat Tasks

| Task | Schedule | Purpose |
|------|----------|---------|
| `publish_job_dispatch_events` | Every 2 seconds | Reads pending outbox events and dispatches to Celery |
| `reset_stuck_running_jobs` | Every 60 seconds | Recovers jobs stuck in RUNNING beyond `JOB_MAX_EXECUTION_SECONDS` |

---

## Adding a New Job Type

### 1. Create an executor function

```python
# src/apps/myapp/executors.py
from src.jobs.registry import register
from src.jobs.types import ExecutionResult, JobContext
from src.jobs.exceptions import NonRetryableJobError, RetryableJobError

@register("myapp.do_something")
def do_something(ctx: JobContext, payload: dict) -> ExecutionResult:
    # ctx.uow — active UnitOfWork (transaction shared with job infrastructure)
    # ctx.job_id, ctx.attempt_no, ctx.request_id
    # Raise NonRetryableJobError for permanent failures (bad payload, missing data)
    # Raise RetryableJobError for transient failures (network, temporary DB issues)
    return ExecutionResult(result={"done": True})
```

### 2. Register the executor module

Add it to `JOB_EXECUTORS` in your settings or environment:

```python
job_executors: list[str] = [
    "src.apps.reports.executors",
    "src.apps.myapp.executors",
]
```

### 3. Submit jobs from your application service

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

## Observability

### Structured Logs

All pipeline events are logged with structured fields using `build_log_extra()`. Every log entry includes `component`, `event`, `job_id`, `attempt_no`, and `request_id` (when available). The `request_id` is propagated from the HTTP `X-Request-Id` header through the outbox payload and into the Celery task headers, allowing full correlation of a client request through its async execution chain.

| Event | Level | When |
|-------|-------|------|
| `job_attempt_begin` | INFO | Task starts executing |
| `job_attempt_noop` | INFO | Job already terminal or duplicate invocation |
| `job_attempt_succeeded` | INFO | Executor completed successfully |
| `job_retry_needed` | WARNING | Retryable error, retry pending |
| `job_retry_scheduled` | WARNING | Retry countdown dispatched |
| `job_moved_to_dlq` | ERROR | Job moved to dead state |
| `job_finalize_failed` | ERROR | Attempt finalization failed — job may be stuck in RUNNING until sweeper recovers it |
| `outbox_event_claimed` | INFO | Outbox event picked up for publishing |
| `outbox_event_published` | INFO | Dispatch successful |
| `outbox_event_retry_scheduled` | WARNING | Publish failed, retry scheduled |
| `outbox_event_failed` | ERROR | Publish exhausted retries or unsupported type |

### Prometheus Metrics

Exposed at `GET /metrics` (Prometheus text format):

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `job_attempts_total` | Counter | `job_type`, `status` | Total job execution attempts by outcome |
| `job_duration_seconds` | Histogram | `job_type` | Executor execution latency |
| `outbox_events_total` | Counter | `outcome` | Outbox event outcomes (published, failed, pending) |

---

## Key Design Decisions

### Transactional Outbox (not direct enqueue)

Job rows and dispatch events are written atomically to PostgreSQL. This guarantees that a committed job is always eventually dispatched — even across process crashes between the DB commit and the broker enqueue. The cost is a maximum 2-second dispatch latency and the operational requirement to run Celery Beat reliably.

### Row-Level Locking for Concurrency Safety

`begin_attempt` uses `SELECT ... FOR UPDATE` on the job row. A `UNIQUE(job_id, attempt_no)` database constraint provides a hard backstop against concurrent duplicate task executions. Duplicate invocations return `should_run=False` — they are silently and safely deduplicated.

### Executor Registry (not hardcoded dispatch)

The job type to executor mapping is resolved at runtime via a registry, allowing domains to register handlers without the pipeline needing to know about them. Executor modules are imported at worker startup via the `JOB_EXECUTORS` setting.

### UnitOfWork in Executor Context

Executors receive an active `UnitOfWork` in their context. Domain updates (e.g., marking a report as ready) happen within the same transaction as the job state finalization — providing atomic domain + infrastructure state consistency.

### Error Classification Via Typed Exceptions

Executors signal intent through exception type, not return codes:
- `RetryableJobError` — transient failure, retry until `max_retries`, then DLQ
- `NonRetryableJobError` — permanent failure, DLQ immediately
- `ExecutorNotRegistered` — unknown job type, DLQ immediately

### Idempotency via Partial Unique Index

`UNIQUE(idempotency_key) WHERE NOT NULL` allows multiple rows with `NULL` while enforcing uniqueness for non-null keys. The submission path uses an optimistic insert with `IntegrityError` fallback to handle concurrent duplicate submissions safely.

---

## Limitations

- **Single Celery Beat instance**: Multiple Beat instances are not supported without external coordination. Beat is a single point of scheduling.
- **No per-attempt result storage**: Only the final job result is persisted; intermediate attempt results are not stored.
- **No webhook or push notifications**: Job completion is poll-based. There is no webhook or event push when a job completes or fails.

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
