import json
import os
import subprocess
import sys
from pathlib import Path

from jira_test.cli import main


def test_validate_needs_no_credentials(tmp_path, capsys):
    case = tmp_path / "case.yaml"
    case.write_text(
        'id: offline\nfixture: {issue_type: "1", mode: none}\nsteps: []\nexpect:\n'
        "  - {check: catalog_exists, field: summary, screen: create, value: true}"
    )
    assert main(["validate", "--suite", str(case)]) == 0
    assert "1 scenario" in capsys.readouterr().out


def test_query_returns_unknown_not_false(tmp_path, capsys):
    from jira_test.catalog import Catalog

    path = tmp_path / "catalog.json"
    Catalog(project="SRC", user="offline").save(path)
    assert main(["query", "--catalog", str(path), "--field", "missing"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["state"] == "unknown"
    assert data["observations"] == []


def test_yaml_pytest_collection_and_execution(tmp_path):
    from jira_test.catalog import Catalog, Observation

    path = tmp_path / "catalog.json"
    catalog = Catalog(project="SRC", user="offline")
    catalog.add(Observation(issue_type="1", screen="create", field="summary", source="api"))
    catalog.save(path)
    case = tmp_path / "test.yaml"
    case.write_text(
        'id: offline\nfixture:\n  mode: none\n  issue_type: "1"\n'
        f"  catalog: {path}\nsteps: []\nexpect:\n"
        "  - {check: catalog_exists, field: summary, screen: create, value: true}"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(Path("src").resolve()),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "jira_test.pytest_plugin",
            "--jira-suite",
            str(case),
            str(case),
            "-q",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_offline_yaml_produces_json_report(tmp_path):
    from jira_test.catalog import Catalog, Observation

    path = tmp_path / "catalog.json"
    catalog = Catalog(project="SRC", user="offline")
    catalog.add(Observation(issue_type="1", screen="create", field="summary", source="api"))
    catalog.save(path)
    case = tmp_path / "test.yaml"
    case.write_text(
        'id: offline\nfixture:\n  mode: none\n  issue_type: "1"\n'
        f"  catalog: {path}\nsteps: []\nexpect:\n"
        "  - {check: catalog_exists, field: summary, screen: create, value: true}"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(Path("src").resolve()),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "jira_test.pytest_plugin",
            "--jira-suite",
            str(case),
            str(case),
            "-q",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads((tmp_path / "artifacts/test-results.json").read_text())
    assert data["results"][0]["outcome"] == "passed"
    assert data["created_issues"] == []


def test_run_launches_pytest_in_a_clean_process(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import jira_test.cli as cli

    case = tmp_path / "test.yaml"
    case.write_text(
        'id: offline\nfixture: {issue_type: "1", mode: none}\nsteps: []\nexpect:\n'
        "  - {check: catalog_exists, field: summary, screen: create, value: true}"
    )
    calls = []

    def launch(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli, "launch_pytest", launch)
    assert main(["run", "--suite", str(case), "--junit", str(tmp_path / "junit.xml")]) == 0
    assert calls[0][:3] == [sys.executable, "-m", "pytest"]
