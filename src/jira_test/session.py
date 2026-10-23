"""Lazy connection lifecycle shared by YAML and ordinary Python tests."""

from pathlib import Path

from .browser import Browser
from .client import JiraClient
from .components import FieldRegistry
from .config import Config
from .errors import ConfigurationError
from .ui import JiraUI


class JiraSession:
    def __init__(self, config: Config):
        self.config = config
        self.client: JiraClient | None = None
        self.browser: Browser | None = None
        self.ui: JiraUI | None = None
        self.registry = FieldRegistry()

    def api(self) -> JiraClient:
        if self.client is None:
            self.config.require_credentials()
            candidate = JiraClient(self.config)
            try:
                actual = candidate.current_user().get("name")
                if actual and actual.casefold() != self.config.username.casefold():
                    raise ConfigurationError("REST session is authenticated as another user")
            except Exception:
                candidate.close()
                raise
            self.client = candidate
        return self.client

    def live(self) -> tuple[JiraClient, JiraUI]:
        client = self.api()
        if self.ui is None:
            candidate = Browser(self.config)
            try:
                candidate.login()
                ui = JiraUI(candidate, client, registry=self.registry)
            except Exception:
                candidate.close()
                raise
            self.browser, self.ui = candidate, ui
        return client, self.ui

    def screenshot(self, name: str) -> Path | None:
        if not self.config.screenshots or self.browser is None or self.browser.page is None:
            return None
        directory = Path(self.config.artifact_dir) / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        # The filename is controlled internally, never derived from scenario IDs or issue values.
        path = directory / name
        self.browser.page.screenshot(path=str(path))
        return path

    def close(self) -> None:
        browser, client = self.browser, self.client
        self.browser, self.client, self.ui = None, None, None
        try:
            if browser:
                browser.close()
        finally:
            if client:
                client.close()
