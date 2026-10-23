"""Atomic local storage and credential redaction for Studio artifacts."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def list_runs(workspace: Path) -> list[dict]:
    records = []
    for path in sorted(
        (workspace / ".jira-test-studio" / "runs").glob("*/manifest.json"), reverse=True
    ):
        record = load_json(path)
        if isinstance(record, dict):
            records.append({**record, "run_dir": str(path.parent), "manifest": str(path)})
    return sorted(records, key=lambda item: item.get("started_at", ""), reverse=True)


class Redactor:
    """Mask literal credentials, including their JSON/XML escaped representations."""

    def __init__(self, credentials: dict):
        from html import escape

        self.password = credentials.get("password", "")
        self.secrets: set[str] = set()
        for value in credentials.values():
            if isinstance(value, str) and value:
                variants = {value, json.dumps(value)[1:-1], repr(value)[1:-1]}
                self.secrets.update(variants)
                self.secrets.update(escape(item) for item in variants)

    def text(self, value: str) -> str:
        for secret in sorted(self.secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        return value

    def data(self, value: Any, key: str = "") -> Any:
        # Paths and pytest identities are protocol data, not log text. Replacing a username
        # substring in /home/alice breaks the catalog, report links and rerun identities.
        identities = {
            "path",
            "source_path",
            "snapshot",
            "catalog",
            "junit",
            "results",
            "manifest",
            "run_dir",
            "suite",
            "events",
            "artifact_dir",
            "verify_tls",
            "original_catalog",
            "html",
            "screenshot",
            "nodeid",
            "selector",
            "python_tests",
            "paths",
            "type",
            "operation",
            "outcome",
            "phase",
            "kind",
            "when",
            "run_id",
            "id",
            "ids",
            "scenario_id",
            "name",
            "field",
            "check",
            "action",
            "source",
            "screen",
            "issue_type",
            "project",
            "source_project",
            "test_project",
            "browser",
            "base_url",
            "mode",
            "started_at",
            "finished_at",
            "created_at",
            "observed_at",
        }
        if key == "config":
            return Redactor({"password": self.password}).data(value)
        if key == "source_hashes":
            return value
        if key in identities and isinstance(value, str):
            return value
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {
                str(name): self.data(item, str(name))
                for name, item in value.items()
                if name not in {"username", "password", "credentials"}
            }
        if isinstance(value, (list, tuple)):
            return [self.data(item, key) for item in value]
        return value

    def snapshot(self, value: Any) -> Any:
        """Reject secret-bearing executable inputs rather than silently changing assertions."""
        # A username may legitimately be an issue assignee, domain segment or description.
        # Only authentication fields/password literals are forbidden in executable snapshots.
        if Redactor({"password": self.password}).data(value) != value:
            raise ValueError(
                "Saved test/configuration contains credential text; remove it before running"
            )
        return value
