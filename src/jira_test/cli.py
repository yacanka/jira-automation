"""Command line entry points. Validation and catalog queries work without a Jira account."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from subprocess import run as launch_pytest

from selenium.common.exceptions import WebDriverException

from .browser import Browser
from .client import JiraClient
from .config import Config
from .errors import ApiError, ConfigurationError, JiraTestError, ScenarioError
from .explorer import Explorer
from .pytest_plugin import safe_error
from .report import write_catalog_report
from .scenario import load_scenarios
from .session import JiraSession
from .ui import JiraUI


def suite_files(path: Path) -> list[Path]:
    if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}:
        return [path]
    if path.is_dir():
        return sorted(p for p in path.rglob("*") if p.suffix.lower() in {".yaml", ".yml"})
    raise ScenarioError("Suite must be a YAML file or directory")


def validate_suite(path: Path) -> int:
    ids: set[str] = set()
    files = suite_files(path)
    if not files:
        raise ScenarioError("Suite contains no YAML scenarios")
    for file in files:
        for case in load_scenarios(file):
            if case.id in ids:
                raise ScenarioError("Duplicate scenario ID across suite files")
            ids.add(case.id)
    return len(ids)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="jira-test")
    commands = root.add_subparsers(dest="command", required=True)
    doctor = commands.add_parser("doctor", help="Validate credentials and Jira capabilities")
    doctor.add_argument("--config", default="config.local.yaml")
    doctor.add_argument("--api-only", action="store_true")
    explore = commands.add_parser("explore", help="Read-only project metadata and UI discovery")
    explore.add_argument("--config", default="config.local.yaml")
    explore.add_argument("--project")
    explore.add_argument("--api-only", action="store_true")
    explore.add_argument("--output", type=Path)
    query = commands.add_parser("query", help="Query recorded observations; missing means unknown")
    query.add_argument("--catalog", required=True, type=Path)
    for key in ("field", "issue-type", "screen", "source", "status", "transition"):
        query.add_argument("--" + key)
    validate = commands.add_parser("validate", help="Offline YAML syntax and schema checks")
    validate.add_argument("--suite", required=True, type=Path)
    run = commands.add_parser("run", help="Run a validated YAML suite using pytest")
    run.add_argument("--suite", required=True, type=Path)
    run.add_argument("--config")
    run.add_argument("--catalog", type=Path)
    run.add_argument("--test-project")
    run.add_argument("--junit", type=Path, default=Path("artifacts/junit.xml"))
    return root


def _doctor(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
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
        if not args.api_only:
            connection.live()
            checks["browser_auth"] = True
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return 0
    finally:
        connection.close()


def _explore(args: argparse.Namespace) -> int:
    config = Config.load(args.config)
    project = args.project or config.source_project
    if project not in {config.source_project, config.test_project}:
        raise ConfigurationError("Explore project must be configured as source or test project")
    config.require_credentials()
    client = JiraClient(config)
    browser = None
    ui = None
    try:
        if not args.api_only:
            browser = Browser(config)
            browser.login()
            ui = JiraUI(browser, client, readonly=True)
        try:
            client.current_user()
            catalog = Explorer(config, client).discover(project, ui)
        except ApiError as exc:
            if args.api_only or browser is None:
                raise
            from .ui_discovery import discover_ui_only

            catalog = discover_ui_only(config, browser, project)
            catalog.gaps.append({"reason": safe_error(exc), "source": "api"})
        output = args.output or Path(config.artifact_dir) / "explorer"
        write_catalog_report(catalog, output)
        print(
            json.dumps(
                {
                    "catalog": str(output / "catalog.json"),
                    "html": str(output / "catalog.html"),
                    "observations": len(catalog.observations),
                    "gaps": len(catalog.gaps),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        try:
            if browser:
                browser.close()
        finally:
            client.close()


def _query(args: argparse.Namespace) -> int:
    from .catalog import Catalog

    catalog = Catalog.load(args.catalog)
    filters = {
        key: getattr(args, key)
        for key in ("field", "issue_type", "screen", "source", "status", "transition")
    }
    results = catalog.query(**filters)
    print(
        json.dumps(
            {
                "state": "observed" if results else "unknown",
                "observations": [asdict(item) for item in results],
                "gaps": catalog.gaps,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _run(args: argparse.Namespace) -> int:
    validate_suite(args.suite)
    if args.test_project:
        if not args.config or Config.load(args.config).test_project != args.test_project:
            raise ConfigurationError("--test-project must match the configured test project")
    pytest_args = [
        str(args.suite),
        "--jira-suite",
        str(args.suite),
        "--tb=short",
        "--junitxml",
        str(args.junit),
    ]
    if args.config:
        pytest_args += ["--jira-config", args.config]
    if args.catalog:
        pytest_args += ["--jira-catalog", str(args.catalog)]
    args.junit.parent.mkdir(parents=True, exist_ok=True)
    return launch_pytest([sys.executable, "-m", "pytest", *pytest_args], check=False).returncode


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            print(f"Validated {validate_suite(args.suite)} scenario(s)")
            return 0
        return {"doctor": _doctor, "explore": _explore, "query": _query, "run": _run}[args.command](
            args
        )
    except (JiraTestError, WebDriverException) as exc:
        print(json.dumps({"error": safe_error(exc)}, ensure_ascii=False))
        return 2
