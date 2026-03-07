# Architecture Documentation: deterministic-job-pipeline

---

## 1. Architectural Style

The system follows a **layered architecture with explicit domain boundaries**, organized into four distinct layers:

```
┌─────────────────────────────────┐
│          API Layer              │  HTTP, schemas, exception mapping
├─────────────────────────────────┤
│       Application Layer         │  Domain services, use cases, UoW
├─────────────────────────────────┤
│   Domain / Infrastructure Mix   │  Job pipeline, Outbox, Repositories
├─────────────────────────────────┤
│       Database / Broker         │  PostgreSQL, Redis/Celery
└─────────────────────────────────┘
```

There are no strict hexagonal ports between all layers, but the system applies **selective port abstraction** where the coupling risk is highest: the `JobSubmitter` Protocol in `jobs/ports.py` allows the reports domain to depend on a callable interface rather than a concrete import of the jobs service, which is the correct place to draw the boundary.

The codebase is not DDD in the full sense — there are no aggregates with invariant enforcement at the object level — but it applies DDD vocabulary (domain exceptions, domain services, domain isolation) in a pragmatic way appropriate to its scale.

---

## 2. Major Layers and Their Responsibilities

### 2.1 API Layer (`src/api/`)

**Responsibility**: Translate HTTP requests into application service calls and map domain results/exceptions back to HTTP responses.

The API layer is intentionally thin. Routers (`router.py`) call domain services with deserialized parameters. They do not contain business logic. Exception handlers are auto-discovered via `exception_registry.py`, which scans API version packages for modules exposing a `register(app)` function. This allows each domain to own its own HTTP exception mapping without modifying central routing configuration.

Key design decision: exception handlers live in `api/v1/{domain}/exceptions.py`, not in the domain itself. This keeps HTTP concerns out of business logic while keeping the exception mapping close to the API module it belongs to.

**Dependency direction**: API → Application services. Never the reverse.

### 2.2 Application Layer (`src/apps/`, `src/jobs/service.py`)

**Responsibility**: Orchestrate domain operations within explicit transaction boundaries. Coordinate between domain objects and infrastructure services (job submission, outbox events).

The reports domain (`src/apps/reports/service.py`) is the canonical example. `create_report()` orchestrates:
1. An idempotency check (read).
2. A report row insertion (with race-condition recovery via `begin_nested`).
3. A job submission (which also creates an outbox event, atomically).
4. A job attachment to the report.

All four steps happen within the same `UnitOfWork` — meaning they commit together or roll back together. This is the correct scope for an application service: one use-case, one transaction boundary.

The jobs application service (`src/jobs/service.py`) manages the jobs domain: submit, retry from DLQ, inspect. It is also used by other domains via the `JobSubmitter` protocol.

### 2.3 Job Pipeline Infrastructure (`src/jobs/`)

**Responsibility**: Reliable job lifecycle management — dispatch, execution, attempt tracking, retry, DLQ.

This is the most complex layer and the core infrastructure of the project. It contains:

- **`service.py`**: Application-facing API for job management.
- **`pipeline.py`**: Low-level state machine operations (`begin_attempt`, `finalize_attempt`) that run under row-level locks.
- **`tasks.py`**: Celery task definitions — the worker entrypoints.
- **`registry.py`**: Executor registry — maps job types to callable handlers.
- **`dispatch.py`**: Abstraction over the job dispatch mechanism (Celery or Noop).
- **`publish.py`**: Bridge between the outbox service and the job dispatcher.

The pipeline is designed to be entirely domain-agnostic. It does not import from `src/apps/`. Domains integrate by registering executor functions. This inversion is the central extensibility mechanism.

### 2.4 Transactional Outbox (`src/outbox/`)

**Responsibility**: Guarantee that job dispatch events are eventually delivered to the Celery broker, even if the broker is temporarily unavailable at submission time.

The outbox is an independent infrastructure module. It knows nothing about jobs specifically — it operates on generic `OutboxEvent` rows with a `payload` field. The events it currently handles are job dispatch requests, but the event type dispatch table in `outbox/service.py` could be extended.

### 2.5 Database Infrastructure (`src/db/`)

**Responsibility**: Provide reusable database primitives: session management, the Unit-of-Work abstraction, shared mixins (UUIDs, timestamps), and repository helpers.

This layer is deliberately minimal. There is no generic base repository class — just shared helper functions (`save`, `save_and_refresh`) and mixins. Domain-specific repository modules live with their respective domains.

---

## 3. Dependency Direction

