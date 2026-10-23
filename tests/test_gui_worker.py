import json
import time
from pathlib import Path

import pytest
import yaml

from jira_test.catalog import Catalog, Observation
from jira_test.gui.jobs import JobController
from jira_test.gui.worker import JobCancelled
from jira_test.runner import ScenarioRunner
from jira_test.scenario import validate


def complete(controller):
    deadline = time.monotonic() + 15
    events = []
    while controller.running and time.monotonic() < deadline:
        events.extend(controller.poll())
        time.sleep(0.02)
    events.extend(controller.poll())
    assert not controller.running
    return events


def catalog_case(identity="selected", required=True):
    return {
        "id": identity,
        "fixture": {"issue_type": "1", "catalog": "catalog.json"},
        "steps": [],
        "expect": [
            {
                "check": "catalog_required",
                "field": "summary",
                "screen": "create",
                "source": "api",
                "value": required,
            }
        ],
    }


def prepare_catalog(workspace):
    catalog = Catalog(project="SRC", user="configured-user")
    catalog.add(
        Observation(issue_type="1", screen="create", field="summary", source="api", required=True)
    )
    catalog.save(workspace / "catalog.json")


def test_yaml_selection_relative_catalog_no_accidental_python(tmp_path):
    prepare_catalog(tmp_path)
    suite = tmp_path / "cases.yaml"
    suite.write_text(yaml.safe_dump([catalog_case(), catalog_case("unselected", False)]))
    (tmp_path / "test_must_not_collect.py").write_text('raise RuntimeError("unselected Python")')
    controller = JobController(tmp_path)
    assert controller.start("run", {"yaml_cases": [{"path": str(suite), "id": "selected"}]})
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "completed", events
    reports = json.loads(Path(result["results"]).read_text())
    assert [r["id"] for r in reports["results"]] == ["selected"]
    assert reports["results"][0]["path"] == str(suite)
    assert any(e["data"].get("phase") == "expect" and e["data"]["position"] == 1 for e in events)


def test_mixed_tests_preserve_conftest_and_catalog_override(tmp_path):
    prepare_catalog(tmp_path)
    (tmp_path / "conftest.py").write_text(
        "import pytest\n@pytest.fixture\ndef workspace_value(): return 123\n"
    )
    test = tmp_path / "test_selected.py"
    test.write_text(
        "def test_chosen(workspace_value): assert workspace_value == 123\n"
        "def test_ignored(): assert False\n"
    )
    suite = tmp_path / "case.yaml"
    case = catalog_case()
    case["fixture"]["catalog"] = "missing.json"
    suite.write_text(yaml.safe_dump(case))
    controller = JobController(tmp_path)
    assert controller.start(
        "run",
        {
            "yaml_cases": [{"path": str(suite), "id": "selected"}],
            "python_tests": ["test_selected.py::test_chosen"],
            "catalog": str(tmp_path / "catalog.json"),
        },
    )
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "completed", events
    reports = json.loads(Path(result["results"]).read_text())
    assert {r["id"] for r in reports["results"]} == {"selected", "test_selected.py::test_chosen"}
    manifest = json.loads(Path(result["manifest"]).read_text())
    assert manifest["request"]["python_tests"] == ["test_selected.py::test_chosen"]
    assert manifest["source_hashes"][str(test)]
    assert manifest["python_snapshots"]
    snapshot = next(
        item["snapshot"] for item in manifest["python_snapshots"] if item["path"] == str(test)
    )
    assert Path(snapshot).read_text() == test.read_text()


def test_runner_cooperative_cancel_before_next_expectation(tmp_path):
    prepare_catalog(tmp_path)
    case = catalog_case()
    case["expect"].append(dict(case["expect"][0]))
    events = []

    def checkpoint():
        if any(e["phase"] == "expect" for e in events):
            raise JobCancelled("cancel")

    runner = ScenarioRunner(
        None, catalog=tmp_path / "catalog.json", event_sink=events.append, cancel_check=checkpoint
    )
    with pytest.raises(JobCancelled):
        runner.run(validate(case))
    assert len(runner.checks) == 1
    assert [e["position"] for e in events if e["phase"] == "expect"] == [1]


def test_yaml_catalog_is_snapshotted_and_teardown_failure_is_reported(tmp_path):
    prepare_catalog(tmp_path)
    (tmp_path / "conftest.py").write_text(
        "def pytest_runtest_teardown(item):\n"
        ' if item.name == "selected": raise RuntimeError("teardown failure")\n'
    )
    suite = tmp_path / "cases.yaml"
    suite.write_text(yaml.safe_dump(catalog_case()))
    controller = JobController(tmp_path)
    assert controller.start("run", {"yaml_cases": [{"path": str(suite), "id": "selected"}]})
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "failed"
    reports = json.loads(Path(result["results"]).read_text())
    assert reports["results"][0]["outcome"] == "failed"
    assert "teardown failure" in reports["results"][0]["reason"]
    manifest = json.loads(Path(result["manifest"]).read_text())
    snapshot = next(iter(manifest["snapshots"]))
    fixture_catalog = yaml.safe_load(Path(snapshot).read_text())[0]["fixture"]["catalog"]
    assert Path(fixture_catalog).is_relative_to(Path(result["run_dir"]))
    assert Path(fixture_catalog).read_text() == (tmp_path / "catalog.json").read_text()


