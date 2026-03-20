# Architecture Documentation: deterministic-job-pipeline

---

## 1. Architectural Style

The system follows a **layered architecture with explicit domain boundaries**, organized into four layers:

```text
┌──────────────────────────────────────────────┐
│                 API Layer                    │  HTTP, schemas, middleware, exception mapping
├──────────────────────────────────────────────┤
│             Application Layer                │  Use cases, domain orchestration, UoW boundaries
├──────────────────────────────────────────────┤
│      Job Pipeline / Outbox / Persistence     │  Reliable execution, dispatch, repositories
├──────────────────────────────────────────────┤
│            Database / Broker Layer           │  PostgreSQL, Redis / Celery
└──────────────────────────────────────────────┘
```

The codebase is not strict hexagonal architecture. Instead, it applies **selective abstraction** where the coupling risk is highest: the `JobSubmitter` protocol in `src/jobs/ports.py` allows the reports domain to depend on a callable interface rather than a concrete job service implementation.

The project also uses DDD vocabulary pragmatically rather than formally. There are no rich aggregate roots, but there are clear domain modules, domain exceptions, domain enums, and application services with explicit transaction boundaries.

---

## 2. Major Layers and Responsibilities

### 2.1 API Layer (`src/api/`)

**Responsibility**: Translate HTTP requests into application service calls and map domain exceptions back to HTTP responses.

The API layer is intentionally thin:

- routers deserialize input and serialize output
- request middleware assigns or propagates `X-Request-Id`
- exception handlers are registered at startup
- routers delegate business work to service modules

Exception registration is auto-discovered through `src/api/common/exception_registry.py`, which scans API packages for modules exposing a `register(app)` function. This keeps exception mapping close to the API module it belongs to.

**Dependency direction**: `API -> application services`

---

### 2.2 Application Layer (`src/apps/`, `src/jobs/service.py`)

**Responsibility**: Orchestrate use cases inside explicit transaction boundaries.

The reports domain is the clearest example. `src/apps/reports/service.py:create_report()` performs:

1. lookup by idempotency key
2. report creation with race-safe recovery
3. job submission
4. job attachment to the report

All of these happen inside the same `UnitOfWork`, so they either commit together or roll back together.

The jobs application service in `src/jobs/service.py` owns job submission and operational workflows such as:

- submit a new job
- retry a dead job from DLQ
- inspect a job
- list attempt history

---

### 2.3 Job Pipeline Layer (`src/jobs/`)

**Responsibility**: Reliable job lifecycle management.

This is the core infrastructure of the project.

| Module | Responsibility |
|--------|----------------|
| `service.py` | Application-facing job operations |
| `pipeline.py` | State transition helpers such as `begin_attempt`, `finalize_attempt`, `reset_stuck_running_jobs` |
| `runner.py` | Runtime orchestration for execution, classification, finalization, and retry scheduling |
| `tasks.py` | Celery task entrypoints |
| `registry.py` | Maps job types to executor callables |
| `dispatch.py` | Dispatch abstraction (`CeleryJobDispatcher`, `NoopJobDispatcher`) |
| `publish.py` | Adapter between the outbox publisher and the dispatcher |
| `repository.py` | Job and attempt persistence helpers |

The pipeline is deliberately **domain-agnostic**. It does not import from `src/apps/`. Domains integrate by registering executor functions.

---

### 2.4 Transactional Outbox (`src/outbox/`)

**Responsibility**: Make dispatch intent durable before broker enqueue.

The outbox writes an `OutboxEvent` in the same database transaction as the job row. A periodic publisher later reads pending events and dispatches them to Celery.

The outbox module is generic at the data model level: it stores `event_type`, `payload`, retry metadata, and publication state. In this project, the only event type currently used is `JOB_DISPATCH_REQUESTED`.

---

### 2.5 Database Infrastructure (`src/db/`)

**Responsibility**: Shared database primitives.

This layer provides:

- SQLAlchemy base and mixins
- session management
- `UnitOfWork`
- shared repository helpers
- utility functions for startup readiness

It stays intentionally small. Domain-specific repository logic lives in the corresponding domain packages.

---

## 3. Dependency Direction

```text
src/api/v1/*
    └──> src/apps/reports/service
    └──> src/jobs/service
              │
              └──> src/jobs/ports.JobSubmitter (used by reports)
              │
              └──> src/outbox/service
              │
              └──> src/jobs/repository / src/jobs/pipeline / src/jobs/runner
                              │
                              └──> src/db/unit_of_work
                                      │
                                      └──> src/db/session
                                              │
                                              └──> PostgreSQL
```

Key rules maintained by the codebase:

