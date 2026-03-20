# deterministic-job-pipeline

A background job processing pipeline built with **FastAPI**, **Celery**, **PostgreSQL**, and the **Transactional Outbox pattern**. It focuses on reliable job submission, controlled execution, retry handling, dead-lettering, and recovery of jobs left in `RUNNING` after worker failures.

The pipeline is domain-agnostic. Domains integrate by registering executor functions. A **report generation domain** is included as a reference implementation.

---

## What This Project Does

This project addresses a common reliability problem in distributed backends: how to ensure that a background job is still dispatched after a successful database commit, even if the process crashes before the broker enqueue happens.

The approach used here is the **Transactional Outbox Pattern**:

- the job row and the dispatch event are written in the same database transaction
- a periodic publisher reads pending outbox events and dispatches them to Celery
- dispatch is decoupled from the API request lifecycle

Once a job has been dispatched, execution is coordinated with row-level locking and explicit attempt tracking. Retryable failures are rescheduled with exponential backoff and full jitter. Permanent failures, or jobs that exhaust retry limits, move to a dead letter queue (DLQ). A background sweeper resets jobs that remain in `RUNNING` longer than the configured execution window.

---

## System Behavior

### What is guaranteed

- **No lost jobs after a successful submission commit**  
  A committed job row always has a matching durable outbox event.

- **At-least-once dispatch and execution**  
  Outbox publication and worker execution both follow at-least-once semantics.

- **Duplicate execution suppression at the attempt layer**  
  Concurrent duplicate deliveries are safely deduplicated with row locks and a `UNIQUE(job_id, attempt_no)` constraint.

- **Atomic domain update and final job state update**  
  Domain writes performed by the executor commit in the same transaction as final job state.

- **Crash recovery for stuck jobs**  
  Jobs left in `RUNNING` because of worker failure can be reset and re-dispatched by the sweeper.

### What is not guaranteed

- **Exactly-once delivery**  
  The system is designed for at-least-once behavior with database-backed deduplication and idempotent submission.

- **Multi-leader scheduler coordination**  
  Running multiple Celery Beat instances is not a supported configuration.

- **Automatic recovery of failed outbox events**  
  Outbox events that exhaust publish retries are marked `FAILED` and require operator intervention.

---

## Architecture Overview

```text
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

For a more detailed breakdown of layers, transaction boundaries, and runtime flow, see `architecture.md`.

---

## Project Structure

```text
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

Client requests that create background work (for example `POST /api/v1/reports`) call the domain service, which submits a job through `submit_job()`.

The submission transaction writes:

- a row in `jobs`
- a row in `outbox_events`

Both rows commit atomically.

---

### 2. Outbox Dispatch

A Celery Beat task runs every 2 seconds and publishes pending outbox events.

The publisher:

1. claims pending events using `SELECT ... FOR UPDATE SKIP LOCKED`
2. dispatches jobs to Celery (`process_job`)
3. marks the event as `published`

Each event is committed independently so one failed publish does not roll back already-published events.

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

Executors classify failures by raising typed exceptions:

- `RetryableJobError` -> retry with exponential backoff and full jitter
- `NonRetryableJobError` -> immediate DLQ
- `ExecutorNotRegistered` -> immediate DLQ

Jobs that exceed `JOB_MAX_RETRIES` are moved to the dead letter queue.

Operators can retry DLQ jobs manually through the API.

---

### 5. Stuck Job Recovery

A periodic sweeper task runs every 60 seconds.

Jobs that remain in `RUNNING` longer than `JOB_MAX_EXECUTION_SECONDS` are reset to `PENDING` and re-dispatched through the outbox.

---

## Failure Handling Summary

