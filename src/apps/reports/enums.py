import enum


class ReportStatus(str, enum.Enum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