- API code depends on services, not the reverse.
- `src/apps/reports` depends on job submission through the `JobSubmitter` protocol.
- `src/jobs` depends on `src/outbox`, but `src/outbox` does not depend on `src/jobs`.
- `src/db` has no upward dependency on application modules.

### Runtime import note

There is a runtime dependency between `dispatch.py` and `tasks.py` because Celery dispatch needs the `process_job` task reference. This is handled safely with a **deferred import inside `CeleryJobDispatcher.dispatch()`**, avoiding a fragile module-level circular import.

---

## 4. Data Flow and Control Flow

### 4.1 Job Submission Flow

```text
HTTP POST /api/v1/reports
  │
  ├─ RequestIdMiddleware assigns or propagates X-Request-Id
  │
  ├─ reports router opens UnitOfWork via get_uow()
  │
  ├─ reports_service.create_report(uow, idempotency_key, request_id, submit_job)
  │     │
  │     ├─ check existing report by idempotency key
  │     ├─ create report row with begin_nested() + IntegrityError fallback
  │     ├─ submit_job(...)
  │     │     ├─ create job row with begin_nested() + IntegrityError fallback
  │     │     └─ create outbox event JOB_DISPATCH_REQUESTED
  │     └─ attach job_id to report under SELECT FOR UPDATE
  │
  └─ UnitOfWork exits -> COMMIT
       report row + job row + outbox event are persisted atomically
```

---

### 4.2 Outbox Dispatch Flow

```text
Celery Beat task: publish_job_dispatch_events()
  │
  └─ outbox.service.publish_pending_events(SessionLocal, dispatch_job)
       │
       ├─ Phase 1: collect pending event ids
       │     SELECT ... FOR UPDATE SKIP LOCKED
       │     WHERE status = pending
       │       AND (next_attempt_at IS NULL OR next_attempt_at <= now)
       │     ORDER BY created_at, id
       │     LIMIT batch_size
       │   -> COMMIT
       │
       └─ Phase 2: process each event independently
             ├─ SELECT event FOR UPDATE
             ├─ verify still pending
             ├─ dispatch_job(job_id, request_id)
             ├─ mark outbox event as published
             └─ COMMIT per event
```

Important characteristics of this design:

- `SKIP LOCKED` avoids contention between publishers
- each event is committed independently
- a failure on one event does not roll back already-published events
- if dispatch succeeds but the publish transaction fails, the event may be retried later, so dispatch is **at-least-once**

---

### 4.3 Job Execution Flow

```text
Celery worker receives process_job(job_id)
  │
  ├─ tasks.process_job() delegates to runner.run_process_job()
  │
  ├─ runner resolves Celery context
  │     ├─ current_retries
  │     ├─ max_retries
  │     └─ request_id from task headers
  │
  ├─ open database session
  │
  └─ with UnitOfWork(db) as uow:
        │
        ├─ pipeline.begin_attempt(...)
        │     ├─ SELECT job FOR UPDATE
        │     ├─ if job terminal -> noop
        │     ├─ set job status = RUNNING
        │     ├─ increment attempts
        │     └─ insert JobAttempt row
        │
        ├─ resolve executor from registry
        │
        ├─ execute domain handler
        │     └─ domain writes happen inside the same UnitOfWork
        │
        ├─ classify outcome
        │     ├─ success -> COMPLETED
        │     ├─ RetryableJobError -> PENDING + retry
        │     ├─ NonRetryableJobError -> DEAD
        │     ├─ ExecutorNotRegistered -> DEAD
        │     └─ unknown exception -> re-raise
        │
        └─ _safe_finalize_attempt()
              └─ finalize attempt + update job state inside begin_nested()
```

If the outcome requires retry, `runner` schedules `self.retry(...)` with exponential backoff and full jitter.

---

## 5. Async Processing Model

The async stack is:

- **API process**: writes domain state, job row, and outbox row to PostgreSQL
- **Celery Beat**: publishes pending outbox events to Redis
- **Celery worker**: consumes `process_job` tasks
- **PostgreSQL**: source of truth for job state and coordination
- **Redis**: broker and result backend for Celery

This project does **not** use `asyncio` for worker execution. The worker pipeline is fully synchronous, which matches the current workload well because:

- coordination is database-centric
- SQLAlchemy usage is sync
- concurrency comes from Celery worker processes, not coroutines

FastAPI uses `run_in_threadpool()` only for startup/readiness checks.

---

## 6. Transaction Boundaries

### 6.1 API Request Transaction

```python
with UnitOfWork(db) as uow:
    report = create_report(...)
```

This transaction covers the full write use case:

- report row
- job row
- outbox event
- report-job attachment

This is the core atomicity guarantee of the submission path.

---

### 6.2 Worker Execution Transaction

