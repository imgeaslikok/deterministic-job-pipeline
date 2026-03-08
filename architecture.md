# Architecture — deterministic-job-pipeline

---

## 1. Architectural Style

The system follows a **layered architecture with explicit domain boundaries**, structured into four layers:

```
┌──────────────────────────────────────────────┐
│               API Layer                      │  HTTP, schemas, exception mapping
├──────────────────────────────────────────────┤
│           Application Layer                  │  Domain services, use cases, UoW boundaries
├──────────────────────────────────────────────┤
│  Job Pipeline / Outbox / Repositories        │  Infrastructure, state machines, persistence
├──────────────────────────────────────────────┤
│         Database / Broker                    │  PostgreSQL, Redis / Celery
└──────────────────────────────────────────────┘
```

The architecture is not hexagonal in the strict sense — ports and adapters are not systematically applied across every boundary. Instead, the system uses **selective port abstraction** at the highest-coupling point: the `JobSubmitter` Protocol in [src/jobs/ports.py](src/jobs/ports.py) allows domain code in `src/apps/` to depend on a callable interface rather than a concrete import from the jobs service. This is the correct tradeoff: full hexagonal purity would add indirection without benefit at this project's scale.

Domain-Driven Design vocabulary is applied pragmatically. There are no aggregates with in-memory invariant enforcement, but domain exceptions, domain services, domain-specific enums, and bounded context isolation are all present and consistently applied.

---

## 2. Layer Responsibilities

### 2.1 API Layer — `src/api/`

**Responsibility**: Translate HTTP into application service calls. Map domain results and exceptions to HTTP responses.

The API layer is intentionally thin. Routers extract validated parameters, open a `UnitOfWork`, call a domain service, and serialize the result. No business logic lives in routers.

Exception handlers in `api/v1/{domain}/exceptions.py` are **auto-discovered** at startup via `exception_registry.py`, which scans API version packages for modules exposing a `register(app)` function. This means adding a new domain's exception handlers requires only placing the handler file in the right location — no changes to central configuration.

**Dependency direction**: `API → Application services`. Never the reverse.

### 2.2 Application Layer — `src/apps/`, `src/jobs/service.py`

**Responsibility**: Orchestrate domain operations within explicit transaction boundaries. Coordinate between domain objects and shared infrastructure services (job submission, outbox).

`reports/service.py::create_report` is the canonical example of an application service:

```
create_report(uow, idempotency_key, request_id, submit_job)
  ├─ Check for existing report by idempotency_key  (read, no lock)
  ├─ Create report row with begin_nested() + IntegrityError fallback
  ├─ submit_job(uow, ...)                           (creates job row + outbox event)
  └─ _attach_job_to_report(uow.session, ...)        (under SELECT FOR UPDATE)
```

All four steps happen within the same `UnitOfWork`. They commit together or roll back together. This is the correct scope for an application service: one use case, one transaction boundary.

`jobs/service.py` manages the jobs domain: submit, retry from DLQ, inspect. It is consumed both by domain application services (via the `JobSubmitter` protocol) and by the API layer directly for read operations.

### 2.3 Job Pipeline — `src/jobs/`

**Responsibility**: Reliable job lifecycle management — dispatch, execution, attempt tracking, retry, DLQ. This is the core infrastructure of the project and is entirely domain-agnostic.

| Module | Role |
|--------|------|
| `service.py` | Application-facing API: submit, retry, inspect |
| `pipeline.py` | Low-level state machine: `begin_attempt`, `finalize_attempt`, `reset_stuck_running_jobs` |
| `runner.py` | Execution orchestration: resolve context → begin → run → finalize → schedule retry |
| `tasks.py` | Thin Celery entrypoints; delegates entirely to runner |
| `registry.py` | Executor registry: maps job type strings to callable handlers |
| `dispatch.py` | Abstraction over the dispatch mechanism (Celery or Noop) |
| `publish.py` | Bridge from outbox service to the job dispatcher |

The pipeline does not import from `src/apps/`. Domains integrate by registering executor functions at worker startup via the `JOB_EXECUTORS` setting. This inversion is the central extensibility mechanism.

### 2.4 Transactional Outbox — `src/outbox/`

**Responsibility**: Guarantee eventual delivery of job dispatch events to the Celery broker, independent of broker availability at submission time.

