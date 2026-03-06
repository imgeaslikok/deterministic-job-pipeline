import enum


class ReportStatus(str, enum.Enum):
    pending = "pending"
    ready = "ready"
    failed = "failed"