```
api/v1/ ────────────────────────► apps/reports/service
                                          │
                                          ▼
                             jobs/ports.JobSubmitter (Protocol)
                                          │
                                          ▼
                                   jobs/service ◄──── jobs/pipeline
                                          │                  │
                                          ▼                  ▼
                                  outbox/service        jobs/repository
                                          │
                                          ▼
                                   db/unit_of_work
                                          │
                                          ▼
                                     db/session
                                          │
                                          ▼
                                     PostgreSQL
```

The `apps/` modules depend on `jobs/` via the protocol. The `jobs/` module depends on `outbox/` for event creation. The `outbox/` module does not depend on `jobs/`. The `db/` layer has no upward dependencies. This direction is consistently maintained throughout the codebase.

**Circular dependency risk**: `jobs/tasks.py` imports from `jobs/pipeline.py`, `jobs/registry.py`, `jobs/service.py`, and `jobs/dispatch.py`. The `dispatch.py` imports from `jobs/tasks.py` (to get the `process_job` task reference). This creates a within-module circular structure that Python resolves through import ordering, but it is a fragility. The `publish.py` module imports `dispatch_job` lazily (inside a function body) to break this cycle for the outbox path.

---

## 4. Data Flow and Control Flow

### 4.1 Job Submission Flow

```
HTTP POST /api/v1/reports
  │
  ├─ RequestIdMiddleware assigns X-Request-Id
  │
  ├─ reports router extracts headers, creates UoW from get_uow()
  │
  ├─ reports_service.create_report(uow, idempotency_key, request_id, submit_job)
  │     │
  │     ├─ Check for existing report by idempotency_key (read, no lock)
  │     ├─ Create report row with begin_nested() + IntegrityError fallback
  │     ├─ submit_job(uow, job_type="report.generate", payload={report_id}, ...)
  │     │     │
  │     │     ├─ _create_job_row() with begin_nested() + fallback
  │     │     └─ outbox_service.create_event(JOB_DISPATCH_REQUESTED, {job_id, request_id})
  │     │
  │     └─ _attach_job_to_report(uow.session, report_id, job_id)
  │
  └─ uow.__exit__() → COMMIT
       (Job row + OutboxEvent written atomically)
```

### 4.2 Dispatch Flow

```
Celery Beat (every 2s)
  │
  └─ publish_job_dispatch_events()
       │
       └─ outbox_service.publish_pending_events(SessionLocal, dispatch_job)
             │
             ├─ Phase 1: Claim batch
             │     SELECT id FROM outbox_events
             │     WHERE status=pending AND (next_attempt_at IS NULL OR next_attempt_at <= now)
             │     ORDER BY created_at, id
             │     FOR UPDATE SKIP LOCKED
             │     LIMIT 100
             │   → COMMIT (releases lock, persists claim intent)
             │
             └─ Phase 2: Process each event ID (separate session per event)
                   │
                   ├─ SELECT ... FOR UPDATE (re-acquire, verify still pending)
                   ├─ CeleryJobDispatcher.dispatch() → process_job.apply_async(job_id)
                   ├─ UPDATE outbox_events SET status=published
                   └─ COMMIT
```

### 4.3 Execution Flow

```
Celery Worker receives process_job(job_id)
  │
  ├─ Extract current_retries, max_retries, request_id from self.request
  │
  ├─ Open SessionLocal
  │
  ├─ Log ATTEMPT_BEGIN
  │
  ├─ UnitOfWork context:
  │     │
  │     ├─ pipeline.begin_attempt(session, job_id, started_at)
  │     │     │
  │     │     ├─ SELECT jobs WHERE id=? FOR UPDATE  (row lock)
  │     │     ├─ if job is terminal → return AttemptResult(should_run=False, "terminal")
  │     │     ├─ UPDATE jobs SET status=running, attempts=N
  │     │     └─ INSERT INTO job_attempts (status=running) → IntegrityError → "duplicate"
  │     │
  │     ├─ if not should_run → skip to logging (noop)
  │     │
  │     ├─ get_executor(job.job_type) → raises ExecutorNotRegistered if missing
  │     │
  │     ├─ executor(JobContext(uow, job_id, attempt_no, request_id), payload)
  │     │     │
  │     │     └─ Domain work (e.g. complete_report()) — inside same UoW
  │     │
  │     ├─ On success: attempt_status=SUCCEEDED, job_status=COMPLETED
  │     │
  │     ├─ On RetryableJobError: _classify_execution_error() → need_retry=True or DLQ
  │     ├─ On NonRetryableJobError: → DLQ immediately
  │     ├─ On unknown Exception: traceback captured, re-raised
  │     │
  │     └─ finally: pipeline.finalize_attempt() inside begin_nested()
  │           ├─ UPDATE job_attempts SET status=..., finished_at=...
  │           └─ UPDATE jobs SET status=..., last_error=..., result=...
  │
  ├─ UoW.__exit__() → COMMIT (or ROLLBACK on re-raised exception)
  │
  ├─ Log outcome event
  │
  └─ if need_retry:
         └─ self.retry(exc=..., countdown=min(2^n, 60))
              (Celery re-queues the task; task is NOT acknowledged yet due to task_acks_late)
```

