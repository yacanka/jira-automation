"""Collect safe YAML suites and expose jira_session to Python tests."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from playwright.sync_api import Error as PlaywrightError

from .config import Config
from .errors import ContextUnavailable, JiraTestError, ScenarioError, UnsupportedFieldError
from .outcomes import final_result
from .runner import ScenarioRunner
from .scenario import Scenario, load_scenarios
from .session import JiraSession

SESSION = pytest.StashKey[JiraSession]()
RESULTS = pytest.StashKey[list[dict]]()
IDS = pytest.StashKey[set[str]]()
# Optional observers leave CLI behavior unchanged.
EVENT_SINK = pytest.StashKey[Any]()
CANCEL_CHECK = pytest.StashKey[Any]()
ARTIFACT_DIR = pytest.StashKey[Path]()
REDACTOR = pytest.StashKey[Any]()
PHASE_REPORTS = pytest.StashKey[list[dict]]()
CANCELED = pytest.StashKey[Any]()


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
        observer = {
            "event_sink": self.config.stash.get(EVENT_SINK, None),
            "cancel_check": self.config.stash.get(CANCEL_CHECK, None),
        }
        try:
            if self.scenario.catalog_only:
                runner = ScenarioRunner(
                    None, catalog=Path(catalog) if catalog else None, **observer
                )
            else:
                session = get_session(self.config)
                client, ui = session.live()
                runner = ScenarioRunner(
                    session.config,
                    client,
                    ui,
                    Path(catalog) if catalog else None,
                    on_failure=lambda: evidence.update(capture_evidence(session)),
                    **observer,
                )
            result = runner.run(self.scenario)
        except (JiraTestError, AssertionError, PlaywrightError) as exc:
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
    except PlaywrightError:
        return {"evidence_error": "Browser screenshot unavailable"}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    data = {
        "when": report.when,
        "outcome": report.outcome,
        "longrepr": str(report.longrepr) if report.longrepr else "",
    }
    if report.failed and not isinstance(item, YamlItem):
        data.update(capture_evidence(item.config.stash.get(SESSION, None)))
    item.stash.setdefault(PHASE_REPORTS, []).append(data)


def execution_selector(item: pytest.Item) -> str:
    """An executable pytest selection, including for files outside rootdir."""
    _, separator, selection = item.nodeid.partition("::")
    return str(item.path.resolve()) + separator + selection


def test_identity(item: pytest.Item) -> str:
    if isinstance(item, YamlItem):
        return item.scenario.id
    if not item.path.resolve().is_relative_to(item.config.rootpath.resolve()):
        return execution_selector(item)
    return item.nodeid


def session_results(session: pytest.Session) -> list[dict]:
    config = session.config
    previous = {result["id"]: result for result in config.stash.get(RESULTS, [])}
    canceled = config.stash.get(CANCELED, lambda: False)()
    results = []
    for item in session.items:
        identity = test_identity(item)
        base = {
            **previous.get(identity, {}),
            "id": identity,
            "nodeid": item.nodeid,
            "selector": execution_selector(item),
        }
        results.append(final_result(base, item.stash.get(PHASE_REPORTS, []), canceled))
    return results


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    connection = config.stash.get(SESSION, None)
    try:
        if connection or config.getoption("--jira-suite") or ARTIFACT_DIR in config.stash:
            directory = config.stash.get(
                ARTIFACT_DIR, Path(connection.config.artifact_dir if connection else "artifacts")
            )
            directory.mkdir(parents=True, exist_ok=True)
            data = {
                "run_id": connection.client.run_id if connection and connection.client else None,
                "created_issues": connection.client.created_keys
                if connection and connection.client
                else [],
                "results": session_results(session),
                "pytest_exitstatus": int(exitstatus),
            }
            redactor = config.stash.get(REDACTOR, None)
            if redactor:
                data = redactor.data(data)
            (directory / "test-results.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    finally:
        if connection:
            connection.close()
