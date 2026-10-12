"""Özel adaptör. Önkoşul: vendor:uppercase-text şemalı özel input alanı olmalı.

pytest examples/python/test_04_custom_adapter.py --jira-config config.local.yaml
Şema anahtarını, alan ID'sini ve gerçek widget uygulamasını değiştirin.
Beklenen: adaptör girdiyi büyük harfe çevirir, kayıt değeri HAZIR olur.
Desteklenmeyen şema tahmin edilmez; açıkça registry'ye kaydedilir.
"""

from jira_test.components import TextField
from jira_test.runner import ScenarioRunner
from jira_test.scenario import validate


class UppercaseField(TextField):
    def fill(self, value):
        super().fill(str(value).upper())


def test_registered_adapter(jira_session):
    jira_session.registry.register("vendor:uppercase-text", UppercaseField)
    client, ui = jira_session.live()
    case = validate(
        {
            "id": "custom-adapter",
            "fixture": {"issue_type": "10001"},
            "steps": [
                {"action": "open", "screen": "edit"},
                {"action": "fill", "field": "customfield_10099", "value": "hazır"},
                {"action": "submit"},
            ],
            "expect": [
                {"check": "accepted", "value": True},
                {"check": "persisted", "field": "customfield_10099", "value": "HAZIR"},
            ],
        }
    )
    assert ScenarioRunner(jira_session.config, client, ui).run(case)["outcome"] == "passed"
