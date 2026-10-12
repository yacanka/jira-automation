"""Parametrik test. Önkoşul: Task 10001, customfield_10011 sayısal ve edit ekranında.

pytest examples/python/test_02_parametrized.py --jira-config config.local.yaml
Beklenen: 0, 1 ve 100 ayrı kayıtlarda kaydedilir. Sınırları iş kuralınıza uyarlayın.
"""

import pytest

from jira_test.runner import ScenarioRunner
from jira_test.scenario import validate


@pytest.mark.parametrize("value", [0, 1, 100])
def test_numeric_values(jira_session, value):
    client, ui = jira_session.live()
    case = validate(
        {
            "id": f"numeric-{value}",
            "fixture": {"issue_type": "10001"},
            "steps": [
                {"action": "open", "screen": "edit"},
                {"action": "fill", "field": "customfield_10011", "value": value},
                {"action": "submit"},
            ],
            "expect": [
                {"check": "accepted", "value": True},
                {"check": "persisted", "field": "customfield_10011", "value": value},
            ],
        }
    )
    assert ScenarioRunner(jira_session.config, client, ui).run(case)["outcome"] == "passed"
