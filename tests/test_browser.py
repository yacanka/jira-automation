from unittest.mock import Mock

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.firefox.service import Service as FirefoxService

from jira_test.browser import Browser
from jira_test.config import Config


@pytest.mark.parametrize(
    "browser_name,constructor,options_type,service_type,headless_arg",
    [
        ("chrome", "Chrome", webdriver.ChromeOptions, ChromeService, "--headless=new"),
        ("firefox", "Firefox", webdriver.FirefoxOptions, FirefoxService, "-headless"),
        ("edge", "Edge", webdriver.EdgeOptions, EdgeService, "--headless=new"),
    ],
)
@pytest.mark.parametrize("headless", [False, True])
@pytest.mark.parametrize("driver_path", [None, "C:/Tools/browserdriver.exe"])
def test_start_uses_selected_browser_and_settings(
    monkeypatch,
    browser_name,
    constructor,
    options_type,
    service_type,
    headless_arg,
    headless,
    driver_path,
):
    # Service reserves a port even when the WebDriver process is replaced below.
    monkeypatch.setattr("selenium.webdriver.common.utils.free_port", lambda: 45678)
    driver = Mock()
    factory = Mock(return_value=driver)
    monkeypatch.setattr(webdriver, constructor, factory)
    config = Config(
        base_url="https://jira.test",
        source_project="SRC",
        test_project="TST",
        browser=browser_name,
        headless=headless,
        driver_path=driver_path,
        timeout=37,
    )
    browser = Browser(config)

    assert browser.start() is driver
    options = factory.call_args.kwargs["options"]
    service = factory.call_args.kwargs["service"]
    assert isinstance(options, options_type)
    assert isinstance(service, service_type)
    assert (headless_arg in options.arguments) is headless
    if browser_name in {"chrome", "edge"}:
        assert "--window-size=1440,1000" in options.arguments
    if driver_path:
        assert service.path == driver_path
    driver.implicitly_wait.assert_called_once_with(0)
    driver.set_page_load_timeout.assert_called_once_with(37)

    assert browser.start() is driver
    factory.assert_called_once()
    browser.close()
    driver.quit.assert_called_once()
    assert browser.driver is None
