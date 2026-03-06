# FastAPI Deterministic Job Pipeline

This project implements a deterministic background job processing pipeline using **FastAPI**, **Celery**, **PostgreSQL**, and a **Transactional Outbox** for reliable dispatch.

The goal is not only to execute background tasks but to demonstrate how to build a **production-grade job orchestration system** with deterministic execution, retry safety, and reliable job dispatch.

The pipeline is domain-agnostic and can be reused by multiple application domains.

A simple **report generation domain** is included as an example.

---

# Architecture Overview

The system is built around a transactional job pipeline with **reliable job dispatch** using the **Transactional Outbox Pattern**.

Core components:

```

Client
↓
FastAPI
↓
Application Service
↓
Job + Outbox Event (single DB transaction)
↓
Outbox Publisher (Celery Beat)
↓
Job Dispatcher
↓
Celery Worker
↓
Job Executor
↓
Domain Update

```

All job state transitions are persisted in the database and executed under explicit transaction boundaries.

---

# Reliable Job Dispatch (Transactional Outbox)

Traditional async systems often suffer from the classic reliability gap:

```

DB commit → enqueue job

```

If enqueue fails after the commit, the job may **never execute**.

This project solves that using the **Transactional Outbox Pattern**.

During job submission:

```

BEGIN TX
insert job
insert outbox_event
COMMIT

```

A periodic publisher then dispatches pending events.

```

Celery Beat → Outbox Publisher → Job Dispatcher → Celery Worker

```

This guarantees:

* reliable dispatch
* retryable publishing
* no lost jobs

---

# Deterministic Job Execution

Job execution is controlled entirely through database state.

Typical lifecycle:

```

pending → running → completed
                  → retry
                  → dead

```

The state machine is enforced by the pipeline.

---

# Retry Safety

Retry behavior ensures that jobs can be safely retried without duplicate side effects.

Features include:

* retry orchestration
* attempt tracking
* exponential backoff
* dead letter queue handling

---

# Transaction Safety

Each job attempt runs within a transactional boundary.

Execution pattern:

```

BEGIN TX
begin_attempt()
executor(ctx)
finalize_attempt()
COMMIT

````

This prevents:

* race conditions
* duplicate execution
* inconsistent job state

---

# Domain Isolation

The job pipeline does not depend on any domain logic.

Domains only register executors.

Example:

```python
@register("report.generate")
def generate_report(ctx, payload):
    ...
````

The worker resolves the executor at runtime using the registry.

---

# Executor Registry

Job types are mapped to executors through a registry.

```
job.job_type → executor function
```

Executors are registered via decorators and loaded at worker startup.

---

# Attempt Audit Trail

Each execution attempt is stored separately.

Table:

```
job_attempts
```

Fields include:

* job_id
* attempt_no
* status
* error
* started_at
* finished_at

This allows full visibility into retry history and failures.

---

# Project Structure

```
src/
  api/
    v1/
      jobs/
      reports/
  apps/
    reports/
  jobs/
    pipeline.py
    registry.py
    tasks.py
    service.py
    dispatch.py
    repository.py
  outbox/
    service.py
    repository.py
    models.py
  db/
  config/
```

Responsibilities are separated across layers:

| Layer          | Responsibility            |
| -------------- | ------------------------- |
| API            | HTTP interface            |
| Domain         | business logic            |
| Job pipeline   | job orchestration         |
| Outbox         | reliable dispatch         |
| Infrastructure | persistence and messaging |

---

# Job Execution Flow

Example flow for report generation.

---

## 1. Client Request

```
POST /api/v1/reports
```

---

## 2. Report Creation

A report row is created with status:

```
pending
```

---

## 3. Job Submission

A job and an outbox event are created within the same transaction.

```
job.status = pending
outbox_event = job.dispatch.requested
```

---

## 4. Outbox Publishing

A periodic publisher dispatches pending events.

```
Celery Beat → publish_job_dispatch_events
```

---

## 5. Job Dispatch

The dispatcher enqueues the job to Celery.

---

## 6. Worker Execution

The worker processes the job.

```
process_job(job_id)
```

---

## 7. Attempt Start

The pipeline creates a new attempt and moves the job to `running`.

---

## 8. Executor Invocation

The registered executor is called.

```python
generate_report(ctx, payload)
```

---

## 9. Domain Update

The executor updates the report domain state.

```
report.status → ready
```

---

## 10. Attempt Finalization

The pipeline persists the final job state.

```
completed
```

---

# Jobs API

The system exposes endpoints for job inspection and operations.

```
GET  /api/v1/jobs/{id}
GET  /api/v1/jobs/{id}/attempts
GET  /api/v1/jobs/dlq
POST /api/v1/jobs/{id}/retry
```

These endpoints allow:

* job inspection
* DLQ inspection
* retrying dead jobs
* attempt history visibility

---

# Example Domain: Reports

The project includes a minimal domain demonstrating how to integrate with the pipeline.

Endpoints:

```
POST /api/v1/reports
GET  /api/v1/reports/{id}
```

The executor simulates generating a report and persists the result.

---

# Key Features

The project demonstrates the following architectural patterns:

* transactional outbox
* deterministic job execution
* retry orchestration
* dead letter queue handling
* idempotent job submission
* executor registry pattern
* transactional job state machine
* domain isolation
* attempt auditing
* API-level job observability

---

# Running the Project

Dependencies are managed using Docker.

Start the system:

```
make up
```

Run migrations:

```
make migrate
```

Run tests:

```
make test
```

---

# Test Coverage

The test suite validates both the job pipeline and the domain integration.

Coverage includes:

* job success execution
* retry behavior
* dead letter handling
* idempotency guarantees
* executor failure handling
* domain invariants
* API error mapping
* outbox dispatch reliability

Tests use:

* pytest
* httpx
* transactional database fixtures

---

# License

MIT License