---

## 5. Async Processing Model

The system uses **Celery with Redis** as the task broker and result backend. The async model is:

- **Producer**: FastAPI API process writes to PostgreSQL; Celery Beat reads and dispatches.
- **Consumer**: Celery workers pull tasks from Redis queues.
- **Coordination**: PostgreSQL row-level locks (`SELECT FOR UPDATE`) are used for execution coordination, not Redis locks. This is a deliberate choice — database locks are transactional and survive broker restarts.

The outbox publisher (Beat task `publish_job_dispatch_events`) runs every 2 seconds and processes up to 100 events per cycle. This means maximum dispatch latency is approximately 2 seconds from job submission to Celery task queuing.

The pipeline does **not** use async Python (`asyncio`). The FastAPI app uses `run_in_threadpool` for the database readiness probe at startup. All other operations are synchronous with SQLAlchemy's sync ORM. This is appropriate for a CPU/IO-bound worker pipeline where connection pooling and synchronous database access are simpler and more predictable.

---

## 6. Transaction Boundaries

There are three distinct transaction scopes in the system:

### 6.1 API Request Transaction (write operations)

```python
with UnitOfWork(db) as uow:
    result = service_function(uow, ...)
# Commits on exit, rolls back on exception
```

Covers the full application service operation: report creation, job submission, outbox event insertion. All-or-nothing atomicity.

### 6.2 Worker Execution Transaction

```python
with UnitOfWork(db) as uow:
    begin = pipeline.begin_attempt(uow.session, ...)
    executor(ctx, payload)   # domain work
    # finalize_attempt in finally, inside begin_nested()
# Commits on exit
```

The executor runs inside the worker's Unit of Work. Domain state updates (e.g. `complete_report`) are committed in the same transaction as the job and attempt status finalization. This is the key design decision for atomicity: domain outcome and job infrastructure state are always consistent.

The `begin_nested()` in `finalize_attempt`'s `finally` block creates a savepoint, so a finalization failure can be rolled back independently without rolling back the outer transaction. However, the current implementation swallows finalization exceptions, which is a known gap.

### 6.3 Outbox Publishing Transaction (per-event)

Each outbox event is processed in its own session and committed independently. This prevents a failure in event N from rolling back the publication status of events 1..N-1.

---

## 7. Error Handling Model

### 7.1 Domain Exceptions → API Exceptions

Domain exceptions (`JobNotFound`, `InvalidJobState`, `IdempotencyKeyConflict`, `ReportNotFound`) are raised in service layers and caught by FastAPI exception handlers registered at startup. The handlers are auto-discovered from `api/v1/{domain}/exceptions.py` modules.

### 7.2 Executor Execution Errors → Pipeline Signals

The jobs domain uses a signal-exception pattern for executor error classification:

| Exception | Meaning | Pipeline Action |
|-----------|---------|-----------------|
| `RetryableJobError` | Transient failure, should retry | Retry with backoff until max_retries, then DLQ |
| `NonRetryableJobError` | Permanent failure, no point retrying | DLQ immediately |
| `ExecutorNotRegistered` | Job type unknown | DLQ immediately |
| Any other `Exception` | Unexpected failure | Re-raise (Celery re-queues via `task_acks_late`) |

This is an intentional design: executor authors express intent through exception type, not return codes. The pipeline interprets intent through `_classify_execution_error`.

### 7.3 Outbox Publishing Errors

Outbox publish failures are retried with exponential backoff (base 30s, cap 600s, max 5 retries). After exhausting retries, the event is marked `FAILED` and the job will never be dispatched. There is no automatic recovery from a `FAILED` outbox event — this would require manual intervention or a separate recovery mechanism.

---

## 8. Consistency Strategy

The system targets **eventual consistency** between the outbox and the Celery broker, and **strong consistency** within a single transaction boundary.