The outbox is an independent infrastructure module. It operates on generic `OutboxEvent` rows — it does not know about jobs specifically. The `_publish_single_event` function dispatches on `event.event_type`; `JOB_DISPATCH_REQUESTED` is the only type currently handled, but the switch is extensible.

### 2.5 Database Infrastructure — `src/db/`

**Responsibility**: Shared database primitives: session management, the Unit-of-Work abstraction, shared mixins (UUIDs, timestamps), and shared repository helpers.

This layer is deliberately minimal. There is no generic base repository class — just shared helper functions (`save`, `save_and_refresh`) and mixins. Domain-specific repository modules live alongside their respective domain models.

---

## 3. Dependency Direction

```
api/v1/
  └─► apps/reports/service (via JobSubmitter Protocol)
            │
            ▼
       jobs/service  ◄──────────── jobs/pipeline
            │                           │
            ▼                           ▼
       outbox/service              jobs/repository
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

- `api/` never imports from `apps/` directly in routers (it receives them via DI).
- `apps/` modules depend on `jobs/` only via the `JobSubmitter` Protocol.
- `jobs/` depends on `outbox/` for event creation; `outbox/` does not depend on `jobs/`.
- `db/` has no upward dependencies.

**Circular import resolved**: `dispatch.py` previously imported `process_job` at module level from `tasks.py`, creating a within-package circular dependency resolved only by Python's import ordering. The import is now deferred inside `CeleryJobDispatcher.dispatch()`, which breaks the cycle at the module level. The dependency is still present at runtime, but it is now explicit and safe.

---

## 4. Data Flow and Control Flow

### 4.1 Job Submission

```
HTTP POST /api/v1/reports
  │
  ├─ RequestIdMiddleware assigns X-Request-Id
  │
  ├─ reports router: get_uow() → UnitOfWork, extract headers
  │
  ├─ reports_service.create_report(uow, idempotency_key, request_id, submit_job=submit_job)
  │     │
  │     ├─ _get_existing_report_by_idempotency_key()    (non-locking fast path)
  │     ├─ _create_report_with_recovery()               (begin_nested + IntegrityError fallback)
  │     ├─ submit_job(uow, job_type, payload, ...)
  │     │     ├─ _create_job_row()                      (begin_nested + IntegrityError fallback)
  │     │     └─ outbox_service.create_event(JOB_DISPATCH_REQUESTED, {job_id, request_id})
  │     └─ _attach_job_to_report()                      (SELECT FOR UPDATE)
  │
  └─ uow.__exit__() → COMMIT
       (report row + job row + outbox event — all atomic)
```

### 4.2 Dispatch

```
Celery Beat (every 2s) → publish_job_dispatch_events()
  │
  └─ outbox_service.publish_pending_events(SessionLocal, dispatch_job)
       │
       ├─ Phase 1 — Batch claim (one session):
       │     SELECT id FROM outbox_events
       │     WHERE status=pending AND (next_attempt_at IS NULL OR next_attempt_at <= now)
       │     ORDER BY created_at ASC, id ASC
       │     FOR UPDATE SKIP LOCKED
       │     LIMIT 100
       │   → COMMIT  (releases lock, no claim persisted — this is ID collection only)
       │
       └─ Phase 2 — Per-event processing (separate session per event):
             ├─ SELECT ... FOR UPDATE  (re-acquire exclusive lock)
             ├─ Verify status == PENDING  (guard against concurrent publisher)
             ├─ CeleryJobDispatcher.dispatch(job_id, request_id)
             │     └─ process_job.apply_async(args=(job_id,), headers={X-Request-Id: ...})
             ├─ UPDATE outbox_events SET status=published, published_at=now
             └─ COMMIT per event
