"""Parent/subtask ilişkisi. Önkoşul: Task 10001 ve subtask 10002 türleri açık.

pytest examples/python/test_03_parent_subtask.py --jira-config config.local.yaml
Beklenen: subtask doğru parent'a bağlıdır, UI açıklama düzenlemesi kalıcıdır.
"""

from jira_test.runner import ScenarioRunner
from jira_test.scenario import validate


def test_parent_and_subtask(jira_session):
    client, ui = jira_session.live()
    case = validate(
        {
            "id": "parent-subtask",
            "fixture": {"issue_type": "10002", "parent": {"issue_type": "10001"}},
            "steps": [
                {"action": "open", "screen": "edit"},
                {"action": "fill", "field": "description", "value": "Alt görev"},
                {"action": "submit"},
            ],
            "expect": [
                {"check": "accepted", "value": True},
                {"check": "persisted", "field": "description", "value": "Alt görev"},
            ],
        }
    )
    result = ScenarioRunner(jira_session.config, client, ui).run(case)
    assert client.issue(result["issue"])["fields"]["parent"]["key"] == result["parent"]
