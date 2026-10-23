"""Fresh-process worker. Requests arrive on stdin; sanitized events leave as JSONL."""

import contextlib
import io
import json
import os
import sys
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from importlib.metadata import entry_points
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from .. import pytest_plugin
from ..config import Config
from ..scenario import load_scenarios
from ..services import doctor, explore
from .pytest_bridge import PytestObserver
from .storage import Redactor, atomic_write_json, atomic_write_text, load_json


class JobCancelled(Exception):
    """Cooperative cancellation never turns unfinished tests into passed tests."""


class EventLog(io.TextIOBase):
    def __init__(self, emit):
        self.emit = emit
        self.pending = ""

    def write(self, text):
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if line.strip():
                self.emit("log", {"message": line})
        return len(text)

    def flush(self):
        if self.pending.strip():
            self.emit("log", {"message": self.pending})
        self.pending = ""


class Worker:
    def __init__(self, request: dict, output):
        self.request = request
        self.operation = request["operation"]
        self.workspace = Path(request["workspace"]).resolve()
        self.credentials = request.get("credentials", {})
        self.redactor = Redactor(self.credentials)
        self.output = output
        self.canceled = threading.Event()
        self.lock = threading.Lock()
        self.run_dir: Path | None = None
        self.manifest: dict = {}

    def emit(self, kind: str, data: dict):
        event = self.redactor.data({"type": kind, "operation": self.operation, "data": data})
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with self.lock:
            self.output.write(line)
            self.output.flush()
            if self.run_dir:
                with (self.run_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(line)

    def checkpoint(self):
        if self.canceled.is_set():
            raise JobCancelled("Canceled by user; already issued writes are not rolled back")

    def commands(self):
        for line in sys.stdin:
            try:
                if json.loads(line).get("command") == "cancel":
                    self.canceled.set()
            except (ValueError, AttributeError):
                continue

    def _start_run(self):
        identity = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + "-" + uuid4().hex[:12]
        self.run_dir = self.workspace / ".jira-test-studio" / "runs" / identity
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.manifest = {
            "run_id": identity,
            "operation": self.operation,
            "started_at": datetime.now(UTC).isoformat(),
            "outcome": "incomplete",
            "run_dir": str(self.run_dir),
            "request": self.redactor.data(
                {
                    key: value
                    for key, value in self.request.items()
                    if key not in {"workspace", "operation"}
                }
            ),
            "results": str(self.run_dir / "test-results.json"),
            "junit": str(self.run_dir / "junit.xml"),
            "events": str(self.run_dir / "events.jsonl"),
            "source_hashes": {},
            "catalog_snapshots": [],
        }
        atomic_write_json(self.run_dir / "manifest.json", self.manifest)
        self.emit("progress", {"phase": "run_start", "run_dir": str(self.run_dir)})

    def _config(self) -> Config:
        settings = dict(self.request.get("config") or {})
        if {"username", "password", "credentials"} & settings.keys():
            raise ValueError("Credentials must be supplied separately from configuration")
        if self.run_dir:
            settings["artifact_dir"] = str(self.run_dir)
        return Config(
            **settings,
            username=self.credentials.get("username", ""),
            password=self.credentials.get("password", ""),
        )

    def _snapshot_catalog(self, path: Path) -> Path:
        assert self.run_dir is not None
        path = path.resolve()
        text = path.read_text(encoding="utf-8")
        self.manifest["source_hashes"][str(path)] = sha256(path.read_bytes()).hexdigest()
        name = sha256(str(path).encode()).hexdigest()[:16] + ".json"
        destination = self.run_dir / "snapshots" / "catalogs" / name
        catalog = json.loads(text)
        atomic_write_json(destination, self.redactor.snapshot(catalog))
        self.manifest["catalog_snapshots"].append({"path": str(path), "snapshot": str(destination)})
        return destination

    def _snapshots(self) -> tuple[list[str], dict]:
        assert self.run_dir is not None
        directory = self.run_dir / "snapshots"
        directory.mkdir()
        sources = {}
        arguments = []
        catalog = self.request.get("catalog")
        if catalog:
            original = (self.workspace / catalog).resolve()
            catalog = self._snapshot_catalog(original)
            self.manifest["original_catalog"] = str(original)
            self.manifest["request"]["catalog"] = str(catalog)
            arguments.extend(["--jira-catalog", str(catalog)])
        grouped: dict[Path, set[str]] = {}
        originals: dict[Path, Path] = {}
        for selected in self.request.get("yaml_cases", []):
            path = (self.workspace / selected["path"]).resolve()
            original = (self.workspace / selected.get("source_path", selected["path"])).resolve()
            if path in originals and originals[path] != original:
                raise ValueError("Selected cases in one snapshot must share their original source")
            originals[path] = original
            grouped.setdefault(path, set()).add(selected["id"])
        for index, (path, wanted) in enumerate(grouped.items()):
            self.checkpoint()
            self.manifest["source_hashes"][str(path)] = sha256(path.read_bytes()).hexdigest()
            scenarios = [scenario for scenario in load_scenarios(path) if scenario.id in wanted]
            for scenario in scenarios:
                fixture_catalog = scenario.fixture.get("catalog")
                if fixture_catalog and not catalog:
                    scenario.fixture["catalog"] = str(
                        self._snapshot_catalog(self.workspace / fixture_catalog)
                    )
            if {scenario.id for scenario in scenarios} != wanted:
                raise ValueError("A selected YAML scenario no longer exists in its source file")
            destination = directory / f"{index:04d}-{path.name}"
            # Resolve catalogs against the workspace before moving YAML into the run snapshot.
            atomic_write_text(
                destination,
                yaml.safe_dump(
                    self.redactor.snapshot([asdict(scenario) for scenario in scenarios]),
                    allow_unicode=True,
                ),
            )
            sources[str(destination)] = {"path": str(originals[path]), "ids": sorted(wanted)}
            arguments.append(str(destination))
        config = self.request.get("config")
        if config:
            settings = asdict(self._config())
            settings.pop("username")
            settings.pop("password")
            destination = directory / "config.yaml"
            atomic_write_text(
                destination, yaml.safe_dump(self.redactor.snapshot(settings), allow_unicode=True)
            )
            arguments.extend(["--jira-config", str(destination)])
        if grouped:
            arguments.extend(["--jira-suite", str(directory)])
        self.manifest["snapshots"] = sources
        self.manifest["suite"] = str(directory)
        atomic_write_json(self.run_dir / "manifest.json", self.manifest)
        return arguments, sources

    def _pytest(self, collect=False) -> dict:
        if collect:
            arguments = list(self.request.get("paths") or ["."])
            sources: dict = {}
            arguments.append("--collect-only")
        else:
            self._start_run()
            if not self.request.get("yaml_cases") and not self.request.get("python_tests"):
                raise ValueError("Select at least one YAML or Python test")
            arguments, sources = self._snapshots()
            arguments.extend(self.request.get("python_tests") or [])
            assert self.run_dir is not None
            arguments.extend(["--junitxml", str(self.run_dir / "junit.xml")])
        self.checkpoint()
        arguments.extend(
            [
                "--rootdir",
                str(self.workspace),
                "--capture=sys",
                "--tb=short",
                "-q",
                "-o",
                "addopts=",
                "-o",
                "cache_dir=" + str(self.workspace / ".jira-test-studio" / "cache"),
            ]
        )
        # Selection and process ownership are controlled by Studio, not ambient pytest flags.
        os.environ.pop("PYTEST_ADDOPTS", None)
        observer = PytestObserver(
            self.emit, self.checkpoint, self.canceled, self.redactor, self.run_dir, sources
        )
        plugins: list = [observer]
        if os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") or not any(
            ep.value == "jira_test.pytest_plugin" for ep in entry_points(group="pytest11")
        ):
            plugins.append(pytest_plugin)
        status = int(pytest.main(arguments, plugins=plugins))
        if self.run_dir:
            self.manifest["python_snapshots"] = observer.python_snapshots
            self.manifest["source_hashes"].update(observer.source_hashes)
        outcome = "canceled" if self.canceled.is_set() else "completed" if status == 0 else "failed"
        result = {"outcome": outcome, "exitstatus": status}
        if self.run_dir:
            result.update({key: self.manifest[key] for key in ("run_dir", "junit", "results")})
            result["manifest"] = str(self.run_dir / "manifest.json")
        return result

    def execute(self):
        os.chdir(self.workspace)
        for key in ("username", "password"):
            os.environ["JIRA_" + key.upper()] = self.credentials.get(key, "")
        threading.Thread(target=self.commands, daemon=True).start()
        result = {"outcome": "failed", "exitstatus": 1}
        logger = EventLog(self.emit)
        try:
            with contextlib.redirect_stdout(logger), contextlib.redirect_stderr(logger):
                self.checkpoint()
                if self.operation in {"run", "collect"}:
                    result = self._pytest(collect=self.operation == "collect")
                elif self.operation == "doctor":
                    data = doctor(self._config(), api_only=self.request.get("api_only", False))
                    self.checkpoint()
                    result = {"outcome": "completed", "exitstatus": 0, **data}
                elif self.operation == "explore":
                    self._start_run()
                    assert self.run_dir is not None
                    data = explore(
                        self._config(),
                        project=self.request.get("project"),
                        api_only=self.request.get("api_only", False),
                        output=self.run_dir / "explorer",
                        event_sink=lambda data: self.emit("progress", data),
                        cancel_check=self.checkpoint,
                    )
                    result = {
                        "outcome": "completed",
                        "exitstatus": 0,
                        **data,
                        "run_dir": str(self.run_dir),
                    }
                else:
                    raise ValueError("Unknown worker operation")
        except JobCancelled as exc:
            result = {"outcome": "canceled", "exitstatus": 2}
            self.emit("log", {"message": str(exc)})
        except Exception as exc:
            self.emit("error", {"message": self.redactor.text(str(exc)) or type(exc).__name__})
        finally:
            logger.flush()
            if self.run_dir:
                result.update(
                    {"run_dir": str(self.run_dir), "manifest": str(self.run_dir / "manifest.json")}
                )
                self.manifest.update(result)
                self.manifest["finished_at"] = datetime.now(UTC).isoformat()
                if self.operation == "run":
                    reports = load_json(self.run_dir / "test-results.json", {})
                    self.manifest["created_issues"] = reports.get("created_issues", [])
                atomic_write_json(self.run_dir / "manifest.json", self.redactor.data(self.manifest))
            self.emit("result", result)
            self.emit("finished", result)
        return result["exitstatus"]


def main():
    try:
        request = json.loads(sys.stdin.readline())
        return Worker(request, sys.stdout).execute()
    except Exception:
        # Malformed requests may contain credentials; never echo the request or exception.
        print(
            json.dumps(
                {
                    "type": "error",
                    "operation": "unknown",
                    "data": {"message": "Cannot initialize worker request"},
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