```

The two-phase design is deliberate: Phase 1 collects IDs efficiently (SKIP LOCKED avoids contention on already-processing events), commits to release locks, then Phase 2 processes each event independently so a failure on event N does not affect events N+1..M.

### 4.3 Execution

```
Celery Worker → process_job(job_id)
  │
  ├─ _resolve_celery_context(task)
  │     └─ Extracts current_retries, max_retries, request_id from task.request
  │
  ├─ Log ATTEMPT_BEGIN (job_id, request_id, retry count)
  │
  ├─ Open SessionLocal
  │
  └─ _execute_job_attempt(db, job_id, started_at, celery_ctx)
       │
       └─ with UnitOfWork(db) as uow:
             │
             ├─ pipeline.begin_attempt(uow.session, job_id, started_at)
             │     ├─ SELECT jobs WHERE id=? FOR UPDATE   (row lock)
             │     ├─ if COMPLETED or DEAD → return AttemptResult(should_run=False, "terminal")
             │     ├─ attempt_no = job.attempts + 1
             │     ├─ UPDATE jobs SET status=running, attempts=attempt_no
             │     ├─ INSERT job_attempts (attempt_no, status=running, started_at)
             │     └─ db.flush()  → IntegrityError on duplicate → AttemptResult(False, "duplicate")
             │
             ├─ if not should_run → return NOOP outcome
             │
             └─ _run_executor(uow, job, attempt_no, celery_ctx)
                   │
                   ├─ get_executor(job.job_type)           (raises ExecutorNotRegistered if missing)
                   │
                   ├─ executor(JobContext(uow, job_id, attempt_no, request_id), payload)
                   │     └─ Domain work within the same UoW transaction
                   │
                   ├─ On success: attempt_status=SUCCEEDED, job_status=COMPLETED
                   ├─ On RetryableJobError: classify → retry or DLQ (if retries exhausted)
                   ├─ On NonRetryableJobError: → DLQ immediately
                   ├─ On ExecutorNotRegistered: → DLQ immediately
                   ├─ On unexpected Exception: capture traceback, re-raise
                   │
                   └─ finally: _safe_finalize_attempt(uow.session, ...)
                         └─ with db.begin_nested():         (savepoint)
                               ├─ UPDATE job_attempts SET status, error, finished_at
                               └─ UPDATE jobs SET status, last_error, result
                         → metrics emitted: JOB_DURATION_SECONDS, JOB_ATTEMPTS_TOTAL
```

### 4.4 Retry and DLQ

```
need_retry=True:
  ├─ In eager mode (tests): task.apply(args, retries=current+1)
  └─ In normal mode: raise task.retry(exc=..., countdown=retry_countdown(n))
       └─ retry_countdown(n) = random.randint(0, min(2^n * base, cap))
              (full jitter exponential backoff, default cap 60s)

need_retry=False (DLQ):
  ├─ job.status = DEAD persisted via finalize_attempt
  └─ task returns normally (no retry raised)

Manual retry via POST /api/v1/jobs/{id}/retry:
  ├─ SELECT FOR UPDATE (prevent double-retry race)
  ├─ Validate status == DEAD
  ├─ UPDATE jobs SET status=pending, last_error=None, result=None
  └─ INSERT outbox_event (JOB_DISPATCH_REQUESTED)
```

### 4.5 Stuck Job Recovery

```
Celery Beat (every 60s) → reset_stuck_running_jobs()
  │
  └─ pipeline.reset_stuck_running_jobs(db, max_execution_seconds=300)
       │
       ├─ SELECT jobs WHERE status=running AND updated_at < now - 300s
       │   LIMIT 50
       │
       └─ For each stuck job:
             ├─ UPDATE jobs SET status=pending, last_error="Reset from RUNNING by sweeper"
             └─ INSERT outbox_event (JOB_DISPATCH_REQUESTED, {job_id})
       └─ COMMIT
```

---

## 5. Transaction Boundaries

There are three distinct transaction scopes in the system.

### 5.1 API Request Transaction

```python
with UnitOfWork(db) as uow:
    result = service_function(uow, ...)
# Commits on clean exit, rolls back on exception
```

Covers the full application service use case. For report creation: report row + job row + outbox event — all or nothing. This is the atomicity guarantee that makes the outbox pattern safe: the dispatch event is only created if the domain operation succeeds.

### 5.2 Worker Execution Transaction

```python
with UnitOfWork(db) as uow:
    begin = pipeline.begin_attempt(uow.session, ...)
    executor(JobContext(uow, ...), payload)   # domain work here
    # finalize_attempt in finally, inside begin_nested() savepoint
