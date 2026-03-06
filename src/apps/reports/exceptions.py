from __future__ import annotations


class ReportsError(Exception):
    """Base class for reports domain errors."""


class ReportNotFound(ReportsError):
    def __init__(self, report_id: str):
        self.report_id = report_id
        super().__init__(f"Report not found: {report_id}")


class InvalidReportState(ReportsError):
    def __init__(self, report_id: str, *, status: str):
        self.report_id = report_id
        self.status = status
        super().__init__(f"Invalid report state: {report_id} status={status}")


class ReportJobAlreadyAttached(ReportsError):
    def __init__(self, report_id: str, *, existing_job_id: str, new_job_id: str):
        self.report_id = report_id
        self.existing_job_id = existing_job_id
        self.new_job_id = new_job_id
        super().__init__(
            f"Report already has a different job attached: {report_id} "
            f"existing={existing_job_id} new={new_job_id}"
        )
