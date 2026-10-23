"""Reusable connection diagnostics and read-only discovery for CLI and desktop clients."""

from collections.abc import Callable
from pathlib import Path

from .browser import Browser
from .client import JiraClient
from .config import Config
from .errors import ApiError, ConfigurationError
from .explorer import Explorer
from .pytest_plugin import safe_error
from .report import write_catalog_report
from .session import JiraSession
from .ui import JiraUI


def doctor(config: Config, api_only: bool = False) -> dict:
    connection = JiraSession(config)
    try:
        client = connection.api()
        info = client.server_info()
        checks: dict = {
            "version": info.get("version"),
            "rest_auth": True,
            "source_project": client.project(config.source_project)["key"],
            "test_project": client.project(config.test_project)["key"],
            "create_metadata": bool(client.issue_types(config.test_project)),
        }
        permissions = client.permissions(config.test_project).get("permissions", {})
        checks["permissions"] = {
            key: value.get("havePermission", False) for key, value in permissions.items()
        }
        if not api_only:
            connection.live()
            checks["browser_auth"] = True
        return checks
    finally:
        connection.close()


def explore(
    config: Config,
    project: str | None = None,
    api_only: bool = False,
    output: Path | None = None,
    event_sink: Callable[[dict], None] | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> dict:
    project = project or config.source_project
    if project not in {config.source_project, config.test_project}:
        raise ConfigurationError("Explore project must be configured as source or test project")
    config.require_credentials()
    client = JiraClient(config)
    browser = None
    ui = None
    try:
        if cancel_check:
            cancel_check()
        if not api_only:
            browser = Browser(config)
            browser.login()
            ui = JiraUI(browser, client, readonly=True)
        try:
            client.current_user()
            catalog = Explorer(config, client, event_sink, cancel_check).discover(project, ui)
        except ApiError as exc:
            if api_only or browser is None:
                raise
            from .ui_discovery import discover_ui_only

            if cancel_check:
                cancel_check()
            catalog = discover_ui_only(config, browser, project)
            catalog.gaps.append({"reason": safe_error(exc), "source": "api"})
        if cancel_check:
            cancel_check()
        output = output or Path(config.artifact_dir) / "explorer"
        write_catalog_report(catalog, output)
        return {
            "catalog": str(output / "catalog.json"),
            "html": str(output / "catalog.html"),
            "observations": len(catalog.observations),
            "gaps": len(catalog.gaps),
        }
    finally:
        try:
            if browser:
                browser.close()
        finally:
            client.close()