# Commits on clean exit
```

The executor runs inside the worker's Unit of Work. Domain state updates (e.g., `complete_report`) are committed in the same transaction as the job and attempt status finalization. This is the key consistency guarantee: domain outcome and job infrastructure state are always in sync.

The `begin_nested()` in `_safe_finalize_attempt` creates a savepoint. If finalization fails, the savepoint is rolled back but the outer transaction continues — preventing a finalization failure from losing the executor's domain work. The sweeper will subsequently recover any job left in RUNNING state.

**Edge case — unclassified exceptions**: For exceptions that are neither `RetryableJobError`, `NonRetryableJobError`, nor `ExecutorNotRegistered`, `_run_executor` re-raises after capturing the traceback. The outer `UnitOfWork.__exit__` calls `rollback()`, which undoes both the `begin_attempt` mutations and the `finalize_attempt` savepoint work. The job returns to its pre-attempt state (PENDING) with no attempt record.

With `task_acks_on_failure_or_timeout=False` now configured, Celery will **nack** the task message on unhandled failure rather than acknowledging it. The broker requeues the task, which will re-enter `begin_attempt` and run again. Combined with the idempotent `begin_attempt` design, this means unclassified exceptions behave as implicit retries from the broker's perspective rather than silently losing the task. Executor authors should still classify errors explicitly via `RetryableJobError`/`NonRetryableJobError` — the nack behaviour is a safety net, not the intended path.

### 5.3 Outbox Per-Event Transaction

Each outbox event is processed in its own session and committed independently. A failure on event N does not affect the published status of events 1..N-1. The Phase 1 batch ID collection is also committed immediately, releasing SKIP LOCKED row locks so the IDs can be re-claimed if processing fails mid-batch.

---

## 6. Async Processing Model

The system uses **Celery with Redis** as the task broker and result backend.

**Producer**: FastAPI API processes write to PostgreSQL. Celery Beat reads pending outbox events and dispatches task messages to Redis.

**Consumer**: Celery workers pull `process_job` tasks from Redis queues and execute them synchronously.

**Coordination**: PostgreSQL row-level locks (`SELECT FOR UPDATE`) are used for execution coordination — not Redis locks. This is a deliberate and correct choice:

- Database locks are transactional: held for the duration of the DB transaction, automatically released on commit, rollback, or worker crash.
- Redis locks require explicit TTL management and heartbeat renewal.
- Since job state lives in PostgreSQL, keeping all coordination in PostgreSQL eliminates a distributed systems coordination problem.

The pipeline uses **synchronous Python** throughout (no `asyncio` in workers). Async Python would add complexity without meaningful benefit: jobs are I/O-bound (database operations), and concurrency is achieved at the process level (multiple Celery workers), not at the coroutine level. FastAPI's `run_in_threadpool` is used only for the DB readiness probe and the metrics endpoint.

**Maximum dispatch latency**: ~2 seconds (one Beat tick) from job submission to task queuing.

**Maximum recovery latency for stuck jobs**: ~60 seconds (one sweeper tick) plus one outbox publish cycle.

---

## 7. Error Handling Strategy

### 7.1 Domain Exceptions → API Responses

Domain exceptions (`JobNotFound`, `InvalidJobState`, `IdempotencyKeyConflict`, `ReportNotFound`) are raised in service layers and caught by FastAPI exception handlers registered at startup. The handlers live in `api/v1/{domain}/exceptions.py` and are auto-discovered by `exception_registry.py`. This keeps HTTP concerns out of business logic.

### 7.2 Executor Errors → Pipeline Signals

Executors communicate intent through exception type:

| Exception | Classification | Pipeline Action |
|-----------|---------------|-----------------|
| `RetryableJobError` | Transient failure | Retry with backoff; DLQ after max_retries |
| `NonRetryableJobError` | Permanent failure | DLQ immediately |
| `ExecutorNotRegistered` | Configuration error | DLQ immediately |
| Any other `Exception` | Unexpected bug | Re-raise → broker nacks → task requeued (see §5.2) |

`_classify_execution_error` in `runner.py` maps these exceptions to `_ErrorClassification` values, which drive the `finalize_attempt` call and the retry decision. This is not a general-purpose exception handler — it is a typed dispatch table.

### 7.3 Outbox Publish Errors

Outbox publish failures are retried with exponential backoff with full jitter (base 30s, cap 600s, max 5 retries). The retry count and `next_attempt_at` are persisted on the `OutboxEvent` row. After exhausting retries, the event is marked `FAILED`. There is no automatic recovery from a `FAILED` outbox event — this requires manual intervention.

`is_terminal_publish_error` in `outbox/utils.py` determines which exceptions should skip retries entirely. Currently, only `UnsupportedOutboxEventType` is terminal.

### 7.4 Attempt Finalization Errors

`_safe_finalize_attempt` in `runner.py` wraps `finalize_attempt` in a savepoint and catches all exceptions. If finalization fails:
- The job remains in RUNNING state.
- The sweeper recovers it within ~60 seconds.
- The failure is emitted as a structured `JobEvent.FINALIZE_FAILED` log entry (using `build_log_extra`) — not a plain `logger.exception` call — so it can be queried and alerted on in log aggregation systems like any other pipeline event.
- The failure does not propagate (the executor's work is preserved if its domain updates committed before the exception).

---

## 8. Consistency Strategy

The system targets **strong consistency within a single transaction boundary** and **eventual consistency across asynchronous hops**.

### Strongly Consistent

| What | How |
|------|-----|
| Job row + outbox event | Written in the same API request transaction |
| Job status + attempt status | Finalized in the same worker transaction |
| Domain state + job outcome | Executor domain work inside the same worker UoW |
| Idempotent job submission | Partial unique index + `begin_nested` + `IntegrityError` fallback |
| Idempotent attempt creation | `UNIQUE(job_id, attempt_no)` database constraint |

### Eventually Consistent

| What | Latency | Mechanism |
|------|---------|-----------|
| Outbox event → Celery dispatch | ≤2s | Beat publishes every 2s |
| Stuck RUNNING → recovery | ≤60s | Sweeper runs every 60s |
| Job completion → client knowledge | Poll-based | No push mechanism |

### Idempotency Implementation

**Job submission**: `UNIQUE(idempotency_key) WHERE NOT NULL` partial index on `jobs`. Application code uses a fast-path non-locking read, followed by an insert in `begin_nested()`, followed by an `IntegrityError` fallback read. Semantic validation (`_validate_idempotent_match`) ensures the same key cannot be reused with different `job_type` or `payload`. This two-layer approach is correct for concurrent environments: the fast path avoids the overhead for the common case, and the IntegrityError path handles the race condition.

**Attempt creation**: `UNIQUE(job_id, attempt_no)` on `job_attempts`. A concurrent duplicate invocation gets `IntegrityError` at `db.flush()` in `begin_attempt` → returns `AttemptResult(should_run=False, "duplicate")`. The task exits cleanly without executing the executor.

**Outbox claiming**: `FOR UPDATE SKIP LOCKED` in Phase 1 + status re-check in Phase 2. Two publishers cannot process the same event concurrently.

---

## 9. Extensibility Points

### 9.1 New Job Types

Register a new executor in any domain module:

```python
@register("new_domain.do_work")
def do_work(ctx: JobContext, payload: dict) -> ExecutionResult:
    ...
