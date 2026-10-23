from unittest.mock import Mock

import pytest

from jira_test.errors import ApiError
from jira_test.waiting import WaitTimeoutError, wait_until


def test_poll_returns_eventual_value():
    condition = Mock(side_effect=[False, False, {"ready": True}])
    assert wait_until(condition, 0.1, interval=0.001) == {"ready": True}
    assert condition.call_count == 3


def test_poll_timeout_has_safe_message():
    with pytest.raises(WaitTimeoutError, match="Persisted state not reached"):
        wait_until(lambda: False, 0.002, interval=0.001, message="Persisted state not reached")


def test_poll_does_not_swallow_api_errors():
    condition = Mock(side_effect=ApiError("Unavailable", status=503))
    with pytest.raises(ApiError):
        wait_until(condition, 0.1)
    condition.assert_called_once()
