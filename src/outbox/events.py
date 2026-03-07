"""
Outbox event type identifiers and publisher log event names.
"""

# domain event types
JOB_DISPATCH_REQUESTED = "job.dispatch.requested"


# publisher lifecycle events
OUTBOX_EVENT_CLAIMED = "outbox.event.claimed"
OUTBOX_EVENT_PUBLISHED = "outbox.event.published"
OUTBOX_EVENT_RETRY_SCHEDULED = "outbox.event.retry_scheduled"
OUTBOX_EVENT_FAILED = "outbox.event.failed"
