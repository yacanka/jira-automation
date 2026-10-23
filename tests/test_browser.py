from unittest.mock import Mock

import pytest

from jira_test.browser import Browser
from jira_test.config import Config
from jira_test.errors import ConfigurationError, WriteBoundaryError


def config(**kwargs):
    return Config(base_url="https://jira.test", source_project="SRC", test_project="TST", **kwargs)


@pytest.fixture
def runtime(monkeypatch):
    playwright = Mock()
    browser = Mock()
    context = browser.new_context.return_value
    page = context.new_page.return_value
    playwright.chromium.launch.return_value = browser
    playwright.firefox.launch.return_value = browser
    factory = Mock()
    factory.return_value.start.return_value = playwright
    monkeypatch.setattr("jira_test.browser.sync_playwright", factory)
    return playwright, browser, context, page, factory


@pytest.mark.parametrize(
    "name,engine,channel",
    [
        ("chrome", "chromium", "chrome"),
        ("edge", "chromium", "msedge"),
        ("firefox", "firefox", None),
    ],
)
@pytest.mark.parametrize("headless", [False, True])
def test_start_settings_and_idempotent_close(runtime, name, engine, channel, headless):
    playwright, native, context, page, factory = runtime
    browser = Browser(config(browser=name, headless=headless, timeout=37))
    assert browser.start() is page
    assert browser.start() is page
    expected = {"headless": headless}
    if channel:
        expected["channel"] = channel
    getattr(playwright, engine).launch.assert_called_once_with(**expected)
    native.new_context.assert_called_once_with(viewport={"width": 1440, "height": 1000})
    page.set_default_timeout.assert_called_once_with(37000)
    page.set_default_navigation_timeout.assert_called_once_with(37000)
    factory.assert_called_once_with()
    browser.close()
    browser.close()
    for resource in (page, context, native):
        resource.close.assert_called_once_with()
    playwright.stop.assert_called_once_with()
    assert browser.page is None


@pytest.mark.parametrize("stage", ["launch", "context", "page", "timeout"])
def test_partial_start_failure_cleans_up_and_sanitizes(runtime, stage):
    playwright, native, context, page, _ = runtime
    failure = {
        "launch": playwright.chromium.launch,
        "context": native.new_context,
        "page": context.new_page,
        "timeout": page.set_default_timeout,
    }[stage]
    failure.side_effect = RuntimeError("sensitive detail")
    browser = Browser(config())
    with pytest.raises(ConfigurationError, match="start") as caught:
        browser.start()
    assert "sensitive detail" not in str(caught.value)
    assert caught.value.__suppress_context__
    playwright.stop.assert_called_once()
    if stage != "launch":
        native.close.assert_called_once()
    if stage in {"page", "timeout"}:
        context.close.assert_called_once()
    if stage == "timeout":
        page.close.assert_called_once()
    assert browser.page is None


def test_close_attempts_all_resources_after_error(runtime):
    playwright, native, context, page, _ = runtime
    browser = Browser(config())
    browser.start()
    page.close.side_effect = RuntimeError("private detail")
    with pytest.raises(ConfigurationError, match="close"):
        browser.close()
    context.close.assert_called_once()
    native.close.assert_called_once()
    playwright.stop.assert_called_once()
    browser.close()


def test_injected_page_login_and_custom_selectors():
    page = Mock(url="https://jira.test/login.jsp")
    page.locator.return_value.get_attribute.return_value = "USER"
    browser = Browser(
        config(username="user", password="test-only", locators={"login.username": "#custom"}),
        page=page,
    )
    assert browser.login() is page
    page.goto.assert_called_once_with("https://jira.test/login.jsp")
    page.locator.assert_any_call("css=#custom")
    page.locator.return_value.fill.assert_any_call("user")
    page.locator.return_value.fill.assert_any_call("test-only")


@pytest.mark.parametrize("failure", ["origin", "user", "interaction"])
def test_login_failure_closes_page(failure):
    page = Mock(url="https://jira.test/login.jsp")
    page.locator.return_value.get_attribute.return_value = "other"
    expected = ConfigurationError
    if failure == "origin":
        page.url = "https://elsewhere.test"
        expected = WriteBoundaryError
    elif failure == "interaction":
        page.locator.return_value.fill.side_effect = RuntimeError("sensitive detail")
    browser = Browser(config(username="user", password="test-only"), page=page)
    with pytest.raises(expected) as caught:
        browser.login()
    assert "sensitive detail" not in str(caught.value)
    page.close.assert_called_once()
    if failure == "origin":
        page.locator.assert_not_called()
    assert browser.page is None


def test_post_login_origin_check_prevents_accepting_external_session():
    page = Mock(url="https://jira.test/login.jsp")
    page.locator.return_value.click.side_effect = lambda: setattr(
        page, "url", "https://elsewhere.test"
    )
    browser = Browser(config(username="user", password="test-only"), page=page)
    with pytest.raises(WriteBoundaryError):
        browser.login()
    page.locator.return_value.get_attribute.assert_not_called()
    page.close.assert_called_once()


def test_login_cleanup_failure_preserves_original_boundary_error():
    page = Mock(url="https://elsewhere.test")
    page.close.side_effect = RuntimeError("private detail")
    browser = Browser(config(username="user", password="test-only"), page=page)
    with pytest.raises(WriteBoundaryError):
        browser.login()
    assert browser.page is None


def test_start_can_retry_after_partial_failure(runtime):
    playwright, native, context, page, factory = runtime
    context.new_page.side_effect = RuntimeError("synthetic failure")
    browser = Browser(config())
    with pytest.raises(ConfigurationError):
        browser.start()
    context.new_page.side_effect = None
    assert browser.start() is page
    assert factory.call_count == 2
    browser.close()
    assert playwright.stop.call_count == 2
