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
    "content",
    [
        "id: invalid\nfixture: {}\nsteps: [{action: execute_python}]\nexpect: []",
        'id: invalid\nfixture: {issue_type: "1"}\n'
        "steps: [{action: fill, field: summary}]\nexpect: []",
        'id: invalid\nfixture: {issue_type: "1"}\n'
        "steps: [{action: open, screen: delete}]\nexpect: []",
        "!!python/object/apply:os.system [echo unsafe]",
    ],
)
def test_invalid_scenarios_fail_before_browser(content, tmp_path):
    path = tmp_path / "case.yaml"
    path.write_text(content)
    with pytest.raises(ScenarioError):
        load_scenarios(path)


def test_unknown_fields_and_duplicate_yaml_keys_rejected(tmp_path):
    path = tmp_path / "case.yaml"
    path.write_text('id: one\nid: two\nfixture: {issue_type: "1"}\nsteps: []\nexpect: []')
    with pytest.raises(ScenarioError):
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
