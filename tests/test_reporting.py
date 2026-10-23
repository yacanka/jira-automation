import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


@pytest.mark.parametrize("frontend", ["cli", "gui"])
def test_all_collected_tests_have_final_phase_aware_results(tmp_path, frontend):
    (tmp_path / "test_phases.py").write_text(
        "import pytest\n"
        "@pytest.fixture\ndef broken_setup(): raise RuntimeError('setup problem')\n"
        "@pytest.fixture\ndef skipped_setup(): pytest.skip('not available')\n"
        "@pytest.fixture\ndef broken_teardown():\n"
        " yield\n raise RuntimeError('teardown problem')\n"
        "def test_pass(): pass\n"
        "def test_call_fail(): raise RuntimeError('call problem')\n"
        "def test_setup_fail(broken_setup): pass\n"
        "def test_setup_skip(skipped_setup): pass\n"
        "def test_teardown_fail(broken_teardown): pass\n"
    )
    (tmp_path / "conftest.py").write_text(
        "import pytest\ndef pytest_runtest_call(item):\n"
        " if item.name == 'crashed_yaml': raise RuntimeError('unexpected YAML problem')\n"
        "@pytest.hookimpl(hookwrapper=True)\ndef pytest_runtest_teardown(item):\n yield\n"
        " if item.name == 'teardown_yaml': raise RuntimeError('YAML teardown problem')\n"
    )
    from jira_test.catalog import Catalog, Observation

    catalog = tmp_path / "catalog.json"
    Catalog("SRC", "", observations=[Observation("1", "create", "summary", "api")]).save(catalog)
    suite = tmp_path / "cases.yaml"
    suite.write_text(
        yaml.safe_dump(
            [
                {
                    "id": identity,
                    "fixture": {"issue_type": "1", "catalog": str(catalog)},
                    "steps": [],
                    "expect": [
                        {
                            "check": "catalog_exists",
                            "field": "summary",
                            "screen": "create",
                            "value": True,
                        }
                    ],
                }
                for identity in ["crashed_yaml", "teardown_yaml"]
            ]
        )
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(Path("src").resolve()),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    if frontend == "cli":
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "jira_test.pytest_plugin",
            "--jira-suite",
            str(suite),
            str(suite),
            "test_phases.py",
            "-q",
        ]
        process = subprocess.run(
            command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
        )
        report_path = tmp_path / "artifacts" / "test-results.json"
    else:
        request = {
            "operation": "run",
            "workspace": str(tmp_path),
            "credentials": {},
            "python_tests": ["test_phases.py"],
            "yaml_cases": [
                {"path": str(suite), "id": identity}
                for identity in ["crashed_yaml", "teardown_yaml"]
            ],
        }
        process = subprocess.run(
            [sys.executable, "-m", "jira_test.gui.worker"],
            input=json.dumps(request) + "\n",
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        event = next(
            json.loads(line)["data"]
            for line in process.stdout.splitlines()
            if json.loads(line)["type"] == "result"
        )
        report_path = Path(event["results"])
    assert process.returncode == 1, process.stdout + process.stderr
    data = json.loads(report_path.read_text())
    results = {row["id"].rsplit("::", 1)[-1]: row for row in data["results"]}
    assert {name: row["outcome"] for name, row in results.items()} == {
        "test_pass": "passed",
        "test_call_fail": "failed",
        "test_setup_fail": "failed",
        "test_setup_skip": "skipped",
        "test_teardown_fail": "failed",
        "crashed_yaml": "failed",
        "teardown_yaml": "failed",
    }
    assert "teardown problem" in results["test_teardown_fail"]["reason"]
    assert "unexpected YAML problem" in results["crashed_yaml"]["reason"]
    assert "YAML teardown problem" in results["teardown_yaml"]["reason"]


@pytest.mark.parametrize("frontend", ["cli", "gui"])
def test_interrupted_teardown_never_leaves_a_passed_result(tmp_path, frontend):
    (tmp_path / "test_interrupt.py").write_text(
        "import pytest\n"
        "@pytest.fixture\ndef interrupted_teardown():\n"
        " yield\n pytest.exit('stop during teardown')\n"
        "def test_first(interrupted_teardown): pass\n"
        "def test_second(): pass\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(Path("src").resolve()),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    request = {
        "operation": "run",
        "workspace": str(tmp_path),
        "python_tests": ["test_interrupt.py"],
        "credentials": {},
    }
    command = (
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "jira_test.pytest_plugin",
            "--jira-suite",
            str(tmp_path),
            "test_interrupt.py",
            "-q",
        ]
        if frontend == "cli"
        else [sys.executable, "-m", "jira_test.gui.worker"]
    )
    process = subprocess.run(
        command,
        input=json.dumps(request) + "\n",
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 2
    if frontend == "cli":
        report_path = tmp_path / "artifacts" / "test-results.json"
    else:
        event = next(
            json.loads(line)["data"]
            for line in process.stdout.splitlines()
            if json.loads(line)["type"] == "result"
        )
        report_path = Path(event["results"])
    report = json.loads(report_path.read_text())
    assert [row["outcome"] for row in report["results"]] == ["incomplete", "incomplete"]
