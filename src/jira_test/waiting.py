"""Bounded polling for persisted REST state and combined UI/API outcomes."""

from collections.abc import Callable
from time import monotonic, sleep
from typing import Literal, TypeVar

from .errors import JiraTestError

T = TypeVar("T")


class WaitTimeoutError(JiraTestError):
    """A condition did not become true within its configured deadline."""


def wait_until(
    condition: Callable[[], T | Literal[False]],
    timeout: float,
    *,
    interval: float = 0.1,
    message: str = "Expected state was not reached before timeout",
) -> T:
    """Return the first truthy result; propagate errors without retrying them.

    Timeout bounds polling, not an in-flight request. REST calls retain their own
    request timeout. Callers must supply a safe message without sensitive values.
    """
    deadline = monotonic() + timeout
    while True:
        result = condition()
        if result:
            return result
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise WaitTimeoutError(message)
        sleep(min(interval, remaining))
