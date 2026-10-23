"""Tk-free tests for GUI profile, catalog and history boundaries."""

import json
import os
from pathlib import Path

import pytest

from jira_test.catalog import Observation
from jira_test.errors import ConfigurationError
from jira_test.gui.platform import (
    jira_issue_url,
    observation_template,
    read_run,
    redact_display,
    run_artifact,
    scan_runs,
    validate_profile,
)


def test_profile_rejects_credentials_and_does_not_use_environment(monkeypatch):
    monkeypatch.setenv("JIRA_PASSWORD", "fixture-only-secret")
    values = {"base_url": "https://jira.invalid", "source_project": "SRC", "test_project": "TEST"}
    assert "password" not in validate_profile(values)
    with pytest.raises(ConfigurationError):
        validate_profile({**values, "password": "fixture-only-secret"})
    with pytest.raises(ConfigurationError):
        validate_profile({**values, "verify_tls": False})


def test_catalog_template_keeps_unknown_context_and_identity():
    item = Observation(
        "10001",
        "transition",
        "customfield_1",
        "ui",
        visible=None,
        required=False,
        status="Open",
        transition="31",
        issue="SRC-7",
    )
    with pytest.raises(ValueError, match="bilinmiyor"):
        observation_template(item, Path("catalog.json"))
    template = observation_template(item, Path("catalog.json"), expected_visible=True)
    check = template["expect"][0]
    assert check["value"] is True
    assert check["source"] == "ui"
    assert check["status"] == "Open"
    assert check["transition"] == "31"
    assert template["fixture"] == {"mode": "none", "issue_type": "10001", "catalog": "catalog.json"}
    assert template["expect"][1]["value"] is False
    assert "SRC-7" in template["description"]


def test_api_template_presence_does_not_use_unknown_ui_visibility():
    template = observation_template(Observation("10", "create", "summary", "api"))
    assert template["expect"][0]["value"] is True
    assert len(template["expect"]) == 1


def test_partial_history_journal_preserves_known_results(tmp_path):
    (tmp_path / "manifest.json").write_text('{"outcome":"canceled"}')
    (tmp_path / "events.jsonl").write_text(
        '{"type":"result","data":{"id":"one","outcome":"failed"}}\n{broken\n'
    )
    run = read_run(tmp_path)
    assert run["incomplete"]
    assert run["status"] == "canceled"
    assert run["results"] == [{"id": "one", "outcome": "failed", "reason": ""}]


def test_complete_run_and_corrupt_report(tmp_path):
    (tmp_path / "test-results.json").write_text(
        json.dumps({"results": [{"id": "one", "outcome": "passed"}, None]})
    )
    (tmp_path / "events.jsonl").write_text('{"type":"finished","data":{}}\n')
    run = read_run(tmp_path)
    assert not run["incomplete"]
    assert len(run["results"]) == 1
    (tmp_path / "test-results.json").write_text("[]")
    assert read_run(tmp_path)["incomplete"]
    assert scan_runs(tmp_path) == []


@pytest.mark.parametrize(
    "base,issue",
    [
        ("file:///tmp", "TEST-1"),
        ("https://user:pass@jira.invalid", "TEST-1"),
        ("https://jira.invalid?q=1", "TEST-1"),
        ("https://jira.invalid", "../TEST-1"),
        ("http://jira.invalid", "TEST-1"),
    ],
)
def test_jira_links_reject_unsafe_targets(base, issue):
    with pytest.raises(ValueError):
        jira_issue_url(base, issue)


def test_jira_context_path_and_artifact_boundary(tmp_path):
    assert jira_issue_url("https://jira.invalid/jira/", "TEST-12") == (
        "https://jira.invalid/jira/browse/TEST-12"
    )
    shot = tmp_path / "screenshot.png"
    shot.write_bytes(b"image")
    assert run_artifact(tmp_path, "screenshot.png") == shot
    with pytest.raises(ValueError):
        run_artifact(tmp_path, "../outside.png")
    assert "fixture-only-secret" not in redact_display(
        {"reason": "fixture-only-secret"}, {"password": "fixture-only-secret"}
    )