### What is strongly consistent:
- Job row + outbox event (written atomically).
- Job status + attempt status (finalized in the same worker transaction).
- Domain state + job outcome (executor runs inside the worker transaction).

### What is eventually consistent:
- Outbox event → Celery dispatch (up to 2s latency plus any publish retries).
- Job completion → external consumers of the result (poll-based; no webhooks or notifications implemented).

### Idempotency strategy:
- Job submission: `UNIQUE` partial index on `idempotency_key` + `begin_nested` + `IntegrityError` fallback read. Semantic validation (same key → same type and payload) prevents logical conflicts.
- Attempt creation: `UNIQUE(job_id, attempt_no)` on `job_attempts`. Concurrent duplicate invocations get `IntegrityError` → `should_run=False`.
- Outbox claiming: `FOR UPDATE SKIP LOCKED` prevents concurrent publishers from claiming the same event.

---

## 9. Extensibility Points

### 9.1 Adding New Job Types

Register a new executor in any domain module:

```python
@register("new_domain.do_work")
def do_work(ctx: JobContext, payload: dict) -> ExecutionResult:
    ...
```

Add the module to `JOB_EXECUTORS` in settings. No changes to the pipeline required.

### 9.2 Adding New Outbox Event Types

The outbox currently only handles `JOB_DISPATCH_REQUESTED`. The `_publish_single_event` function in `outbox/service.py` dispatches on `event.event_type`. New event types require:
1. Adding a new event type constant in `outbox/events.py`.
2. Adding a new dispatch handler in `outbox/service.py`.
3. Updating `is_terminal_publish_error` if the new event type has different terminal error semantics.

### 9.3 Adding New Domains

New domains follow the reports pattern:
1. Create `src/apps/{domain}/` with service, repository, models, executors.
2. Register the executor module in `JOB_EXECUTORS`.
3. Add API routes in `src/api/v1/{domain}/` with router, schemas, exceptions.
4. Include the router in `src/api/v1/router.py`.

The pipeline and outbox require no modification.

### 9.4 Swapping the Job Dispatcher

The `JobDispatcher` protocol in `dispatch.py` allows the Celery dispatcher to be replaced with any callable that implements `dispatch(job_id, request_id)`. This is already used in tests (`NoopJobDispatcher`) and could be used to swap to a different broker without changing the pipeline.

---

## 10. Observability and Operational Model

### 10.1 Structured Logging

Logging is structured throughout using `build_log_extra()`, which produces a dictionary of non-null fields suitable for log aggregation systems. Every log entry from the pipeline includes:

- `component` — e.g. `"jobs.worker"` or `"outbox.publisher"`.
- `event` — a `JobEvent` or outbox event string (e.g. `"job_attempt_begin"`, `"outbox_event_published"`).
- `job_id`, `attempt_no`, `request_id` — when available.
- `detail` — error message or contextual information.

The `request_id` is propagated from the HTTP request through the outbox payload and into the Celery task via task headers (`X-Request-Id`). This allows correlation of a single client request through the full async execution chain.

### 10.2 Log Events Reference

| Event | Level | When |
|-------|-------|------|
| `job_attempt_begin` | INFO | Task starts executing |
| `job_attempt_noop` | INFO | Job already terminal or duplicate |
| `job_attempt_succeeded` | INFO | Executor completed successfully |
| `job_retry_needed` | WARNING | Retryable error, retry pending |
| `job_retry_scheduled` | WARNING | Retry countdown dispatched |
| `job_retry_eager_simulated` | WARNING | Test-mode retry recursion |
| `job_moved_to_dlq` | ERROR | Job moved to dead state |
| `outbox_event_claimed` | INFO | Outbox event picked up for publishing |
| `outbox_event_published` | INFO | Dispatch successful |
| `outbox_event_retry_scheduled` | WARNING | Publish failed, retry scheduled |
| `outbox_event_failed` | ERROR | Publish exhausted retries or unsupported type |

### 10.3 What Is Currently Missing

- **Metrics**: No Prometheus counters or histograms for job throughput, failure rates, DLQ depth, or execution latency.
- **Distributed tracing**: `request_id` propagation exists but no OpenTelemetry spans.
- **DLQ alerting**: No hooks for alerting when jobs enter the DLQ.
- **Stuck-RUNNING detection**: No metrics or alerts for jobs remaining in `RUNNING` beyond a threshold.

---

## 11. Trade-offs and Design Choices

### 11.1 PostgreSQL as the Coordination Layer (not Redis)