| Failure point | Outcome | Recovery path |
|---|---|---|
| API fails before commit | nothing is persisted | no recovery needed |
| API fails after commit but before enqueue | job is not lost | outbox publisher dispatches later |
| outbox publish fails transiently | event stays pending with retry metadata | publisher retries later |
| outbox publish exhausts retries | event becomes `FAILED` | operator intervention |
| worker receives duplicate delivery | duplicate attempt is deduplicated | no-op execution path |
| executor raises retryable error | job returns to `PENDING` | Celery retry |
| executor raises permanent error | job moves to `DEAD` | optional manual retry |
| worker crashes during execution | job may remain `RUNNING` | sweeper resets and re-dispatches |

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
| `POST` | `/api/v1/reports` | Create a report and submit a generation job |
| `GET` | `/api/v1/reports/{id}` | Fetch a report by ID |

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Liveness probe |
| `GET` | `/readyz` | Readiness probe (verifies DB and broker connectivity) |
| `GET` | `/metrics` | Prometheus metrics endpoint |

---

## Setup and Installation

### Prerequisites

- Docker
- Docker Compose

### Start the System

```bash
make up
```

This starts:

- `postgres` — PostgreSQL 16
- `redis` — Redis 7 (Celery broker and result backend)
- `api` — FastAPI app
- `worker` — Celery worker
- `beat` — Celery Beat scheduler (outbox publisher + sweeper)

The API container runs Alembic migrations on startup.

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

Configuration is loaded from environment variables or a `.env` file. The defaults are suitable for local development.

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+psycopg://app:app@localhost:5432/app` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `ENVIRONMENT` | `dev` | Runtime environment. Set to `test` for eager execution behavior |
| `JOB_DISPATCHER` | `celery` | Dispatcher implementation. Set to `noop` in tests |
| `JOB_EXECUTORS` | `["src.apps.reports.executors"]` | Executor modules imported at worker startup |

### Job Execution Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `JOB_MAX_RETRIES` | `3` | Maximum retry attempts before DLQ |
| `JOB_DEFAULT_RETRY_DELAY` | `2` | Base retry delay in seconds |
| `JOB_RETRY_BACKOFF_BASE` | `2` | Exponential backoff base |
| `JOB_RETRY_BACKOFF_CAP_SECONDS` | `60` | Maximum retry delay cap in seconds |
| `JOB_MAX_EXECUTION_SECONDS` | `300` | Time after which a `RUNNING` job is considered stuck |

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

Tests require a running PostgreSQL instance. The Docker Compose stack provides one.

```bash
make test
```

This runs:

```bash
ENVIRONMENT=test JOB_DISPATCHER=noop alembic upgrade head
ENVIRONMENT=test JOB_DISPATCHER=noop pytest -q
```

With `ENVIRONMENT=test`:

- Celery runs in eager mode
- `JOB_DISPATCHER=noop` replaces broker dispatch with a no-op
- tests control execution explicitly through the test helpers

The suite is integration-oriented and runs against a live database. Each test uses an isolated `UnitOfWork`, and the executor registry is reset between tests.

### Covered Scenarios

The tests cover the main reliability paths, including:

- idempotent report creation
- duplicate job submission recovery
- outbox publication
- duplicate execution suppression
- retry and DLQ transitions
- stuck-job recovery
- report completion through the executor path

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

**Important**: run exactly one Celery Beat instance. Multiple Beat instances are not a supported configuration. The outbox locking and status checks reduce the chance of duplicate publication, but Beat itself is treated as a single scheduler.

### Worker Configuration

| Setting | Value | Purpose |
|---------|-------|---------|
| `task_acks_late` | `True` | Acknowledge tasks after execution so worker crashes do not lose tasks |
| `task_acks_on_failure_or_timeout` | `False` | Unhandled failures are not silently acknowledged |
| `worker_prefetch_multiplier` | `1` | Prevents task hoarding per worker process |

### Beat Tasks

| Task | Schedule | Purpose |
|------|----------|---------|
| `publish_job_dispatch_events` | Every 2 seconds | Reads pending outbox events and dispatches to Celery |
| `reset_stuck_running_jobs` | Every 60 seconds | Recovers jobs stuck in `RUNNING` beyond `JOB_MAX_EXECUTION_SECONDS` |

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
    # ctx.uow — active UnitOfWork shared with job infrastructure
    # ctx.job_id, ctx.attempt_no, ctx.request_id
    # Raise NonRetryableJobError for permanent failures
    # Raise RetryableJobError for transient failures
    return ExecutionResult(result={"done": True})
