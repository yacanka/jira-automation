import pytest

from jira_test.config import Config
from jira_test.session import JiraSession


def test_failed_browser_login_closes_candidate(monkeypatch):
    instances = []

    class FailingBrowser:
        def __init__(self, config):
            self.closed = False
            instances.append(self)

        def login(self):
            raise RuntimeError("synthetic login failure")

        def close(self):
            self.closed = True

    monkeypatch.setattr("jira_test.session.Browser", FailingBrowser)
    session = JiraSession(
        Config(base_url="https://jira.test", source_project="SRC", test_project="TST")
    )
    session.api = lambda: object()
    for _ in range(2):
        with pytest.raises(RuntimeError):
            session.live()
    assert all(instance.closed for instance in instances)
    assert session.browser is None
