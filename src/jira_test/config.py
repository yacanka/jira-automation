"""Non-secret YAML configuration; credentials come exclusively from the environment."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .errors import ConfigurationError


@dataclass
class Config:
    base_url: str
    source_project: str
    test_project: str
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    timeout: float = 20
    browser: str = "chrome"
    headless: bool = False
    verify_tls: bool | str = True
    artifact_dir: str = "artifacts"
    sample_limit: int = 100
    screenshots: bool = False
    locators: dict[str, str] = field(default_factory=dict)
    samples: dict[str, list[str]] = field(default_factory=dict)
    default_fields: dict = field(default_factory=dict)
    driver_path: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str):
            raise ConfigurationError("base_url must be a HTTPS URL")
        url = urlsplit(self.base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ConfigurationError("base_url must use HTTPS without embedded credentials")
        if url.query or url.fragment:
            raise ConfigurationError("base_url cannot contain query parameters or fragments")
        self.base_url = self.base_url.rstrip("/")
        for key in (self.source_project, self.test_project):
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
                raise ConfigurationError("Project keys must be Jira project keys")
        if self.source_project.upper() == self.test_project.upper():
            raise ConfigurationError("Source and test projects must be different")
        if self.browser not in {"chrome", "firefox"}:
            raise ConfigurationError("browser must be chrome or firefox")
        if not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            raise ConfigurationError("timeout must be positive")
        if not isinstance(self.sample_limit, int) or self.sample_limit < 1:
            raise ConfigurationError("sample_limit must be a positive integer")
        if self.verify_tls is False or not isinstance(self.verify_tls, (bool, str)):
            raise ConfigurationError("TLS verification cannot be disabled; provide a CA bundle")
        if isinstance(self.verify_tls, str) and not self.verify_tls.strip():
            raise ConfigurationError("CA bundle path cannot be empty")
        for value in (self.headless, self.screenshots):
            if not isinstance(value, bool):
                raise ConfigurationError("headless and screenshots must be booleans")
        if not isinstance(self.locators, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in self.locators.items()
        ):
            raise ConfigurationError("locators must map names to CSS selectors")
        if not isinstance(self.samples, dict) or not all(
            isinstance(k, str)
            and isinstance(v, list)
            and all(isinstance(issue, str) for issue in v)
            for k, v in self.samples.items()
        ):
            raise ConfigurationError("samples must map issue type IDs to issue key lists")
        if not isinstance(self.default_fields, dict):
            raise ConfigurationError("default_fields must be an API field mapping")
        if {"project", "parent", "issuetype"} & self.default_fields.keys():
            raise ConfigurationError("default_fields cannot override fixture identity")

    @classmethod
    def load(cls, path: Path | str) -> "Config":
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ConfigurationError("Cannot read configuration YAML") from exc
        if not isinstance(data, dict):
            raise ConfigurationError("Configuration must be a mapping")
        if {"username", "password"} & data.keys():
            raise ConfigurationError("Use JIRA_USERNAME and JIRA_PASSWORD environment variables")
        try:
            return cls(
                **data,
                username=os.environ.get("JIRA_USERNAME", ""),
                password=os.environ.get("JIRA_PASSWORD", ""),
            )
        except TypeError as exc:
            raise ConfigurationError("Missing or unknown configuration settings") from exc

    def require_credentials(self) -> None:
        if not self.username or not self.password:
            raise ConfigurationError("Set JIRA_USERNAME and JIRA_PASSWORD before connecting")
