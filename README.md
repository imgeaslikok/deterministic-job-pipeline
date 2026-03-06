# FastAPI Deterministic Job Pipeline

This project implements a deterministic background job processing pipeline using **FastAPI**, **Celery**, and **PostgreSQL**.

The goal is not only to execute background tasks but to demonstrate how to build a **production-grade job orchestration system** with deterministic execution, retry safety, and clear domain separation.

The pipeline is domain-agnostic and can be reused by multiple application domains.

A simple **report generation domain** is included as an example.

---

# Architecture Overview

The system is built around a transactional job pipeline that guarantees consistent job execution.

Core components:

```
Client → FastAPI → Job Submission → Celery Queue → Worker → Job Executor → Domain Update
```

All job state transitions are persisted in the database and executed under explicit transaction boundaries.

---

# Design Goals

The system is designed to address common problems found in background job systems.

## Deterministic Job Execution

Job execution is controlled entirely through database state.

Typical lifecycle:

```
pending → running → completed
                  → retry
                  → dead
```

The state machine is enforced by the pipeline.

---

## Retry Safety

Retry behavior ensures that jobs can be safely retried without duplicate side effects.

Features include:

* retry orchestration
* attempt tracking
* exponential backoff
* dead letter queue handling

---

## Transaction Safety

Each job attempt runs within a transactional boundary.

Execution pattern:

```
BEGIN TX
  begin_attempt()
  executor(ctx)
  finalize_attempt()
COMMIT
```

This prevents:

* race conditions
* duplicate execution
* inconsistent job state

---

## Domain Isolation

The job pipeline does not depend on any domain logic.

Domains only register executors.

Example:

```python
@register("report.generate")
def generate_report(ctx, payload):
    ...
```

The worker resolves the executor at runtime using the registry.

---

## Executor Registry

Job types are mapped to executors through a registry.

```
job.type → executor function
```

Executors are registered via decorators and loaded at worker startup.

---

## Attempt Audit Trail

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
    repository.py
  db/
  config/
```

Responsibilities are separated across layers:

| Layer          | Responsibility            |
| -------------- | ------------------------- |
| API            | HTTP interface            |
| Domain         | business logic            |
| Job pipeline   | job orchestration         |
| Infrastructure | persistence and messaging |

---

# Job Execution Flow

Example flow for report generation.

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

A job is inserted into the jobs table.

```
type = report.generate
status = pending
```

---

## 4. Queue Dispatch

The job is sent to the Celery queue.

---

## 5. Worker Execution

The worker processes the job.

```
process_job(job_id)
```

---

## 6. Attempt Start

The pipeline creates a new attempt and moves the job to `running`.

---

## 7. Executor Invocation

The registered executor is called.

```python
generate_report(ctx, payload)
```

---

## 8. Domain Update

The executor updates the report domain state.

```
report.status → ready
```

---

## 9. Attempt Finalization

The pipeline persists the final job state.

```
completed
```

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

* deterministic job execution
* retry orchestration
* dead letter queue handling
* idempotent job submission
* executor registry pattern
* transactional job state machine
* domain isolation
* attempt auditing

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

Tests use:

* pytest
* httpx
* transactional database fixtures