```python
with UnitOfWork(db) as uow:
    begin = pipeline.begin_attempt(...)
    executor(JobContext(...), payload)
    _safe_finalize_attempt(...)
```

Domain updates performed by the executor commit in the **same outer transaction** as job state updates. This means domain outcome and job outcome stay consistent.

`_safe_finalize_attempt()` wraps `pipeline.finalize_attempt()` in `db.begin_nested()`, so finalization uses a savepoint.

If finalization fails:

- an exception is logged with event `job_finalize_failed`
- the outer transaction continues
- the job may remain in `RUNNING`
- the sweeper can recover it later

---

### 6.3 Outbox Event Transaction

Each outbox event is processed in its own session and committed independently.

This keeps the publisher durable: one failing event does not poison the entire batch.

---

## 7. Error Handling Model

### 7.1 Domain Exceptions -> API Responses

Service-layer exceptions such as:

- `ReportNotFound`
- `InvalidReportState`
- `JobNotFound`
- `InvalidJobState`
- `IdempotencyKeyConflict`

are mapped to HTTP responses by exception handlers in `src/api/v1/*/exceptions.py`.

---

### 7.2 Executor Errors -> Pipeline Decisions

Executors communicate failure intent through typed exceptions.

| Exception | Meaning | Pipeline action |
|-----------|---------|-----------------|
| `RetryableJobError` | transient failure | move job back to `PENDING`, schedule retry |
| `NonRetryableJobError` | permanent failure | move to `DEAD` |
| `ExecutorNotRegistered` | configuration/runtime mismatch | move to `DEAD` |
| any other `Exception` | unexpected bug | re-raise to Celery |

For retryable failures, retry scheduling uses exponential backoff with full jitter.

For unexpected exceptions, the task is re-raised. Combined with:

- `task_acks_late=True`
- `task_acks_on_failure_or_timeout=False`

Celery can requeue the task instead of silently consuming it.

---

### 7.3 Outbox Publish Errors

Outbox publish failures are handled in `src/outbox/service.py`.

Behavior:

- unsupported event types are marked `FAILED`
- transient failures are rescheduled with persisted `retry_count` and `next_attempt_at`
- after retry exhaustion, the event is marked `FAILED`

There is **no automatic recovery path** for `FAILED` outbox events in the current implementation.

---

## 8. Consistency Strategy

The system uses **strong consistency inside a transaction boundary** and **eventual consistency across asynchronous boundaries**.

### 8.1 Strongly Consistent

| Data relationship | Why |
|-------------------|-----|
| report row + job row + outbox event | written in one API transaction |
| job snapshot + attempt row finalization | written in one worker transaction |
| domain update + final job outcome | executor runs inside the active UnitOfWork |

---

### 8.2 Eventually Consistent

| Boundary | Mechanism |
|----------|-----------|
| outbox event -> broker dispatch | periodic publisher |
| retry scheduling -> later execution | Celery retry |
| stuck running job -> recovery | periodic sweeper |
| job completion -> client awareness | polling via API |

---

### 8.3 Idempotency and Duplicate Suppression

The project uses multiple layers of deduplication:

#### Submission idempotency

- partial unique index on `jobs.idempotency_key`
- fast-path read by key
- `begin_nested()` insert
- `IntegrityError` fallback read
- semantic validation: same key must match same `job_type` and `payload`

#### Report creation idempotency

- partial unique index on `reports.idempotency_key`
- same optimistic insert + fallback pattern

#### Attempt deduplication

- `UNIQUE(job_id, attempt_no)` on `job_attempts`
- if duplicate attempt insert fails, execution is skipped safely

#### Publisher concurrency control

- `FOR UPDATE SKIP LOCKED` for pending outbox batches
- per-event `FOR UPDATE` before publish
- status re-check before changing state

---

## 9. Extensibility Points

### 9.1 Adding a New Job Type

A domain adds an executor:

```python
@register("my_domain.some_job")
def some_job(ctx: JobContext, payload: dict) -> ExecutionResult:
    ...
```

Then the executor module is included in `JOB_EXECUTORS`.

No pipeline changes are required.

---

### 9.2 Adding a New Outbox Event Type

To support another outbox event type:

1. define a new event type constant
2. add publish handling in `src/outbox/service.py`
3. update terminal/non-terminal error behavior if needed

---

### 9.3 Swapping the Dispatcher

`src/jobs/dispatch.py` defines a small dispatch interface.

The current implementations are:

- `CeleryJobDispatcher`
- `NoopJobDispatcher`

This makes broker dispatch replaceable without changing the pipeline or domain services.

---

## 10. Observability and Operational Model

### 10.1 Structured Logging

The pipeline and publisher emit structured logs using `build_log_extra()`.

Common fields include:

