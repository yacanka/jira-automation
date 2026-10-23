"""Tk-independent scenario editing with transactional parsing and atomic saves."""

import json
import math
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from ..errors import ScenarioError
from ..scenario import UniqueLoader, validate


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Tekrarlanan anahtar: {key}")
        result[key] = value
    return result


def parse_typed_value(kind: str, text: str) -> Any:
    """Parse an explicit type; identifiers/text never undergo YAML coercion."""
    if kind == "str":
        return text
    if kind == "null":
        if text.strip() not in {"", "null"}:
            raise ValueError("Boş değer için metni temizleyin veya null yazın.")
        return None
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (ValueError, TypeError) as exc:
        raise ValueError("Seçilen tür için geçerli JSON girin.") from exc
    expected: dict[str, type | tuple[type, ...]] = {
        "number": (int, float),
        "bool": bool,
        "list": list,
        "object": dict,
    }
    if kind not in expected or not isinstance(value, expected[kind]):
        raise ValueError("Değer seçilen tür ile eşleşmiyor.")
    if kind == "number" and (
        isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value))
    ):
        raise ValueError("Sonlu bir sayı girin.")
    return value


def value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return "str"


def _validate_cases(cases: list[dict]) -> None:
    if not cases:
        raise ScenarioError("En az bir senaryo gerekli.")
    validated = [validate(case) for case in cases]
    if len({case.id for case in validated}) != len(cases):
        raise ScenarioError("Senaryo kimlikleri dosya içinde benzersiz olmalı.")


def _parse(text: str) -> tuple[list[dict], bool]:
    try:
        parsed = yaml.load(text, Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise ScenarioError(f"Geçersiz YAML: {exc}") from exc
    suite = isinstance(parsed, list)
    cases = parsed if suite else [parsed]
    _validate_cases(cases)
    return cases, suite


class ScenarioDocument:
    """Keep the last valid model separate from the raw, possibly invalid draft."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self.cases: list[dict] = []
        self.text = ""
        self.yaml_draft = ""
        self._saved_text = ""
        self._suite = False
        self.visual_rewritten = False

    @property
    def dirty(self) -> bool:
        return self.yaml_draft != self._saved_text or self.text != self._saved_text

    def load(self, path: Path) -> None:
        text = path.read_bytes().decode("utf-8")
        cases, suite = _parse(text)
        self._loaded(text, cases, suite, path)

    def load_text(self, text: str) -> None:
        cases, suite = _parse(text)
        self._loaded(text, cases, suite, None)

    def _loaded(self, text: str, cases: list[dict], suite: bool, path: Path | None) -> None:
        self.cases = cases
        self._suite = suite
        self.path = path
        self.text = self.yaml_draft = self._saved_text = text
        self.visual_rewritten = False

    def apply_yaml(self, text: str) -> None:
        self.yaml_draft = text
        cases, suite = _parse(text)
        self.cases, self._suite = cases, suite
        self.text = text
        self.visual_rewritten = False

    def validate(self) -> None:
        _validate_cases(self.cases)

    def replace_cases(self, cases: list[dict]) -> None:
        candidate = deepcopy(cases)
        _validate_cases(candidate)
        suite = self._suite or len(candidate) > 1
        text = yaml.safe_dump(
            candidate if suite else candidate[0],
            allow_unicode=True,
            sort_keys=False,
        )
        self.cases, self._suite = candidate, suite
        self.text = self.yaml_draft = text
        self.visual_rewritten = True

    def set_case(self, index: int, case: dict) -> None:
        cases = deepcopy(self.cases)
        cases[index] = deepcopy(case)
        self.replace_cases(cases)

    def add_case(self, case: dict) -> int:
        cases = deepcopy(self.cases)
        new = deepcopy(case)
        identifiers = {item["id"] for item in cases}
        base = new["id"]
        suffix = "-copy"
        count = 2
        while new["id"] in identifiers:
            new["id"] = base + suffix
            suffix = f"-copy-{count}"
            count += 1
        cases.append(new)
        self.replace_cases(cases)
        return len(cases) - 1

    def remove_case(self, index: int) -> None:
        cases = deepcopy(self.cases)
        del cases[index]
        self.replace_cases(cases)

    def copy_operation(self, case_index: int, section: str, index: int) -> None:
        case = deepcopy(self.cases[case_index])
        case[section].insert(index + 1, deepcopy(case[section][index]))
        self.set_case(case_index, case)

    def move_operation(self, case_index: int, section: str, index: int, delta: int) -> None:
        case = deepcopy(self.cases[case_index])
        target = index + delta
        if 0 <= target < len(case[section]):
            case[section].insert(target, case[section].pop(index))
            self.set_case(case_index, case)

    def save(self, path: Path | None = None) -> None:
        """Save only a valid draft, replacing the destination atomically."""
        target = path or self.path
        if target is None:
            raise ValueError("Kaydetmek için dosya seçin.")
        self.apply_yaml(self.yaml_draft)
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(self.text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.path = target
        self._saved_text = self.text
