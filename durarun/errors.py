"""durarun custom exceptions."""

from __future__ import annotations


class DurarunError(Exception):
    """Base exception for all durarun errors."""


class StepTimeout(DurarunError):
    """Raised when a step exceeds its allowed execution time."""

    def __init__(
        self,
        step_name: str,
        timeout_seconds: float,
        message: str = "",
    ) -> None:
        self.step_name = step_name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            message
            or f"Step '{step_name}' timed out after {timeout_seconds}s"
        )


class StepRetryExhausted(DurarunError):
    """Raised when a step has exhausted all retry attempts."""

    def __init__(
        self,
        step_name: str,
        max_retries: int,
        last_exception: BaseException | None = None,
        message: str = "",
    ) -> None:
        self.step_name = step_name
        self.max_retries = max_retries
        self.last_exception = last_exception
        super().__init__(
            message
            or (
                f"Step '{step_name}' failed after {max_retries} retries"
                + (f": {last_exception}" if last_exception else "")
            )
        )


class WALCorrupted(DurarunError):
    """Raised when the WAL data is corrupted or unreadable."""

    def __init__(self, details: str = "") -> None:
        self.details = details
        super().__init__(f"WAL corrupted: {details}" if details else "WAL corrupted")