def test_gui_selection_is_not_expanded_by_project_addopts(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = test_unselected.py\n")
    (tmp_path / "test_selected.py").write_text("def test_selected(): pass\n")
    (tmp_path / "test_unselected.py").write_text("def test_unselected(): assert False\n")
    controller = JobController(tmp_path)
    assert controller.start("run", {"python_tests": ["test_selected.py::test_selected"]})
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "completed", events
    reports = json.loads(Path(result["results"]).read_text())
    assert [row["id"] for row in reports["results"]] == ["test_selected.py::test_selected"]


def test_worker_loads_jira_plugin_when_pytest_autoload_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    prepare_catalog(tmp_path)
    suite = tmp_path / "cases.yaml"
    suite.write_text(yaml.safe_dump(catalog_case()))
    controller = JobController(tmp_path)
    assert controller.start("run", {"yaml_cases": [{"path": str(suite), "id": "selected"}]})
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "completed", events


def test_username_in_workspace_path_does_not_corrupt_catalog_or_artifact_paths(tmp_path):
    workspace = tmp_path / "alice"
    workspace.mkdir()
    prepare_catalog(workspace)
    suite = workspace / "cases.yaml"
    suite.write_text(yaml.safe_dump(catalog_case()))
    controller = JobController(workspace)
    assert controller.start(
        "run",
        {
            "yaml_cases": [{"path": str(suite), "id": "selected"}],
            "credentials": {"username": "alice", "password": "unrelated-secret"},
            "config": {
                "base_url": "https://jira.invalid",
                "source_project": "SRC",
                "test_project": "TST",
            },
        },
    )
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "completed", events
    assert Path(result["run_dir"]).is_dir()
    manifest = json.loads(Path(result["manifest"]).read_text())
    assert manifest["request"]["yaml_cases"][0]["path"] == str(suite)
    assert manifest["source_hashes"][str(suite)]
    for snapshot in manifest["snapshots"]:
        assert Path(snapshot).is_file()
        data = yaml.safe_load(Path(snapshot).read_text())
        assert Path(data[0]["fixture"]["catalog"]).is_file()


def test_skipped_python_preserves_junit_tuple_and_reports_skipped(tmp_path):
    (tmp_path / "test_skip.py").write_text(
        'import pytest\n@pytest.mark.skip(reason="unavailable")\n'
        'def test_skipped(): raise RuntimeError("must not execute")\n'
    )
    controller = JobController(tmp_path)
    assert controller.start("run", {"python_tests": ["test_skip.py"]})
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "completed", events
    reports = json.loads(Path(result["results"]).read_text())
    assert reports["results"][0]["outcome"] == "skipped"
    assert "<skipped" in Path(result["junit"]).read_text()


def test_yaml_rerun_retains_original_editor_source_path(tmp_path):
    prepare_catalog(tmp_path)
    original = tmp_path / "original.yaml"
    original.write_text(yaml.safe_dump(catalog_case()))
    prior_snapshot = tmp_path / "snapshot.yaml"
    prior_snapshot.write_text(original.read_text())
    controller = JobController(tmp_path)
    assert controller.start(
        "run",
        {
            "yaml_cases": [
                {"path": str(prior_snapshot), "id": "selected", "source_path": str(original)}
            ]
        },
    )
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    reports = json.loads(Path(result["results"]).read_text())
    assert reports["results"][0]["path"] == str(original)
    manifest = json.loads(Path(result["manifest"]).read_text())
    assert next(iter(manifest["snapshots"].values()))["path"] == str(original)


def test_secret_literal_is_rejected_instead_of_altering_assertion(tmp_path):
    prepare_catalog(tmp_path)
    suite = tmp_path / "case.yaml"
    case = catalog_case()
    case["description"] = "secret-literal-identity"
    suite.write_text(yaml.safe_dump(case))
    controller = JobController(tmp_path)
    assert controller.start(
        "run",
        {
            "yaml_cases": [{"path": str(suite), "id": "selected"}],
            "credentials": {"password": "secret-literal-identity"},
        },
    )
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "failed"
    assert any("credential text" in e["data"].get("message", "") for e in events)
    assert not any(e["data"].get("phase") == "test_start" for e in events)
    for path in Path(result["run_dir"]).rglob("*"):
        if path.is_file():
            assert "secret-literal-identity" not in path.read_text()


@pytest.mark.parametrize("teardown_failed", [False, True])
def test_yaml_blocked_remains_distinct_unless_teardown_fails(tmp_path, teardown_failed):
    Catalog(project="SRC", user="configured-user").save(tmp_path / "catalog.json")
    if teardown_failed:
        (tmp_path / "conftest.py").write_text(
            'def pytest_runtest_teardown(item): raise RuntimeError("teardown failure")\n'
        )
    suite = tmp_path / "blocked.yaml"
    suite.write_text(yaml.safe_dump(catalog_case()))
    controller = JobController(tmp_path)
    assert controller.start("run", {"yaml_cases": [{"path": str(suite), "id": "selected"}]})
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    reports = json.loads(Path(result["results"]).read_text())
    row = reports["results"][0]
    assert row["outcome"] == ("failed" if teardown_failed else "blocked")
    assert ("teardown failure" if teardown_failed else "No observation") in row["reason"]


def test_incidental_username_in_scenario_and_configuration_is_not_rejected(tmp_path):
    prepare_catalog(tmp_path)
    case = catalog_case("test_case")
    case["description"] = "test catalog metadata"
    suite = tmp_path / "test_case.yaml"
    suite.write_text(yaml.safe_dump(case))
    config = {
        "base_url": "https://jira.example.test",
        "source_project": "SRC",
        "test_project": "TST",
        "default_fields": {"summary": "test fixture"},
    }
    controller = JobController(tmp_path)
    assert controller.start(
        "run",
        {
            "yaml_cases": [{"path": str(suite), "id": "test_case"}],
            "config": config,
            "credentials": {"username": "test", "password": "unrelated-secret"},
        },
    )
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "completed", events
    manifest = json.loads(Path(result["manifest"]).read_text())
    assert manifest["request"]["config"] == config
    snapshot = next(iter(manifest["snapshots"]))
    assert yaml.safe_load(Path(snapshot).read_text())[0]["description"] == "test catalog metadata"


def test_optimized_worker_does_not_remove_yaml_expectations(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONOPTIMIZE", "1")
    prepare_catalog(tmp_path)
    suite = tmp_path / "incorrect.yaml"
    suite.write_text(yaml.safe_dump(catalog_case(required=False)))
    controller = JobController(tmp_path)
    assert controller.start("run", {"yaml_cases": [{"path": str(suite), "id": "selected"}]})
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["exitstatus"] == 1
    reports = json.loads(Path(result["results"]).read_text())
    assert reports["results"][0]["outcome"] == "failed"


@pytest.mark.parametrize(
    "failure", ["raise RuntimeError(value)", "pytest.skip(value, allow_module_level=True)"]
)
def test_collection_diagnostics_are_redacted_in_all_artifacts(tmp_path, failure):
    from uuid import uuid4

    sentinel = uuid4().hex
    (tmp_path / "test_import.py").write_text(
        "import os, pytest\nvalue = os.environ['JIRA_PASSWORD']\n" + failure + "\n"
    )
    controller = JobController(tmp_path)
    assert controller.start(
        "run", {"python_tests": ["test_import.py"], "credentials": {"password": sentinel}}
    )
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert Path(result["junit"]).is_file()
    assert sentinel not in json.dumps(events)
    for path in Path(result["run_dir"]).rglob("*"):
        if path.is_file():
            assert sentinel not in path.read_text(), path.name


def test_external_python_selection_and_failed_rerun(tmp_path):
    from jira_test.gui.rerun import rerun_request

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    source = external / "test_external.py"
    source.write_text(
        'import pytest\n@pytest.mark.parametrize("value", [0, 1], ids=["pass", "fail"])\n'
        "def test_external(value): assert value == 0\n"
    )
    controller = JobController(workspace)
    assert controller.start(
        "collect", {"paths": [str(source)], "credentials": {"username": "external"}}
    )
    events = complete(controller)
    collected = next(e["data"]["tests"] for e in events if e["type"] == "collected")
    chosen = next(item for item in collected if item["name"] == "test_external[fail]")
    selector = chosen.get("selector", chosen["nodeid"])
    assert controller.start("run", {"python_tests": [selector]})
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    report = json.loads(Path(result["results"]).read_text())
    assert len(report["results"]) == 1
    assert report["results"][0]["outcome"] == "failed"
    assert report["results"][0]["name"] == "test_external[fail]"
    request = rerun_request(json.loads(Path(result["manifest"]).read_text()), failed_only=True)
    assert request["python_tests"] == [str(source) + "::test_external[fail]"]


def test_external_files_with_same_test_name_keep_separate_results(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    passed = tmp_path / "test_external_pass.py"
    failed = tmp_path / "test_external_fail.py"
    passed.write_text("def test_same(): pass\n")
    failed.write_text("def test_same(): assert False\n")
    controller = JobController(workspace)
    assert controller.start("run", {"python_tests": [str(passed), str(failed)]})
    events = complete(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    report = json.loads(Path(result["results"]).read_text())
    assert {row["path"]: row["outcome"] for row in report["results"]} == {
        str(passed): "passed",
        str(failed): "failed",
    }
    assert len({row["id"] for row in report["results"]}) == 2
