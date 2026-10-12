from copy import deepcopy

import pytest

from jira_test.config import Config
from jira_test.errors import ScenarioError
from jira_test.runner import ScenarioRunner
from jira_test.scenario import validate


class MemoryClient:
    def __init__(self):
        self.records = {}
        self.run_id = "offline-run"
        self.owned_keys = []

    def create_issue(self, fields):
        key = f"TST-{len(self.records) + 1}"
        self.records[key] = {"key": key, "fields": {**fields, "status": {"id": "10"}}}
        self.owned_keys.append(key)
        return {"key": key}

    def issue(self, key):
        return deepcopy(self.records[key])

    def transitions(self, key):
        return [{"id": "31"}]

    def create_fields(self, project, issue_type):
        return [{"fieldId": "summary", "schema": {"type": "string"}}]

    def edit_fields(self, key):
        return {"summary": {"schema": {"type": "string"}}}

    def assert_owned(self, key):
        assert key in self.owned_keys

    def summary(self, text):
        return "[jira-test:offline-run] " + text


class RejectingUI:
    def __init__(self, client, changed=False):
        self.client = client
        self.changed = changed
        self.metadata = {}

    def open(self, **kwargs):
        self.key = kwargs.get("issue")

    def fill(self, field, value):
        pass

    def clear(self, field):
        pass

    def submit(self):
        if self.changed:
            self.client.records[self.key]["fields"]["summary"] = "unexpected mutation"
        return {"accepted": False, "errors": {"summary": "Summary is required"}, "key": self.key}

    def cancel(self):
        pass


def rejection_case():
    return validate(
        {
            "id": "reject-empty-summary",
            "fixture": {"issue_type": "1"},
            "steps": [
                {"action": "open", "screen": "edit"},
                {"action": "clear", "field": "summary"},
                {"action": "submit"},
            ],
            "expect": [
                {
                    "check": "accepted",
                    "value": False,
                    "field": "summary",
                    "error_contains": "required",
                }
            ],
        }
    )


def test_expected_rejection_requires_unchanged_record():
    client = MemoryClient()
    runner = ScenarioRunner(
        Config(base_url="https://jira.test", source_project="SRC", test_project="TST"),
        client,
        RejectingUI(client),
    )
    result = runner.run(rejection_case())
    assert result["outcome"] == "passed"


def test_rejection_with_mutation_fails():
    client = MemoryClient()
    runner = ScenarioRunner(
        Config(base_url="https://jira.test", source_project="SRC", test_project="TST"),
        client,
        RejectingUI(client, changed=True),
    )
    with pytest.raises(AssertionError, match="changed"):
        runner.run(rejection_case())


def test_catalog_only_case_needs_no_credentials(tmp_path):
    from jira_test.catalog import Catalog, Observation

    path = tmp_path / "catalog.json"
    catalog = Catalog(project="SRC", user="offline")
    catalog.add(
        Observation(issue_type="1", screen="create", field="summary", source="api", required=True)
    )
    catalog.save(path)
    case = validate(
        {
            "id": "required",
            "fixture": {"issue_type": "1", "mode": "none", "catalog": str(path)},
            "steps": [],
            "expect": [
                {
                    "check": "catalog_required",
                    "screen": "create",
                    "source": "api",
                    "field": "summary",
                    "value": True,
                }
            ],
        }
    )
    assert ScenarioRunner(None).run(case)["outcome"] == "passed"


def test_readonly_fixture_cannot_edit():
    case = validate(
        {
            "id": "unsafe",
            "fixture": {"issue_type": "1", "mode": "none"},
            "steps": [{"action": "open", "screen": "edit"}],
            "expect": [{"check": "visible", "field": "summary", "value": True}],
        }
    )
    with pytest.raises(ScenarioError):
        ScenarioRunner(None).run(case)


def test_runner_will_not_fill_a_screenless_transition_after_executing_it():
    client = MemoryClient()
    ui = RejectingUI(client)
    case = validate(
        {
            "id": "screenless-fields",
            "fixture": {"issue_type": "1"},
            "steps": [{"action": "transition", "id": "31", "fields": {"summary": "value"}}],
            "expect": [{"check": "accepted", "value": True}],
        }
    )
    runner = ScenarioRunner(
        Config(base_url="https://jira.test", source_project="SRC", test_project="TST"), client, ui
    )
    from jira_test.errors import ContextUnavailable

    with pytest.raises(ContextUnavailable, match="screenless"):
        runner.run(case)
    assert not hasattr(ui, "key")


def test_option_list_assertions_compare_ordered_projections():
    from jira_test.runner import matches

    actual = [
        {"id": "1", "self": "https://jira.test/option/1", "value": "First"},
        {"id": "2", "value": "Second"},
    ]
    assert matches(actual, [{"id": "1"}, {"id": "2"}])
    assert not matches(actual, [{"id": "2"}, {"id": "1"}])
    assert not matches(actual, [{"id": "1"}])


def test_failure_evidence_is_captured_before_leaving_form():
    client = MemoryClient()
    ui = RejectingUI(client, changed=True)
    events = []
    ui.cancel = lambda: events.append("cancel")
    runner = ScenarioRunner(
        Config(base_url="https://jira.test", source_project="SRC", test_project="TST"),
        client,
        ui,
        on_failure=lambda: events.append("evidence"),
    )
    with pytest.raises(AssertionError):
        runner.run(rejection_case())
    assert events == ["evidence", "cancel"]
