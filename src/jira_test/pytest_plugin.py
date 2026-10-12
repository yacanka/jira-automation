"""Collect safe YAML suites and expose jira_session to Python tests."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from selenium.common.exceptions import WebDriverException

from .config import Config
from .errors import ContextUnavailable, JiraTestError, ScenarioError, UnsupportedFieldError
from .runner import ScenarioRunner
from .scenario import Scenario, load_scenarios
from .session import JiraSession

SESSION = pytest.StashKey[JiraSession]()
RESULTS = pytest.StashKey[list[dict]]()
IDS = pytest.StashKey[set[str]]()


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("jira")
    group.addoption("--jira-suite", help="Collect YAML files only inside this suite path")
    group.addoption("--jira-config", help="Non-secret Jira configuration YAML")
    group.addoption("--jira-catalog", help="Override catalog path for catalog assertions")


def pytest_configure(config: pytest.Config) -> None:
    config.stash[RESULTS] = []
    config.stash[IDS] = set()


def get_session(config: pytest.Config) -> JiraSession:
    if SESSION not in config.stash:
        path = config.getoption("--jira-config")
        if not path:
            raise ContextUnavailable(
                "Live test needs --jira-config; no Jira connection was attempted"
            )
        config.stash[SESSION] = JiraSession(Config.load(path))
    return config.stash[SESSION]


@pytest.fixture(scope="session")
def jira_session(request: pytest.FixtureRequest) -> JiraSession:
    """Lazy session: call .live() for client/UI; .registry.register() before connecting."""
    return get_session(request.config)


def pytest_collect_file(file_path: Path, parent: pytest.Collector) -> Any:
    suite = parent.config.getoption("--jira-suite")
    if not suite or file_path.suffix.lower() not in {".yaml", ".yml"}:
        return None
    path = Path(suite).resolve()
    if file_path.resolve() == path or (path.is_dir() and file_path.resolve().is_relative_to(path)):
        return YamlFile.from_parent(parent, path=file_path)
    return None


class YamlFile(pytest.File):
    def collect(self):
        for case in load_scenarios(self.path):
            ids = self.config.stash[IDS]
            if case.id in ids:
                raise ScenarioError("Scenario IDs must be unique across the collected suite")
            ids.add(case.id)
            yield YamlItem.from_parent(self, name=case.id, scenario=case)


class YamlItem(pytest.Item):
    def __init__(self, *, scenario: Scenario, **kwargs: Any):
        super().__init__(**kwargs)
        self.scenario = scenario

    def runtest(self) -> None:
        catalog = self.config.getoption("--jira-catalog")
        session = None
        runner = None
        evidence: dict = {}
        try:
            if self.scenario.catalog_only:
                runner = ScenarioRunner(None, catalog=Path(catalog) if catalog else None)
            else:
                session = get_session(self.config)
                client, ui = session.live()
                runner = ScenarioRunner(
                    session.config,
                    client,
                    ui,
                    Path(catalog) if catalog else None,
                    on_failure=lambda: evidence.update(capture_evidence(session)),
                )
            result = runner.run(self.scenario)
        except (JiraTestError, AssertionError, WebDriverException) as exc:
            blocked = isinstance(exc, (ContextUnavailable, UnsupportedFieldError))
            result = {
                "id": self.scenario.id,
                "outcome": "blocked" if blocked else "failed",
                "reason": safe_error(exc),
                "issue": runner.issue_key if runner else None,
            }
            if session and not evidence:
                evidence.update(capture_evidence(session))
            result.update(evidence)
            self.config.stash[RESULTS].append(result)
            pytest.fail(result["outcome"] + ": " + result["reason"], pytrace=False)
        self.config.stash[RESULTS].append(result)

    def reportinfo(self):
        return self.path, 0, self.name


def safe_error(exc: Exception) -> str:
    if isinstance(exc, (JiraTestError, AssertionError)):
        return str(exc)
    return type(exc).__name__ + "; check browser connectivity, locators and timeouts"


def capture_evidence(session: JiraSession | None) -> dict:
    if session is None:
        return {}
    try:
        path = session.screenshot(uuid4().hex + ".png")
        return {"screenshot": str(path)} if path else {}
    except WebDriverException:
        return {"evidence_error": "Browser screenshot unavailable"}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    if isinstance(item, YamlItem) or SESSION not in item.config.stash:
        return
    if report.when == "call" or (report.when == "setup" and report.failed):
        result = {"id": item.nodeid, "outcome": report.outcome}
        if report.failed:
            result.update(capture_evidence(item.config.stash[SESSION]))
        item.config.stash[RESULTS].append(result)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    connection = config.stash.get(SESSION, None)
    try:
        if connection or config.getoption("--jira-suite"):
            directory = Path(connection.config.artifact_dir if connection else "artifacts")
            directory.mkdir(parents=True, exist_ok=True)
            data = {
                "run_id": connection.client.run_id if connection and connection.client else None,
                "created_issues": connection.client.created_keys
                if connection and connection.client
                else [],
                "results": config.stash.get(RESULTS, []),
                "pytest_exitstatus": int(exitstatus),
            }
            (directory / "test-results.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    finally:
        if connection:
            connection.close()
