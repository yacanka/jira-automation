"""Desktop integration and pure adapters for the auxiliary views (no Tk dependency)."""

import json
import os
import re
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from ..catalog import Observation
from ..config import Config
from ..errors import ConfigurationError


def open_path(path: Path) -> None:
    """Open an existing local artifact with the OS default handler, without a shell."""
    target = path.expanduser().resolve(strict=True)
    if sys.platform == "win32":
        os.startfile(str(target))
    else:
        command = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([command, str(target)], shell=False)


def open_source(path: Path) -> None:
    """Open source as text; never invoke an executable file association.

    Linux uses the first installed GUI editor from the explicit list below and
    reports an error when none is available instead of falling back to xdg-open.
    """
    target = path.expanduser().resolve(strict=True)
    if not target.is_file():
        raise ValueError("Kaynak dosyası seçilmelidir")
    if sys.platform == "win32":
        command = ["notepad.exe"]
    elif sys.platform == "darwin":
        command = ["open", "-t"]
    else:
        editors = ("gedit", "kate", "xed", "mousepad", "pluma", "leafpad", "code")
        editor = next((found for name in editors if (found := shutil.which(name))), None)
        if editor is None:
            raise OSError(
                "Metin düzenleyici bulunamadı. gedit, kate, xed, mousepad, pluma, "
                "leafpad veya code kurun; dosyayı düzenleyicinizde elle açabilirsiniz."
            )
        command = [editor]
    subprocess.Popen([*command, str(target)], shell=False)


def jira_issue_url(base_url: str, issue: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(char.isspace() for char in base_url)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*-[0-9]+", issue)
    ):
        raise ValueError("Jira bağlantısı geçerli bir HTTPS adresi ve kayıt anahtarı gerektirir")
    return base_url.rstrip("/") + "/browse/" + issue


def open_jira_issue(base_url: str, issue: str) -> None:
    webbrowser.open(jira_issue_url(base_url, issue), new=2)


def validate_profile(data: dict) -> dict:
    """Validate a profile without loading credentials from process environment."""
    if not isinstance(data, dict) or {"username", "password"} & data.keys():
        raise ConfigurationError("Profil eşleme olmalı; kullanıcı adı/parola içermemeli")
    try:
        config = Config(**data)
    except TypeError as exc:
        raise ConfigurationError("Eksik veya bilinmeyen profil ayarı") from exc
    result = asdict(config)
    result.pop("username")
    result.pop("password")
    return result


def observation_template(
    item: Observation, catalog_path: Path | None = None, expected_visible: bool | None = None
) -> dict:
    """Create a catalog assertion preserving context and unknown observation values."""
    context = {"field": item.field, "screen": item.screen, "source": item.source}
    for key in ("status", "transition"):
        if getattr(item, key) is not None:
            context[key] = getattr(item, key)
    # A UI observation with unknown visibility cannot safely become an exists assertion.
    exists = item.visible if item.source == "ui" else True
    if exists is None:
        if not isinstance(expected_visible, bool):
            raise ValueError("Görünürlük bilinmiyor; beklenen değeri açıkça seçin")
        exists = expected_visible
    checks = [{"check": "catalog_exists", **context, "value": exists}]
    if item.required is not None:
        checks.append({"check": "catalog_required", **context, "value": item.required})
    fixture = {"mode": "none", "issue_type": item.issue_type}
    if catalog_path is not None:
        fixture["catalog"] = str(catalog_path)
    description = f"Katalog gözlemi: {item.source}; örnek kayıt: {item.issue or 'bilinmiyor'}."
    if item.source == "ui" and item.visible is None:
        description += " Gözlemde görünürlük bilinmiyor; beklentiyi kullanıcı belirledi."
    return {
        "id": "catalog-" + item.field,
        "description": description,
        "fixture": fixture,
        "steps": [],
        "expect": checks,
    }


def read_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def read_run(directory: Path) -> dict:
    """Read partial journals/reports without treating missing evidence as a success."""
    manifest = read_json_object(directory / "manifest.json")
    report = read_json_object(directory / "test-results.json")
    if not report:
        report = read_json_object(directory / "artifacts" / "test-results.json")
    events = []
    journal_error = False
    try:
        with (directory / "events.jsonl").open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        events.append(event)
                except ValueError:
                    journal_error = True
    except (OSError, UnicodeError):
        journal_error = True
    results = report.get("results", [])
    results = (
        [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []
    )
    if not results:
        by_id: dict[str, dict] = {}
        for event in events:
            item = event.get("result", event.get("data"))
            if not isinstance(item, dict):
                continue
            if event.get("type") != "result" and not (
                event.get("type") == "progress" and item.get("phase") == "test_end"
            ):
                continue
            identity = item.get("scenario_id", item.get("id", item.get("nodeid")))
            if identity and by_id.get(identity, {}).get("outcome") != "failed":
                by_id[identity] = {
                    **item,
                    "id": identity,
                    "reason": item.get("reason", item.get("longrepr", "")),
                }
        results = list(by_id.values())
    terminal = next((e for e in reversed(events) if e.get("type") == "finished"), {})
    state = manifest.get("outcome", manifest.get("status", manifest.get("state")))
    if not state:
        state = "tamamlandı" if terminal else "eksik / bilinmiyor"
    artifact_complete = bool(report)
    if manifest.get("operation") == "explore":
        try:
            run_artifact(directory, manifest.get("catalog", ""))
            artifact_complete = True
        except (OSError, TypeError, ValueError):
            artifact_complete = False
    return {
        "directory": directory,
        "manifest": manifest,
        "report": report,
        "events": events,
        "results": results,
        "status": state,
        "incomplete": not artifact_complete or journal_error or not bool(terminal),
    }


def scan_runs(workspace: Path) -> list[dict]:
    root = workspace / ".jira-test-studio" / "runs"
    if not root.is_dir():
        return []
    runs = [read_run(path) for path in root.iterdir() if path.is_dir()]
    return sorted(runs, key=_run_started_at, reverse=True)


def _run_started_at(run: dict) -> tuple[float, str]:
    directory = run["directory"]
    try:
        started = datetime.fromisoformat(run["manifest"].get("started_at", ""))
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        timestamp = started.timestamp()
    except (TypeError, ValueError, OverflowError):
        timestamp = directory.stat().st_mtime
    return timestamp, directory.name


def redact_display(value: object, credentials: dict) -> str:
    secrets = [item for item in credentials.values() if isinstance(item, str) and item]

    def clean(item):
        if isinstance(item, dict):
            return {clean(str(key)): clean(val) for key, val in item.items()}
        if isinstance(item, (list, tuple)):
            return [clean(val) for val in item]
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[gizlendi]")
        return item

    return json.dumps(clean(value), ensure_ascii=False, indent=2, default=str)


def run_artifact(directory: Path, value: str) -> Path:
    """Resolve screenshot paths only within the selected run's artifact boundary."""
    path = Path(value)
    resolved = (path if path.is_absolute() else directory / path).resolve()
    if not resolved.is_relative_to(directory.resolve()):
        raise ValueError("Dosya bu çalıştırmanın klasörü dışında")
    if not resolved.is_file():
        raise ValueError("Dosya bulunamadı")
    return resolved
