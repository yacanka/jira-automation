"""Strict declarative scenarios: safe YAML, no executable expressions."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ScenarioError


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate keys instead of silently changing a test's meaning."""


def _mapping(loader: UniqueLoader, node: Any) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, (str, int)) or key in mapping:
            raise ScenarioError("Duplicate or invalid YAML mapping key")
        mapping[key] = loader.construct_object(value_node)
    return mapping


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)

ACTIONS = {
    "open": ({"screen", "transition"}, {"screen"}),
    "fill": ({"field", "value"}, {"field", "value"}),
    "clear": ({"field"}, {"field"}),
    "submit": (set(), set()),
    "transition": ({"id", "fields"}, {"id"}),
}
CHECKS = {
    "visible": ({"field", "value"}, {"field", "value"}),
    "editable": ({"field", "value"}, {"field", "value"}),
    "required": ({"field", "value"}, {"field", "value"}),
    "accepted": ({"value", "field", "error_contains"}, {"value"}),
    "persisted": ({"field", "value"}, {"field", "value"}),
    "status": ({"value"}, {"value"}),
    "catalog_exists": (
        {"field", "value", "screen", "source", "status", "transition"},
        {"field", "value", "screen"},
    ),
    "catalog_required": (
        {"field", "value", "screen", "source", "status", "transition"},
        {"field", "value", "screen", "source"},
    ),
    "catalog_options": (
        {"field", "contains", "screen", "source", "status", "transition"},
        {"field", "contains", "screen", "source"},
    ),
    "transition_available": ({"id", "value"}, {"id", "value"}),
}


@dataclass
class Scenario:
    id: str
    fixture: dict
    steps: list[dict]
    expect: list[dict]
    description: str = ""

    @property
    def catalog_only(self) -> bool:
        return not self.steps and all(e["check"].startswith("catalog_") for e in self.expect)


def _fail(message: str) -> None:
    raise ScenarioError(message)


def _identifier(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{name} must be a non-empty string; quote numeric IDs in YAML")


def _operations(items: Any, key: str, definitions: dict) -> None:
    if not isinstance(items, list):
        _fail(f"{key} entries must be a list")
    for item in items:
        if not isinstance(item, dict) or item.get(key) not in definitions:
            _fail(f"Unknown {key}")
        allowed, required = definitions[item[key]]
        if set(item) - (allowed | {key}) or required - set(item):
            _fail(f"Invalid keys for {item[key]}")
        for name in ("field", "id", "transition"):
            if name in item:
                _identifier(item[name], name)
        if "screen" in item and item["screen"] not in {"create", "view", "edit", "transition"}:
            _fail("Unknown screen")
        if "source" in item and item["source"] not in {"api", "ui"}:
            _fail("source must be api or ui")
        if item.get("action") == "open" and item["screen"] == "transition":
            _identifier(item.get("transition"), "transition")
        if "fields" in item and not isinstance(item["fields"], dict):
            _fail("fields must be a mapping")
        check = item.get("check", "")
        if check in {
            "visible",
            "editable",
            "required",
            "accepted",
            "catalog_exists",
            "catalog_required",
            "transition_available",
        }:
            if not isinstance(item["value"], bool):
                _fail(f"{check} expects a boolean value")
        if check == "accepted" and not item["value"] and not item.get("error_contains"):
            _fail("Rejected submissions require error_contains to identify the expected error")


def validate(data: Any) -> Scenario:
    if not isinstance(data, dict) or set(data) - {
        "id",
        "description",
        "fixture",
        "steps",
        "expect",
    }:
        _fail("Scenario must contain only id, description, fixture, steps and expect")
    if {"id", "fixture", "steps", "expect"} - set(data):
        _fail("Missing scenario sections")
    _identifier(data["id"], "id")
    fixture = data["fixture"]
    if not isinstance(fixture, dict) or set(fixture) - {
        "issue_type",
        "mode",
        "fields",
        "parent",
        "path",
        "catalog",
    }:
        _fail("Invalid fixture settings")
    _identifier(fixture.get("issue_type"), "issue_type")
    if fixture.get("mode", "new") not in {"new", "none"}:
        _fail("fixture.mode must be new or none")
    if not isinstance(fixture.get("fields", {}), dict):
        _fail("fixture.fields must be a mapping")
    if {"project", "parent", "issuetype"} & fixture.get("fields", {}).keys():
        _fail("Fixture project, parent and issue type are controlled by the runner")
    parent = fixture.get("parent")
    if parent is not None:
        if not isinstance(parent, dict) or set(parent) - {"issue_type", "fields"}:
            _fail("Invalid parent fixture")
        _identifier(parent.get("issue_type"), "parent.issue_type")
        if (
            not isinstance(parent.get("fields", {}), dict)
            or {"project", "parent", "issuetype"} & parent.get("fields", {}).keys()
        ):
            _fail("Invalid parent fields")
    path = fixture.get("path", [])
    if not isinstance(path, list):
        _fail("fixture.path must be a list")
    for hop in path:
        if not isinstance(hop, dict) or set(hop) - {"id", "fields", "status"}:
            _fail("Invalid fixture transition path")
        _identifier(hop.get("id"), "path.id")
        if not isinstance(hop.get("fields", {}), dict):
            _fail("path.fields must be a mapping")
    _operations(data["steps"], "action", ACTIONS)
    _operations(data["expect"], "check", CHECKS)
    _validate_order(data["steps"])
    if not data["expect"]:
        _fail("Every scenario must assert an expectation")
    if not isinstance(data.get("description", ""), str):
        _fail("description must be text")
    return Scenario(**data)


def load_scenarios(path: Path | str) -> list[Scenario]:
    try:
        data = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=UniqueLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise ScenarioError("Cannot read safe scenario YAML") from exc
    cases = data if isinstance(data, list) else [data]
    if not cases:
        _fail("Empty scenario suite")
    scenarios = [validate(case) for case in cases]
    if len({case.id for case in scenarios}) != len(scenarios):
        _fail("Scenario IDs must be unique within a suite")
    return scenarios


def _validate_order(steps: list[dict]) -> None:
    screen = None
    for step in steps:
        action = step["action"]
        if action == "open":
            screen = step["screen"]
        elif action == "transition":
            screen = None
        elif action in {"fill", "clear", "submit"}:
            if screen not in {"create", "edit", "transition"}:
                _fail("Open an editable form before fill, clear or submit")
            if action == "submit":
                screen = None
