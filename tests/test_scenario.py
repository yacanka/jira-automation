import pytest

from jira_test.errors import ScenarioError
from jira_test.scenario import load_scenarios


def test_minimum_scenario(tmp_path):
    path = tmp_path / "case.yaml"
    path.write_text(
        'id: field-exists\nfixture: {issue_type: "10001"}\nsteps:\n'
        "  - {action: open, screen: create}\n"
        "expect:\n  - {check: visible, field: summary, value: true}\n"
    )
    scenario = load_scenarios(path)[0]
    assert scenario.id == "field-exists"
    assert scenario.steps[0]["action"] == "open"


@pytest.mark.parametrize(
    "steps,message",
    [
        ([{"action": "execute_python"}], "Unknown action"),
        (
            [{"action": "open", "screen": "edit"}, {"action": "fill", "field": "summary"}],
            "Invalid keys for fill",
        ),
        ([{"action": "open", "screen": "delete"}], "Unknown screen"),
    ],
)
def test_invalid_scenarios_fail_before_browser(steps, message, tmp_path):
    import yaml

    case = valid_case()
    case["steps"] = steps
    path = tmp_path / "case.yaml"
    path.write_text(yaml.safe_dump(case))
    with pytest.raises(ScenarioError, match=message):
        load_scenarios(path)


def test_executable_yaml_tags_are_rejected(tmp_path):
    path = tmp_path / "case.yaml"
    path.write_text("!!python/object/apply:os.system [echo unsafe]")
    with pytest.raises(ScenarioError, match="safe scenario YAML"):
        load_scenarios(path)


def test_unknown_fields_and_duplicate_yaml_keys_rejected(tmp_path):
    path = tmp_path / "case.yaml"
    path.write_text(
        'id: one\nid: two\nfixture: {issue_type: "1"}\nsteps: []\n'
        'expect: [{check: transition_available, id: "31", value: true}]'
    )
    with pytest.raises(ScenarioError, match="Duplicate"):
        load_scenarios(path)


@pytest.mark.parametrize(
    "steps",
    [
        [{"action": "fill", "field": "summary", "value": "unopened"}],
        [{"action": "submit"}],
        [{"action": "open", "screen": "view"}, {"action": "clear", "field": "summary"}],
        [
            {"action": "open", "screen": "edit"},
            {"action": "submit"},
            {"action": "fill", "field": "summary", "value": "already closed"},
        ],
    ],
)
def test_invalid_action_order_rejected_before_execution(steps):
    from jira_test.scenario import validate

    with pytest.raises(ScenarioError):
        validate(
            {
                "id": "order",
                "fixture": {"issue_type": "1"},
                "steps": steps,
                "expect": [{"check": "visible", "field": "summary", "value": True}],
            }
        )


def valid_case():
    return {
        "id": "validation",
        "fixture": {"issue_type": "1"},
        "steps": [{"action": "open", "screen": "edit"}],
        "expect": [{"check": "visible", "field": "summary", "value": True}],
    }


@pytest.mark.parametrize("check", ["visible", "editable", "required"])
def test_ui_expectations_require_an_open_screen(check):
    from jira_test.scenario import validate

    case = valid_case()
    case["steps"] = []
    case["expect"] = [{"check": check, "field": "summary", "value": False}]
    with pytest.raises(ScenarioError, match="open screen"):
        validate(case)


def test_accepted_expectation_requires_submission():
    from jira_test.scenario import validate

    case = valid_case()
    case["expect"] = [{"check": "accepted", "value": True}]
    with pytest.raises(ScenarioError, match="submit/transition"):
        validate(case)


@pytest.mark.parametrize("value", [42, [], {}, "", "   "])
def test_rejection_message_must_be_nonempty_text(value):
    from jira_test.scenario import validate

    case = valid_case()
    case["steps"].append({"action": "submit"})
    case["expect"] = [{"check": "accepted", "value": False, "error_contains": value}]
    with pytest.raises(ScenarioError, match="error_contains"):
        validate(case)


@pytest.mark.parametrize("step", [{"action": []}, {"action": "open", "screen": []}])
def test_invalid_operation_types_raise_scenario_error(step):
    from jira_test.scenario import validate

    case = valid_case()
    case["steps"] = [step]
    with pytest.raises(ScenarioError):
        validate(case)


@pytest.mark.parametrize(
    "key,value", [("catalog", 1), ("mode", []), ("path", [{"id": "1", "status": {}}])]
)
def test_invalid_fixture_value_types_raise_scenario_error(key, value):
    from jira_test.scenario import validate

    case = valid_case()
    case["fixture"][key] = value
    with pytest.raises(ScenarioError):
        validate(case)


def test_ui_expectations_after_submit_need_explicit_screen():
    from jira_test.scenario import validate

    case = valid_case()
    case["steps"].append({"action": "submit"})
    with pytest.raises(ScenarioError, match="open screen"):
        validate(case)
    case["steps"].append({"action": "open", "screen": "view"})
    assert validate(case).steps[-1]["screen"] == "view"
