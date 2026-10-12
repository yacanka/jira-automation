"""Errors distinguish unsupported contexts from actual test assertions."""


class JiraTestError(Exception):
    """Base exception with a safe, user-facing message."""


class ConfigurationError(JiraTestError):
    pass


class ScenarioError(JiraTestError):
    pass


class ApiError(JiraTestError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class WriteBoundaryError(JiraTestError):
    pass


class UnsupportedFieldError(JiraTestError):
    pass


class ContextUnavailable(JiraTestError):
    pass
