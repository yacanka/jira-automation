"""Playwright lifecycle and Jira username/password login with explicit waits."""

from collections.abc import Callable
from urllib.parse import urlsplit

from playwright.sync_api import Browser as PlaywrightBrowser
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .components import LocatorMap
from .config import Config
from .errors import ConfigurationError, WriteBoundaryError


class Browser:
    def __init__(self, config: Config, page: Page | None = None):
        self.config = config
        self.page = page
        self.locators = LocatorMap(config.locators)
        self._playwright: Playwright | None = None
        self._browser: PlaywrightBrowser | None = None
        self._context: BrowserContext | None = None

    def start(self) -> Page:
        if self.page is not None:
            return self.page
        try:
            self._playwright = sync_playwright().start()
            if self.config.browser == "firefox":
                self._browser = self._playwright.firefox.launch(headless=self.config.headless)
            else:
                channel = "chrome" if self.config.browser == "chrome" else "msedge"
                self._browser = self._playwright.chromium.launch(
                    channel=channel, headless=self.config.headless
                )
            self._context = self._browser.new_context(viewport={"width": 1440, "height": 1000})
            self.page = self._context.new_page()
            self.page.set_default_timeout(self.config.timeout * 1000)
            self.page.set_default_navigation_timeout(self.config.timeout * 1000)
            return self.page
        except Exception:
            self._close_after_failure()
            raise ConfigurationError("Cannot start browser; check browser installation") from None

    def login(self) -> Page:
        try:
            self.config.require_credentials()
            page = self.start()
            page.goto(self.config.base_url + "/login.jsp")
            self.assert_origin()
            username = self.locators.get("login.username", "#login-form-username")
            password = self.locators.get("login.password", "#login-form-password")
            submit = self.locators.get("login.submit", "#login-form-submit")
            page.locator(f"css={username}").fill(self.config.username)
            page.locator(f"css={password}").fill(self.config.password)
            page.locator(f"css={submit}").click()
            user_menu = self.locators.get("login.success", "#header-details-user-fullname")
            user = page.locator(f"css={user_menu}")
            user.wait_for(state="visible")
            self.assert_origin()
            actual = user.get_attribute("data-username")
            if actual and actual.casefold() != self.config.username.casefold():
                raise ConfigurationError("Browser session is authenticated as another Jira user")
            return page
        except (ConfigurationError, WriteBoundaryError):
            self._close_after_failure()
            raise
        except Exception:
            self._close_after_failure()
            raise ConfigurationError(
                "Browser login failed; check credentials and login selectors"
            ) from None

    def assert_origin(self) -> None:
        if self.page is None:
            raise ConfigurationError("Browser not started")
        expected = urlsplit(self.config.base_url)
        actual = urlsplit(self.page.url)
        if (actual.scheme, actual.netloc) != (expected.scheme, expected.netloc):
            raise WriteBoundaryError("Browser left the configured Jira origin")

    def _close_after_failure(self) -> None:
        try:
            self.close()
        except ConfigurationError:
            # Preserve the original startup/login failure after attempting all cleanup.
            pass

    def close(self) -> None:
        cleanup: list[Callable[[], None]] = []
        for resource in (self.page, self._context, self._browser):
            if resource is not None:
                cleanup.append(resource.close)
        if self._playwright is not None:
            cleanup.append(self._playwright.stop)
        self.page = None
        self._context = None
        self._browser = None
        self._playwright = None
        failed = False
        for close_resource in cleanup:
            try:
                close_resource()
            except Exception:
                failed = True
        if failed:
            raise ConfigurationError("Cannot close all browser resources") from None