```

Add the module to `JOB_EXECUTORS`. No changes to the pipeline required. The registry lookup (`get_executor(job.job_type)`) will find it at runtime.

### 9.2 New Outbox Event Types

The `_publish_single_event` function in `outbox/service.py` dispatches on `event.event_type`. Adding a new event type requires:

1. A new constant in `outbox/events.py`
2. A new dispatch handler called from `_publish_single_event`
3. An update to `is_terminal_publish_error` if the new type has different terminal error semantics

### 9.3 New Domains

New domains follow the reports domain pattern:

1. `src/apps/{domain}/` — service, repository, models, executors, exceptions
2. Executor module registered in `JOB_EXECUTORS`
3. API routes in `src/api/v1/{domain}/` — router, schemas, exceptions
4. Router included in `src/api/v1/router.py`

The pipeline, outbox, and database infrastructure require no modification.

### 9.4 Swapping the Job Dispatcher

The `JobDispatcher` Protocol in `dispatch.py` defines a single method `dispatch(job_id, request_id)`. Replacing Celery with another broker (e.g., AWS SQS, RabbitMQ) requires only a new `JobDispatcher` implementation and an update to `_build_dispatcher`. The pipeline, outbox, and domain code are unaffected.

---

## 10. Observability Model

### 10.1 Structured Logging

All pipeline and outbox events are logged using `build_log_extra()`, which produces a dictionary of non-null fields suitable for log aggregation systems (ELK, Loki, Datadog). Every relevant log entry includes:

- `component` — e.g., `"jobs.worker"`, `"outbox.publisher"`
- `event` — a `JobEvent` or outbox event string constant
- `job_id`, `attempt_no` — when available
- `request_id` — propagated from the original HTTP request through the full async chain
- `detail` — error message or contextual information

Pipeline log events emitted via `build_log_extra()`:

| Event | Level | When |
|-------|-------|------|
| `job_attempt_begin` | INFO | Task starts executing |
| `job_attempt_noop` | INFO | Job already terminal or duplicate invocation |
| `job_attempt_succeeded` | INFO | Executor completed successfully |
| `job_retry_needed` | WARNING | Retryable error, retry pending |
| `job_retry_scheduled` | WARNING | Retry countdown dispatched |
| `job_moved_to_dlq` | ERROR | Job moved to dead state |
| `job_finalize_failed` | ERROR | Finalization savepoint failed — job may be stuck in RUNNING until sweeper recovers it |
| `outbox_event_claimed` | INFO | Outbox event picked up for publishing |
| `outbox_event_published` | INFO | Dispatch successful |
| `outbox_event_retry_scheduled` | WARNING | Publish failed, retry scheduled |
| `outbox_event_failed` | ERROR | Publish exhausted retries or unsupported type |

The `request_id` propagation path:
```
HTTP X-Request-Id header
  → stored in outbox event payload (via submit_job)
  → forwarded as Celery task header (via CeleryJobDispatcher)
  → extracted from task.request.headers (via _resolve_celery_context)
  → included in all worker log entries
