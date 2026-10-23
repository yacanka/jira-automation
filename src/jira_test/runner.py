"""Scenario execution: API fixture preparation, Playwright actions, persisted assertions."""

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from .catalog import Catalog
from .config import Config
from .errors import ContextUnavailable, ScenarioError
from .explorer import normalize_fields
from .scenario import Scenario
from .waiting import wait_until


def _expect(condition: bool, message: str) -> None:
    """Scenario expectations must also execute under python -O."""
    if not condition:
        raise AssertionError(message)


def matches(actual: Any, expected: Any) -> bool:
    """Mappings assert projections; lists preserve order and length recursively."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(matches(a, e) for a, e in zip(actual, expected, strict=True))
        )
    return actual == expected


class ScenarioRunner:
    def __init__(
        self,
        config: Config | None,
        client: Any = None,
        ui: Any = None,
        catalog: Path | None = None,
        on_failure: Callable[[], Any] | None = None,
        event_sink: Callable[[dict], None] | None = None,
        cancel_check: Callable[[], None] | None = None,
    ):
        self.config, self.client, self.ui = config, client, ui
        self.on_failure = on_failure
        self.event_sink = event_sink
        self.cancel_check = cancel_check
        self.catalog_path = catalog
        self.issue_key: str | None = None
        self.parent_key: str | None = None
        self.last_outcome: dict | None = None
        self.before: dict | None = None
        self.before_created: set[str] = set()
        self.touched_fields: set[str] = set()
        self.checks: list[dict] = []

    def _checkpoint(self, phase: str, scenario: Scenario, **data: Any) -> None:
        if self.cancel_check:
            self.cancel_check()
        if self.event_sink:
            self.event_sink({"phase": phase, "scenario_id": scenario.id, **data})

    def run(self, scenario: Scenario) -> dict:
        self._checkpoint("scenario_start", scenario)
        self.issue_key = self.parent_key = None
        self.last_outcome = self.before = None
        self.touched_fields, self.checks = set(), []
        if scenario.catalog_only:
            self._catalog_checks(scenario)
        else:
            self._live(scenario)
        return {
            "id": scenario.id,
            "outcome": "passed",
            "issue": self.issue_key,
            "parent": self.parent_key,
            "checks": self.checks,
        }

    def _live(self, scenario: Scenario) -> None:
        if scenario.fixture.get("mode", "new") == "none":
            forbidden = any(
                step["action"] == "transition"
                or (step["action"] == "open" and step["screen"] != "create")
                for step in scenario.steps
            )
            if forbidden:
                raise ScenarioError("A fixture-free scenario may only use the create screen")
        if self.config is None or self.client is None or self.ui is None:
            raise ContextUnavailable(
                "Live scenarios need configuration, REST API and browser access"
            )
        # Obtain metadata before allocating any records, exposing missing API capabilities early.
        normalize_fields(
            self.client.create_fields(self.config.test_project, scenario.fixture["issue_type"])
        )
        try:
            self._checkpoint("fixture", scenario)
            self._prepare(scenario)
            for position, step in enumerate(scenario.steps, 1):
                self._checkpoint(
                    "step",
                    scenario,
                    position=position,
                    total=len(scenario.steps),
                    action=step["action"],
                )
                self._step(step, scenario)
            self._catalog_checks(scenario)
        except Exception:
            if self.on_failure:
                self.on_failure()
            raise
        finally:
            self.ui.cancel()

    def _create_fixture(self, definition: dict, parent: str | None = None) -> str:
        assert self.config is not None
        fields = {
            **self.config.default_fields,
            **definition.get("fields", {}),
            "project": {"key": self.config.test_project},
            "issuetype": {"id": definition["issue_type"]},
        }
        fields.setdefault("summary", "scenario fixture")
        if parent:
            fields["parent"] = {"key": parent}
        elif "parent" in fields:
            raise ScenarioError("default_fields cannot specify a parent")
        return self.client.create_issue(fields)["key"]

    def _prepare(self, scenario: Scenario) -> None:
        parent = scenario.fixture.get("parent")
        if parent:
            self.parent_key = self._create_fixture(parent)
        if scenario.fixture.get("mode", "new") == "new":
            self.issue_key = self._create_fixture(scenario.fixture, self.parent_key)
            for hop in scenario.fixture.get("path", []):
                self._checkpoint("fixture_transition", scenario, transition=hop["id"])
                available = self.client.transitions(self.issue_key)
                if not any(str(t["id"]) == hop["id"] for t in available):
                    raise ContextUnavailable("Fixture transition path is unavailable")
                self.client.transition_issue(self.issue_key, hop["id"], hop.get("fields", {}))
                if "status" in hop:
                    self._wait_field("status", {"id": str(hop["status"])})

    def _open(self, step: dict, scenario: Scenario) -> None:
        assert self.config is not None
        screen = step["screen"]
        if screen == "create":
            # A new create form has no saved issue, even when a previous fixture exists.
            self.issue_key = None
            self.ui.metadata = normalize_fields(
                self.client.create_fields(self.config.test_project, scenario.fixture["issue_type"])
            )
        elif screen in {"edit", "view"}:
            self.ui.metadata = self.client.edit_fields(self.issue_key)
        else:
            choices = self.client.transitions(self.issue_key)
            match = next((t for t in choices if str(t["id"]) == step["transition"]), None)
            if match is None:
                raise ContextUnavailable("Requested transition is unavailable")
            self.ui.metadata = match.get("fields", {})
            if not match.get("hasScreen"):
                self._snapshot()
        self.ui.open(
            screen=screen,
            project=self.config.test_project,
            issue_type=scenario.fixture["issue_type"],
            issue=self.issue_key,
            transition=step.get("transition"),
            parent=self.parent_key,
        )
        if screen == "create":
            summary = self.client.summary(
                str(scenario.fixture.get("fields", {}).get("summary", scenario.id))
            )
            self.ui.fill("summary", summary)
            for field, value in {
                **self.config.default_fields,
                **scenario.fixture.get("fields", {}),
            }.items():
                if field != "summary":
                    self.ui.fill(field, value)

    def _snapshot(self) -> None:
        if self.issue_key:
            self.before = deepcopy(self.client.issue(self.issue_key)["fields"])
        else:
            self.before = None
            self.before_created = set(self.client.run_issue_keys())

    def _submit(self) -> None:
        if not getattr(self.ui, "immediate_outcome", None):
            self._snapshot()
        self.last_outcome = self.ui.submit()
        if self.last_outcome["accepted"] and self.last_outcome.get("key"):
            key = self.last_outcome["key"]
            if key != self.issue_key:
                self.client.register_created(key)
                self.issue_key = key

    def _step(self, step: dict, scenario: Scenario) -> None:
        action = step["action"]
        if action == "open":
            self._open(step, scenario)
        elif action in {"fill", "clear"}:
            self.touched_fields.add(step["field"])
            if action == "fill":
                value = step["value"]
                if step["field"] == "summary" and self.ui.screen == "create" and value:
                    value = self.client.summary(str(value))
                self.ui.fill(step["field"], value)
            else:
                self.ui.clear(step["field"])
        elif action == "submit":
            self._submit()
        elif action == "transition":
            choices = self.client.transitions(self.issue_key)
            choice = next((t for t in choices if str(t["id"]) == step["id"]), None)
            if choice and not choice.get("hasScreen") and step.get("fields"):
                raise ContextUnavailable("Cannot set fields on a screenless transition")
            self._open({"screen": "transition", "transition": step["id"]}, scenario)
            for field, value in step.get("fields", {}).items():
                self.ui.fill(field, value)
                self.touched_fields.add(field)
            self._submit()

    def _wait_field(self, field: str, expected: Any) -> None:
        if not self.issue_key:
            raise ContextUnavailable("Persisted checks need a saved issue")
        timeout = self.config.timeout if self.config else 20

        def persisted() -> bool:
            fields = self.client.issue(self.issue_key)["fields"]
            if field not in fields:
                raise ContextUnavailable(
                    f"Persisted field {field} is not present in the API response"
                )
            return matches(fields[field], expected)

        wait_until(
            persisted,
            timeout,
            message=f"Persisted field {field} did not reach the expected value",
        )

    def _check(self, expected: dict, scenario: Scenario) -> None:
        check = expected["check"]
        if check.startswith("catalog_"):
            self._catalog_check(expected, scenario)
        elif check in {"visible", "editable", "required"}:
            actual = getattr(self.ui, check)(expected["field"])
            _expect(
                actual is expected["value"], f"UI {check} assertion failed for {expected['field']}"
            )
        elif check == "accepted":
            self._accepted(expected)
        elif check in {"persisted", "status"}:
            field = "status" if check == "status" else expected["field"]
            value = {"id": str(expected["value"])} if check == "status" else expected["value"]
            self._wait_field(field, value)
        elif check == "transition_available":
            if not self.issue_key:
                raise ContextUnavailable("Transition availability needs an issue fixture")
            actual = any(
                str(t["id"]) == expected["id"] for t in self.client.transitions(self.issue_key)
            )
            _expect(actual is expected["value"], "Transition availability assertion failed")
        self.checks.append({"check": check, "outcome": "passed"})

    def _accepted(self, expected: dict) -> None:
        if self.last_outcome is None:
            raise ScenarioError("accepted checks require a preceding submit/transition")
        _expect(self.last_outcome["accepted"] is expected["value"], "Submission outcome mismatch")
        if expected["value"]:
            return
        errors = self.last_outcome.get("errors", {})
        message = (
            errors.get(expected["field"], "")
            if expected.get("field")
            else " ".join(errors.values())
        )
        _expect(
            expected["error_contains"].casefold() in message.casefold(),
            "Expected validation error was not observed",
        )
        if self.issue_key:
            actual = self.client.issue(self.issue_key)["fields"]
            _expect(actual == self.before, "Issue changed despite expected rejection")
        else:
            _expect(
                set(self.client.run_issue_keys()) == self.before_created,
                "Issue was created despite expected rejection",
            )

    def _catalog_checks(self, scenario: Scenario) -> None:
        for position, expected in enumerate(scenario.expect, 1):
            self._checkpoint(
                "expect",
                scenario,
                position=position,
                total=len(scenario.expect),
                check=expected["check"],
            )
            self._check(expected, scenario)

    def _catalog_check(self, expected: dict, scenario: Scenario) -> None:
        path = self.catalog_path or scenario.fixture.get("catalog")
        if not path:
            raise ContextUnavailable("Catalog checks require fixture.catalog or --jira-catalog")
        catalog = Catalog.load(Path(path))
        filters = {
            key: expected[key]
            for key in ("field", "screen", "source", "status", "transition")
            if key in expected
        }
        observations = catalog.query(issue_type=scenario.fixture["issue_type"], **filters)
        if not observations:
            raise ContextUnavailable("No observation for this context; absence remains unknown")
        check = expected["check"]
        if check == "catalog_exists":
            # API observation means available in metadata; UI uses observed visibility.
            values = [True if item.source == "api" else item.visible for item in observations]
            _expect(
                all(value is expected["value"] for value in values),
                "Field presence differs in observed contexts",
            )
        elif check == "catalog_required":
            if any(item.required is None for item in observations):
                raise ContextUnavailable("Required state unknown for this context")
            _expect(
                all(item.required is expected["value"] for item in observations),
                "Required state differs in observed contexts",
            )
        else:
            target = expected["contains"]
            _expect(
                all(
                    any(matches(option, target) for option in item.options) for item in observations
                ),
                "Expected option not found in catalog",
            )
