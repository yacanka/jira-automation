"""Observe pytest in its dedicated worker, without a second pytest process."""

from hashlib import sha256
from pathlib import Path

import pytest

from .. import pytest_plugin
from .storage import atomic_write_json, atomic_write_text, load_json


class PytestObserver:
    def __init__(self, emit, checkpoint, canceled, redactor, run_dir=None, sources=None):
        self.emit = emit
        self.checkpoint = checkpoint
        self.canceled = canceled
        self.redactor = redactor
        self.run_dir = run_dir
        self.sources = sources or {}
        self.reports = []
        self.items = {}
        self.python_snapshots = []
        self.source_hashes = {}

    def pytest_configure(self, config):
        config.stash[pytest_plugin.EVENT_SINK] = lambda data: self.emit("progress", data)
        config.stash[pytest_plugin.CANCEL_CHECK] = self.checkpoint
        config.stash[pytest_plugin.REDACTOR] = self.redactor
        config.stash[pytest_plugin.CANCELED] = self.canceled.is_set
        if self.run_dir:
            config.stash[pytest_plugin.ARTIFACT_DIR] = self.run_dir

    def pytest_collection_finish(self, session):
        tests = []
        for item in session.items:
            source = self.sources.get(str(item.path), {})
            data = {
                "id": pytest_plugin.test_identity(item),
                "nodeid": item.nodeid,
                "path": source.get("path", str(item.path)),
                "name": item.name,
                "kind": "yaml" if isinstance(item, pytest_plugin.YamlItem) else "python",
            }
            if isinstance(item, pytest_plugin.YamlItem):
                data["scenario_id"] = item.scenario.id
            else:
                # Outside rootdir pytest may emit only ::test_name. Keep an executable path.
                data["selector"] = pytest_plugin.execution_selector(item)
            tests.append(data)
            self.items[pytest_plugin.execution_selector(item)] = data
        self.emit("collected", {"tests": tests, "count": len(tests)})
        if self.run_dir:
            self._snapshot_python(session)

    def _snapshot_python(self, session):
        paths = {Path(item["path"]) for item in self.items.values() if item["kind"] == "python"}
        for path in list(paths):
            for parent in (path.parent, *path.parent.parents):
                if not parent.is_relative_to(session.config.rootpath):
                    break
                conftest = parent / "conftest.py"
                if conftest.is_file():
                    paths.add(conftest)
        for index, path in enumerate(sorted(paths)):
            destination = self.run_dir / "snapshots" / "python" / f"{index:04d}-{path.name}"
            atomic_write_text(destination, self.redactor.text(path.read_text(encoding="utf-8")))
            self.python_snapshots.append({"path": str(path), "snapshot": str(destination)})
            self.source_hashes[str(path)] = sha256(path.read_bytes()).hexdigest()

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_protocol(self, item, nextitem):
        if self.canceled.is_set():
            pytest.exit("Canceled by user", returncode=2)
        self.emit(
            "progress",
            {
                "phase": "test_start",
                **self.items.get(pytest_plugin.execution_selector(item), {}),
                "nodeid": item.nodeid,
            },
        )

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        report.jira_test_item = self.items.get(pytest_plugin.execution_selector(item), {})
        self._redact_report(report)

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_make_collect_report(self, collector):
        outcome = yield
        # Collection reports go directly to JUnit, outside runtest_makereport.
        self._redact_report(outcome.get_result())

    def _redact_report(self, report):
        if isinstance(report.longrepr, tuple):
            report.longrepr = tuple(
                self.redactor.text(value) if isinstance(value, str) else value
                for value in report.longrepr
            )
        elif report.longrepr:
            report.longrepr = self.redactor.text(str(report.longrepr))
        report.sections = [(name, self.redactor.text(text)) for name, text in report.sections]
        if hasattr(report, "user_properties"):
            report.user_properties = self.redactor.data(report.user_properties)

    def pytest_runtest_logreport(self, report):
        data = {
            "nodeid": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "longrepr": str(report.longrepr) if report.longrepr else "",
            "duration": report.duration,
            **getattr(report, "jira_test_item", {}),
        }
        self.reports.append(data)
        if report.when == "call" or report.failed:
            self.emit("progress", {"phase": "test_end", **data})

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus):
        if not self.run_dir:
            return
        path = self.run_dir / "test-results.json"
        data = load_json(path, {})
        results = data.setdefault("results", [])
        for result in results:
            result.update(self.items.get(result.get("selector"), {}))
        data.update(
            {
                "reports": self.reports,
                "pytest_exitstatus": int(exitstatus),
                "outcome": "canceled"
                if self.canceled.is_set()
                else "completed"
                if exitstatus == 0
                else "failed",
            }
        )
        atomic_write_json(path, self.redactor.data(data))