def test_python_journal_does_not_mislabel_overall_result_as_a_test(tmp_path):
    events = [
        {
            "type": "progress",
            "data": {
                "phase": "test_end",
                "nodeid": "test_x.py::test_x",
                "outcome": "failed",
                "longrepr": "assertion failed",
            },
        },
        {"type": "result", "data": {"outcome": "failed", "exitstatus": 1}},
        {"type": "finished", "data": {"outcome": "failed", "exitstatus": 1}},
    ]
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    results = read_run(tmp_path)["results"]
    assert len(results) == 1
    assert results[0]["id"] == "test_x.py::test_x"
    assert results[0]["reason"] == "assertion failed"


def test_masking_happens_before_json_escaping():
    secret = 'fixture-only-"quoted"'
    shown = redact_display({"error": secret}, {"password": secret})
    assert json.loads(shown)["error"] == "[gizlendi]"


@pytest.mark.parametrize(
    "catalog_exists,journal,incomplete",
    [
        (True, '{"type":"finished","data":{"outcome":"completed"}}\n', False),
        (False, '{"type":"finished","data":{"outcome":"completed"}}\n', True),
        (True, "", True),
        (True, '{broken\n{"type":"finished","data":{"outcome":"completed"}}\n', True),
    ],
)
def test_explore_history_uses_catalog_instead_of_test_report(
    tmp_path, catalog_exists, journal, incomplete
):
    catalog_path = tmp_path / "explorer" / "catalog.json"
    if catalog_exists:
        catalog_path.parent.mkdir()
        catalog_path.write_text('{"version":1}')
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "operation": "explore",
                "outcome": "completed",
                "catalog": str(catalog_path),
            }
        )
    )
    (tmp_path / "events.jsonl").write_text(journal)
    run = read_run(tmp_path)
    assert run["incomplete"] is incomplete
    assert run["results"] == []
    assert run["status"] == "completed"


def test_history_orders_same_second_runs_by_start_time_not_random_suffix(tmp_path):
    root = tmp_path / ".jira-test-studio" / "runs"
    for name, started in (
        ("20261021T120000-zzzz", "2026-10-21T12:00:00.100000+00:00"),
        ("20261021T120000-aaaa", "2026-10-21T12:00:00.900000+00:00"),
    ):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps({"started_at": started}))
    assert [run["directory"].name for run in scan_runs(tmp_path)] == [
        "20261021T120000-aaaa",
        "20261021T120000-zzzz",
    ]


@pytest.mark.parametrize(
    "system,expected",
    [
        ("win32", ["notepad.exe"]),
        ("darwin", ["open", "-t"]),
        ("linux", ["/usr/bin/kate"]),
    ],
)
def test_open_source_selects_editor_without_executing_python(
    tmp_path, monkeypatch, system, expected
):
    from jira_test.gui import platform

    path = tmp_path / "source with spaces.py"
    path.write_text("raise RuntimeError('must not execute')")
    calls = []
    monkeypatch.setattr(platform.sys, "platform", system)
    monkeypatch.setattr(platform.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    monkeypatch.setattr(
        platform.shutil, "which", lambda name: "/usr/bin/kate" if name == "kate" else None
    )
    platform.open_source(path)
    assert calls == [(expected + [str(path.resolve())], {"shell": False})]


def test_linux_without_editor_reports_error_instead_of_executing_source(tmp_path, monkeypatch):
    from jira_test.gui import platform

    path = tmp_path / "source.py"
    path.write_text("raise RuntimeError('must not execute')")
    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.setattr(platform.shutil, "which", lambda name: None)
    with pytest.raises(OSError, match="düzenleyici"):
        platform.open_source(path)


def test_history_with_missing_or_invalid_start_uses_directory_timestamp(tmp_path):
    root = tmp_path / ".jira-test-studio" / "runs"
    for name, manifest, timestamp in (
        ("older", {}, 100),
        ("newer", {"started_at": "invalid"}, 200),
    ):
        directory = root / name
        directory.mkdir(parents=True)
        (directory / "manifest.json").write_text(json.dumps(manifest))
        os.utime(directory, (timestamp, timestamp))
    assert [run["directory"].name for run in scan_runs(tmp_path)] == ["newer", "older"]
