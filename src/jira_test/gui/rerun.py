"""Reconstruct selected runs from immutable YAML snapshots and original Python tests."""

import hashlib
from pathlib import Path

from .storage import load_json


def changed_sources(manifest: dict) -> list[str]:
    changed = []
    for source, expected in manifest.get("source_hashes", {}).items():
        try:
            digest = hashlib.sha256(Path(source).read_bytes()).hexdigest()
        except OSError:
            digest = None
        if digest != expected:
            changed.append(source)
    return changed


def rerun_request(manifest: dict, failed_only: bool = False) -> dict:
    request = manifest.get("request", {})
    report = load_json(Path(manifest.get("results", "")), {}) or {}
    failures = [
        item for item in report.get("results", []) if item.get("outcome") in {"failed", "blocked"}
    ]
    if failed_only and not failures:
        raise ValueError("Başarısız test bulunamadı; eksik raporlarda tümünü çalıştırabilirsiniz.")
    yaml_cases = []
    for snapshot, original in manifest.get("snapshots", {}).items():
        for case_id in original.get("ids", []):
            if failed_only and not any(
                item.get("id") == case_id and item.get("path") == original.get("path")
                for item in failures
            ):
                continue
            if not Path(snapshot).is_file():
                raise ValueError("Kaydedilmiş senaryo kopyası bulunamadı: " + snapshot)
            yaml_cases.append(
                {"path": snapshot, "id": case_id, "source_path": original.get("path", snapshot)}
            )
    python_tests = [
        nodeid
        for nodeid in request.get("python_tests", [])
        if not failed_only
        or any(
            nodeid in {item.get("selector"), item.get("nodeid", item.get("id"))}
            for item in failures
        )
    ]
    if not yaml_cases and not python_tests:
        raise ValueError("Yeniden çalıştırılacak test bulunamadı.")
    return {
        "yaml_cases": yaml_cases,
        "python_tests": python_tests,
        "config": request.get("config", {}),
        "catalog": request.get("catalog"),
        "rerun_of": manifest.get("run_id"),
    }