```

This allows a single client request to be traced through its async execution chain in any log aggregation system without distributed tracing infrastructure.

### 10.2 Prometheus Metrics

Three metrics are emitted and exposed at `/metrics`:

| Metric | Type | Labels | Emitted In |
|--------|------|--------|-----------|
| `job_attempts_total` | Counter | `job_type`, `status` | `runner._run_executor` finally block |
| `job_duration_seconds` | Histogram | `job_type` | `runner._run_executor` finally block |
| `outbox_events_total` | Counter | `outcome` | `outbox.service` publish/fail/retry paths |

Both metrics in `_run_executor` are emitted in the `finally` block, meaning they fire for every attempt outcome including failure — guaranteeing no outcome is silently unobservable.

### 10.3 Health and Readiness Probes

- `GET /healthz` — always returns 200. Liveness probe.
- `GET /readyz` — executes `SELECT 1` against the configured database. Returns 503 on failure. Readiness probe.

There is no broker (Redis) health check in the readiness probe. Workers that can reach the database but not Redis would still return ready.

### 10.4 What Is Currently Missing

| Gap | Impact | Mitigation |
|-----|--------|-----------|
| No DLQ depth gauge | Cannot alert on accumulating dead jobs | Query `jobs` table with `status=dead` for ad hoc monitoring |
| No outbox backlog gauge | Cannot alert on publish lag | Query `outbox_events` table with `status=pending` |
| No retry count label on `job_attempts_total` | Cannot distinguish first vs. Nth attempt outcomes | Check structured logs |
| No distributed tracing (OpenTelemetry) | Cannot visualize latency across API→Beat→Worker | `request_id` propagation provides partial correlation |

---

## 11. Trade-offs and Design Reasoning

### 11.1 PostgreSQL as Coordination Layer

**What it optimizes for**: Correctness and simplicity. Database locks are transactional — they are held for the duration of the DB transaction and automatically released on commit, rollback, or crash. No external lock management required.

**What it sacrifices**: Throughput. A `SELECT FOR UPDATE` on a job row creates a serialization point. For jobs processed by many concurrent workers, this is not a bottleneck because each job is a separate row — workers contend only when targeting the exact same job, which should be rare.

**Is it reasonable?** Yes. For a system that already requires PostgreSQL for durable state, using the same database for coordination is strictly simpler than introducing a distributed lock service.

### 11.2 Outbox Over Direct Enqueue

**What it optimizes for**: Reliability. The job row and dispatch event are written atomically. A process crash between submission and enqueue cannot silently lose a job.

**What it sacrifices**: Latency (up to 2s), operational complexity (Beat must run), and one additional component to operate.

**Is it reasonable?** Yes. For a system that already requires Celery Beat for periodic tasks, the marginal cost is low. The reliability guarantee is essential for any production job system.

### 11.3 Executor Context Carries Active Transaction

**What it optimizes for**: Atomic consistency between domain state and job infrastructure state. A report marked READY and a job marked COMPLETED are always consistent — they commit in the same transaction.

**What it sacrifices**: Transaction duration. Executors can hold open a database transaction for as long as they run, increasing lock hold time and potential for contention on rows accessed by both the executor and concurrent requests.

**Is it reasonable?** Yes, at current scale. For long-running executors that perform many database operations, the risk increases. Executors should be designed to complete quickly; slow operations (e.g., external API calls) should be outside the UoW or designed to fail fast.

### 11.4 Optimistic Idempotency (insert-then-fallback)

**What it optimizes for**: Performance in the common case (no conflict). The fast path requires no lock at all.

**What it sacrifices**: Complexity. The `begin_nested` + `IntegrityError` fallback + semantic validation pattern is not obvious, and the two-layer approach (fast-path read + insert + fallback read) must be correctly maintained.

**Is it reasonable?** Yes. The alternative (pessimistic lock-before-read) would require a `SELECT FOR UPDATE` on every submission, even when no conflict exists. For high-submission-rate job systems, optimistic concurrency is the correct default.

### 11.5 Full Jitter Exponential Backoff

**What it optimizes for**: Thundering herd avoidance. When many jobs fail simultaneously, full jitter (`random.randint(0, max_delay)`) distributes retry attempts across the full delay window rather than clustering them.

**What it sacrifices**: Predictability. The retry delay is not deterministic. The lower bound of 0 means immediate retries are possible.

**Is it reasonable?** Yes for the job pipeline. The outbox publisher runs independently every 2 seconds regardless; jitter only affects when failed jobs re-enter the queue.

---

## 12. Database Schema

```
jobs
  id                UUID PK
  job_type          VARCHAR(64)  INDEX
  idempotency_key   VARCHAR(128) UNIQUE PARTIAL INDEX (WHERE NOT NULL)
  status            ENUM(pending, running, completed, dead)  INDEX
  payload           JSONB
  result            JSONB nullable
  attempts          INTEGER
  last_error        TEXT nullable
  created_at        TIMESTAMPTZ
  updated_at        TIMESTAMPTZ   ← used by sweeper for stuck-job detection

