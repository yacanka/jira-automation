import pytest

from jira_test.gui.rerun import changed_sources, rerun_request
from jira_test.gui.storage import atomic_write_json


def test_rerun_uses_snapshot_and_only_failed_cases(tmp_path):
    snapshot = tmp_path / "snapshot.yaml"
    snapshot.write_text("[]")
    results = tmp_path / "test-results.json"
    atomic_write_json(
        results,
        {
            "results": [
                {"id": "bad", "kind": "yaml", "path": "/old/test.yaml", "outcome": "failed"},
                {"id": "ok", "kind": "yaml", "path": "/old/test.yaml", "outcome": "passed"},
                {"id": "test_x.py::test_bad", "kind": "python", "outcome": "failed"},
            ]
        },
    )
    manifest = {
        "request": {"config": {}, "python_tests": ["test_x.py::test_bad"]},
        "results": str(results),
        "snapshots": {str(snapshot): {"path": "/old/test.yaml", "ids": ["bad", "ok"]}},
    }
    payload = rerun_request(manifest, failed_only=True)
    assert payload["yaml_cases"] == [
        {"path": str(snapshot), "id": "bad", "source_path": "/old/test.yaml"}
    ]
    assert payload["python_tests"] == ["test_x.py::test_bad"]


def test_rerun_rejects_no_failure_and_missing_snapshot(tmp_path):
    manifest = {"request": {}, "snapshots": {str(tmp_path / "gone"): {"ids": ["test"]}}}
    with pytest.raises(ValueError, match="bulunamadı"):
        rerun_request(manifest)
    with pytest.raises(ValueError, match="Başarısız"):
        rerun_request({"request": {}}, failed_only=True)


def test_changed_sources_detects_missing_and_modified(tmp_path):
    source = tmp_path / "test_x.py"
    source.write_text("new")
    manifest = {"source_hashes": {str(source): "old", str(tmp_path / "missing.py"): "hash"}}
    assert set(changed_sources(manifest)) == {str(source), str(tmp_path / "missing.py")}