- `component`
- `event`
- `job_id`
- `attempt_no`
- `request_id`
- `detail`

The `request_id` propagation chain is:

```text
HTTP header
  -> RequestIdMiddleware
  -> submit_job(... request_id=...)
  -> outbox payload
  -> Celery task headers
  -> runner._resolve_celery_context()
  -> worker logs
```

This provides end-to-end correlation without distributed tracing.

---

### 10.2 Prometheus Metrics

The application exposes metrics at `GET /metrics`.

Defined metrics:

| Metric | Type | Labels |
|--------|------|--------|
| `job_attempts_total` | Counter | `job_type`, `status` |
| `job_duration_seconds` | Histogram | `job_type` |
| `outbox_events_total` | Counter | `outcome` |

Emission points:

- `runner._run_executor()` updates job attempt and duration metrics
- `outbox.service` updates outbox outcome metrics

---

### 10.3 Health and Readiness

The application exposes:

- `GET /healthz` -> liveness probe
- `GET /readyz` -> checks both database and Redis broker connectivity

Readiness returns `503` with an `errors` map if any dependency is unavailable.

---

### 10.4 Current Gaps

The current observability model does **not** include:

- OpenTelemetry or distributed tracing
- explicit DLQ depth metrics
- explicit outbox backlog metrics
- alerting hooks for DLQ growth or stuck jobs

These are operational gaps, not correctness gaps.

---

## 11. Trade-offs and Design Choices

### 11.1 PostgreSQL as the Coordination Layer

The system uses PostgreSQL row locks for coordination instead of Redis locks.

Benefits:

- transactional correctness
- automatic lock release on commit/rollback
- no TTL/heartbeat complexity

Trade-off:

- lock contention is resolved at the database level
- throughput is bounded by database coordination patterns

For this project, this is the right trade-off.

---

### 11.2 Transactional Outbox Instead of Direct Enqueue

The outbox removes the classic failure window:

- DB commit succeeds
- process crashes before queue enqueue
- job is lost

The cost is extra moving parts and up to one publisher interval of dispatch latency.

This trade-off is the main correctness choice of the architecture.

---

### 11.3 Executor Runs Inside the Active UnitOfWork

Running the executor inside the active transaction gives strong consistency between domain state and job state.

Trade-off:

- long-running executors can hold DB transactions open longer
- executor code must be careful with expensive or slow side effects

This is a deliberate consistency-over-isolation choice.

---

### 11.4 Optimistic Idempotency Pattern

The code prefers:

- non-locking fast-path reads
- insert under `begin_nested()`
- `IntegrityError` recovery

instead of pessimistic lock-first logic.

This keeps the common path lightweight while still remaining race-safe.

---

### 11.5 At-Least-Once Dispatch and Execution

The architecture intentionally accepts at-least-once behavior at async boundaries.

Safety comes from:

- durable submission
- duplicate suppression at attempt creation
- idempotent submission semantics
- explicit job state transitions

This is the right model for the current stack.

---

## 12. Database Schema Overview

```text
jobs
  id                UUID PK
  job_type          VARCHAR(...) INDEX
  idempotency_key   VARCHAR(...) UNIQUE PARTIAL INDEX (WHERE NOT NULL)
  status            ENUM(pending, running, completed, dead) INDEX
  payload           JSON
  result            JSON nullable
  attempts          INTEGER
  last_error        TEXT nullable
  created_at
  updated_at

job_attempts
  id                UUID PK
  job_id            FK -> jobs.id (ON DELETE CASCADE)
  attempt_no        INTEGER
  status            ENUM(running, succeeded, failed) INDEX
  error             TEXT nullable
  started_at        TIMESTAMPTZ nullable
  finished_at       TIMESTAMPTZ nullable
  created_at
  UNIQUE(job_id, attempt_no)

outbox_events
  id                UUID PK
  event_type        VARCHAR(...) INDEX
  status            ENUM(pending, published, failed) INDEX
  payload           JSON
  error             TEXT nullable
  retry_count       INTEGER
  next_attempt_at   TIMESTAMPTZ nullable
  published_at      TIMESTAMPTZ nullable
  created_at
  updated_at

reports
  id                UUID PK
  idempotency_key   VARCHAR(...) UNIQUE PARTIAL INDEX (WHERE NOT NULL)
  status            ENUM(pending, ready) INDEX
  job_id            VARCHAR(...) nullable INDEX
  result            JSON nullable
  created_at
  updated_at
```

Notable choices:

- partial unique indexes allow optional idempotency keys
- `job_attempts` uses `ON DELETE CASCADE`
- `reports.job_id` is indexed but not a foreign key
- enums are stored as string values via `enum_value_type()`
- `jobs.updated_at` is used by the sweeper to detect stuck running jobs

---