job_attempts
  id                UUID PK
  job_id            VARCHAR → jobs.id (CASCADE DELETE)  INDEX
  attempt_no        INTEGER
  status            ENUM(running, succeeded, failed)  INDEX
  error             TEXT nullable
  started_at        TIMESTAMPTZ nullable
  finished_at       TIMESTAMPTZ nullable
  created_at        TIMESTAMPTZ
  UNIQUE(job_id, attempt_no)           ← concurrency guard for duplicate invocations

outbox_events
  id                UUID PK
  event_type        VARCHAR  INDEX
  status            ENUM(pending, published, failed)  INDEX
  payload           JSONB
  error             TEXT nullable
  retry_count       INTEGER
  next_attempt_at   TIMESTAMPTZ nullable  ← enables deferred retry
  published_at      TIMESTAMPTZ nullable
  created_at        TIMESTAMPTZ
  updated_at        TIMESTAMPTZ

reports
  id                UUID PK
  idempotency_key   VARCHAR(128) UNIQUE PARTIAL INDEX (WHERE NOT NULL)
  status            ENUM(pending, ready, failed)  INDEX
  job_id            VARCHAR nullable  INDEX  ← no FK to jobs (intentional loose coupling)
  result            JSONB nullable
  created_at        TIMESTAMPTZ
  updated_at        TIMESTAMPTZ
```

**Notable design choices**:

- **Partial unique index on `idempotency_key WHERE NOT NULL`**: Correctly allows multiple `NULL` keys while enforcing uniqueness for non-null ones. Standard SQL `UNIQUE` on a nullable column would require explicit NULL handling.
- **CASCADE DELETE on `job_attempts`**: Cleaning up a job cleans all its attempt history. No orphan attempt rows.
- **No foreign key from `reports.job_id` to `jobs.id`**: Intentional loose coupling between domains. The relationship is maintained at the application layer. This allows reports and jobs to evolve their schemas independently.
- **Enum stored as string values** (via `enum_value_type()`): Migration-safe and human-readable in the database. Avoids ordinal-based enum migration problems.
- **`updated_at` on `jobs`**: Serves double duty as the stuck-job detection timestamp. The sweeper queries `updated_at < now - max_execution_seconds` to find jobs that have been in RUNNING state without any update.

---

## 13. Known Gaps and Future Directions

| Area | Current State | Risk |
|------|---------------|------|
| Outbox publisher — single Beat | Cannot horizontally scale Beat | Low: Beat is single-instance by convention |
| Redis health in readiness probe | Not checked | Low: workers fail fast on missing broker |