The pipeline uses PostgreSQL `SELECT FOR UPDATE` for all concurrency control — not Redis locks or distributed locking. This is a deliberate and correct choice for this pattern:

- Database locks are transactional: they are held for the duration of the DB transaction and automatically released on commit or rollback, including worker crashes.
- Redis locks require explicit TTL management and heartbeat renewal.
- For a system where job state lives in PostgreSQL anyway, keeping all coordination in PostgreSQL eliminates a distributed systems coordination problem.

The trade-off is throughput: `SELECT FOR UPDATE` on a single job row creates a serialization point for concurrent workers targeting the same job. Since each job is processed by exactly one worker, this is not a throughput concern in practice.

### 11.2 Outbox Over Direct Enqueue

Direct `apply_async` after a database commit is simpler to implement but creates a reliability gap: the commit succeeds, the process crashes before enqueue, and the job is silently lost. The outbox pattern eliminates this by making the "intent to dispatch" durable before dispatch is attempted.

The cost is latency (up to 2s dispatch delay) and operational complexity (the publisher must run reliably). For a system that already requires Celery Beat, this cost is marginal.

### 11.3 Executor Context Carries Active Transaction

Executors receive a `JobContext` containing the active `UnitOfWork`. This means domain updates in executors are transactional with the job infrastructure updates. The benefit is atomic consistency: domain outcome and job status are always in sync. The risk is that executors can perform arbitrary database operations in a long-lived transaction, increasing lock hold time and contention risk for large payloads.

An alternative approach would be to run domain updates outside the job transaction, using the job state as a coordination mechanism. This would reduce lock scope but introduce a window where the job is marked `COMPLETED` but the domain update has not yet been applied. The current design accepts the risk of longer transactions in exchange for simpler consistency guarantees.

### 11.4 Idempotency via Unique Constraint + Optimistic Recovery

The system uses a "try-insert, catch IntegrityError, read-back" pattern rather than a pessimistic lock-before-read approach. This is correct for high-concurrency environments because the common case (no conflict) requires no lock, and the uncommon case (race) is resolved by a subsequent read. The semantic validation (same key → same params) adds a second guard against logical idempotency violations.

### 11.5 Synchronous Python (no asyncio in the worker)

The worker pipeline uses synchronous SQLAlchemy and synchronous Celery. Async Python would add complexity without meaningful benefit for this workload: jobs are primarily I/O-bound (database operations), and the concurrency model is at the process level (multiple Celery workers), not at the coroutine level.

---

## 12. Database Schema Overview

```
jobs
  id                 UUID PK
  job_type           VARCHAR(64) INDEX
  idempotency_key    VARCHAR(128) UNIQUE PARTIAL INDEX (WHERE NOT NULL)
  status             ENUM(pending, running, completed, dead) INDEX
  payload            JSONB
  result             JSONB nullable
  attempts           INTEGER
  last_error         TEXT nullable
  created_at, updated_at

job_attempts
  id                 UUID PK
  job_id             VARCHAR → jobs.id (CASCADE DELETE) INDEX
  attempt_no         INTEGER
  status             ENUM(running, succeeded, failed) INDEX
  error              TEXT nullable
  started_at         TIMESTAMPTZ nullable
  finished_at        TIMESTAMPTZ nullable
  created_at         TIMESTAMPTZ
  UNIQUE(job_id, attempt_no)            ← concurrency guard

outbox_events
  id                 UUID PK
  event_type         VARCHAR INDEX
  status             ENUM(pending, published, failed) INDEX
  payload            JSONB
  error              TEXT nullable
  retry_count        INTEGER
  next_attempt_at    TIMESTAMPTZ nullable
  published_at       TIMESTAMPTZ nullable
  created_at, updated_at

reports
  id                 UUID PK
  idempotency_key    VARCHAR(128) UNIQUE PARTIAL INDEX (WHERE NOT NULL)
  status             ENUM(pending, ready) INDEX
  job_id             VARCHAR nullable INDEX
  result             JSONB nullable
  created_at, updated_at
```

Notable design choices:
- Partial unique index on `idempotency_key WHERE NOT NULL` — allows multiple rows with `NULL` while enforcing uniqueness for non-null keys. This is the correct implementation of optional idempotency keys.
- `CASCADE DELETE` from `jobs` to `job_attempts` — cleaning up a job cleans all its attempts.
- No foreign key from `reports.job_id` to `jobs.id` — this is intentional for loose coupling between domains. The relationship is maintained at the application layer.
- Enum types stored as string values (via `enum_value_type()`), not as numeric ordinals — migration-safe and human-readable.
