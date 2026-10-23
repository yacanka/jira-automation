import json
import time
from pathlib import Path

from jira_test.gui.jobs import JobController


def finish(controller, timeout=15):
    events = []
    deadline = time.monotonic() + timeout
    while controller.running and time.monotonic() < deadline:
        events.extend(controller.poll())
        time.sleep(0.02)
    events.extend(controller.poll())
    assert not controller.running, events
    assert any(e["type"] == "finished" for e in events), events
    return events


def test_collect_uses_workspace_conftest_and_fresh_process(tmp_path):
    (tmp_path / "conftest.py").write_text(
        "import pytest\n@pytest.fixture\ndef local(): return 42\n"
    )
    test = tmp_path / "test_local.py"
    test.write_text("def test_local(local): assert local == 42\n")
    controller = JobController(tmp_path)
    assert controller.start("collect", {"paths": ["test_local.py"]})
    assert not controller.start("collect", {})
    events = finish(controller)
    collected = next(e["data"] for e in events if e["type"] == "collected")
    assert collected["tests"][0]["nodeid"] == "test_local.py::test_local"
    test.write_text("def test_changed(local): assert local == 42\n")
    assert controller.start("collect", {"paths": ["test_local.py"]})
    events = finish(controller)
    assert (
        next(e["data"] for e in events if e["type"] == "collected")["tests"][0]["name"]
        == "test_changed"
    )


def test_python_failure_reports_mask_credentials(tmp_path):
    (tmp_path / "test_failure.py").write_text(
        "import os\ndef test_bad():\n"
        ' print(os.environ["JIRA_USERNAME"])\n'
        ' assert False, os.environ["JIRA_PASSWORD"]\n'
    )
    controller = JobController(tmp_path)
    assert controller.start(
        "run",
        {
            "python_tests": ["test_failure.py::test_bad"],
            "credentials": {"username": "private-user-89", "password": "private-pass-92"},
        },
    )
    events = finish(controller)
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "failed"
    directory = Path(result["run_dir"])
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["outcome"] == "failed"
    assert Path(result["junit"]).exists()
    reports = json.loads(Path(result["results"]).read_text())
    assert any("AssertionError" in r.get("longrepr", "") for r in reports["reports"])
    for text in [json.dumps(events), *(p.read_text() for p in directory.rglob("*") if p.is_file())]:
        assert "private-user-89" not in text
        assert "private-pass-92" not in text


def test_cancel_stops_before_next_python_test(tmp_path):
    (tmp_path / "test_slow.py").write_text(
        "import time\ndef test_first(): time.sleep(0.5)\n"
        'def test_second(): assert False, "must not execute"\n'
    )
    controller = JobController(tmp_path)
    assert controller.start("run", {"python_tests": ["test_slow.py"]})
    deadline = time.monotonic() + 10
    events = []
    while time.monotonic() < deadline:
        batch = controller.poll()
        events.extend(batch)
        if any(e["type"] == "progress" and e["data"].get("phase") == "test_start" for e in batch):
            controller.cancel()
            break
        time.sleep(0.02)
    events.extend(finish(controller))
    result = next(e["data"] for e in events if e["type"] == "result")
    assert result["outcome"] == "canceled"
    assert not any(
        e["data"].get("nodeid", "").endswith("test_second")
        and e["data"].get("phase") == "test_start"
        for e in events
    )


def test_redaction_covers_python_repr_and_xml_escaped_secrets():
    from html import escape

    from jira_test.gui.storage import Redactor

    secret = 'line"one&\nline-two\\end'
    redactor = Redactor({"password": secret})
    for rendered in (
        secret,
        repr(secret)[1:-1],
        json.dumps(secret)[1:-1],
        escape(secret),
        escape(repr(secret)[1:-1]),
    ):
        assert redactor.text(rendered) == "[REDACTED]"


def test_redaction_preserves_protocol_schema_and_identity_values():
    from jira_test.gui.storage import Redactor

    event = {
        "type": "collected",
        "operation": "run",
        "data": {
            "tests": [{"kind": "python", "outcome": "passed", "nodeid": "test_run.py::test_run"}],
            "source_hashes": {"/workspace/test.py": "aaa123"},
            "run_id": "aaa123",
            "message": "user run connected",
        },
    }
    for username in ("run", "test", "a"):
        result = Redactor({"username": username}).data(event)
        assert result["type"] == "collected"
        assert result["operation"] == "run"
        assert result["data"]["tests"] == event["data"]["tests"]
        assert result["data"]["source_hashes"] == event["data"]["source_hashes"]
        assert result["data"]["run_id"] == "aaa123"
    assert "run" not in Redactor({"username": "run"}).data(event)["data"]["message"]