```

### 2. Register the executor module

Add it to `JOB_EXECUTORS`:

```python
job_executors: list[str] = [
    "src.apps.reports.executors",
    "src.apps.myapp.executors",
]
```

### 3. Submit jobs from an application service

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

Pipeline and outbox events are logged with structured fields using `build_log_extra()`. Log entries include `component`, `event`, `job_id`, `attempt_no`, and `request_id` when available.

The `request_id` is propagated from the HTTP `X-Request-Id` header into the outbox payload and Celery task headers so API requests can be correlated with async execution.

| Event | Level | When |
|-------|-------|------|
| `job_attempt_begin` | INFO | Task starts executing |
| `job_attempt_noop` | INFO | Job already terminal or duplicate invocation |
| `job_attempt_succeeded` | INFO | Executor completed successfully |
| `job_retry_needed` | WARNING | Retryable error, retry pending |
| `job_retry_scheduled` | WARNING | Retry countdown dispatched |
| `job_moved_to_dlq` | ERROR | Job moved to dead state |
| `job_finalize_failed` | ERROR | Attempt finalization failed; sweeper may recover later |
| `outbox_event_claimed` | INFO | Outbox event picked up for publishing |
| `outbox_event_published` | INFO | Dispatch successful |
| `outbox_event_retry_scheduled` | WARNING | Publish failed, retry scheduled |
| `outbox_event_failed` | ERROR | Publish exhausted retries or unsupported type |

### Prometheus Metrics

Exposed at `GET /metrics` in Prometheus text format.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `job_attempts_total` | Counter | `job_type`, `status` | Total job execution attempts by outcome |
| `job_duration_seconds` | Histogram | `job_type` | Executor execution latency |
| `outbox_events_total` | Counter | `outcome` | Outbox event outcomes |

---

## Key Design Decisions

### Transactional Outbox Instead of Direct Enqueue

Job rows and dispatch events are written atomically to PostgreSQL. This removes the failure window where a database commit succeeds but the process crashes before broker enqueue.

The trade-off is extra moving parts and publisher latency.

### Row-Level Locking for Concurrency Safety

`begin_attempt()` uses `SELECT ... FOR UPDATE` on the job row. A `UNIQUE(job_id, attempt_no)` constraint acts as a hard backstop against concurrent duplicate execution.

Duplicate invocations become safe no-ops.

### Registry-Based Executor Resolution

Job types are resolved at runtime through a registry. The pipeline does not need to know domain modules ahead of time beyond importing executor modules configured in `JOB_EXECUTORS`.

### Shared UnitOfWork for Domain and Job Finalization

Executors receive the active `UnitOfWork`. Domain changes and final job state commit together.

This keeps state consistent but means executor code should avoid unnecessarily long or slow transactions.

### Typed Error Classification

Executors communicate intent through exception type rather than return codes:

- `RetryableJobError` — retry until the limit is reached, then DLQ
- `NonRetryableJobError` — immediate DLQ
- `ExecutorNotRegistered` — immediate DLQ

### Idempotency via Partial Unique Indexes

`UNIQUE(idempotency_key) WHERE NOT NULL` allows optional idempotency keys while enforcing uniqueness when a key is provided.

Submission uses optimistic insert plus `IntegrityError` fallback so duplicate requests can be resolved safely under concurrency.

---

## Limitations

- **Single Celery Beat instance**: multiple Beat instances are not supported without external coordination.
- **No automatic recovery of failed outbox events**: exhausted publish failures remain in `FAILED` until handled manually.
- **No per-attempt result payload storage**: only the final job result is persisted.
- **No webhook or push notifications**: job completion is currently poll-based.

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
