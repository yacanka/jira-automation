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


def test_screenshot_uses_page_only_when_enabled(tmp_path):
    from unittest.mock import Mock

    session = JiraSession(
        Config(
            base_url="https://jira.test",
            source_project="SRC",
            test_project="TST",
            artifact_dir=str(tmp_path),
        )
    )
    session.browser = Mock()
    assert session.screenshot("failure.png") is None
    session.browser.page.screenshot.assert_not_called()
    session.config.screenshots = True
    path = session.screenshot("failure.png")
    assert path == tmp_path / "screenshots" / "failure.png"
    session.browser.page.screenshot.assert_called_once_with(path=str(path))


def test_close_attempts_client_after_browser_failure():
    from unittest.mock import Mock

    session = JiraSession(
        Config(base_url="https://jira.test", source_project="SRC", test_project="TST")
    )
    session.browser = Mock()
    session.client = Mock()
    session.browser.close.side_effect = RuntimeError("synthetic failure")
    browser, client = session.browser, session.client
    with pytest.raises(RuntimeError):
        session.close()
    client.close.assert_called_once()
    session.close()
    browser.close.assert_called_once()
    assert session.ui is None
