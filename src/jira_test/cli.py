"""Command line entry points. Validation and catalog queries work without a Jira account."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from subprocess import run as launch_pytest

from playwright.sync_api import Error as PlaywrightError

from .config import Config
from .errors import ConfigurationError, JiraTestError, ScenarioError
from .pytest_plugin import safe_error
from .scenario import load_scenarios
from .services import doctor, explore


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
    gui = commands.add_parser("gui", help="Open the Tk desktop application")
    gui.add_argument("--workspace", type=Path, default=Path.cwd())
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
    checks = doctor(Config.load(args.config), api_only=args.api_only)
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0


def _explore(args: argparse.Namespace) -> int:
    result = explore(
        Config.load(args.config), project=args.project, api_only=args.api_only, output=args.output
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


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
        if args.command == "gui":
            from .gui.launch import launch

            return launch(args.workspace)
        if args.command == "validate":
            print(f"Validated {validate_suite(args.suite)} scenario(s)")
            return 0
        return {"doctor": _doctor, "explore": _explore, "query": _query, "run": _run}[args.command](
            args
        )
    except (JiraTestError, PlaywrightError) as exc:
        print(json.dumps({"error": safe_error(exc)}, ensure_ascii=False))
        return 2
