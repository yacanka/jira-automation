"""Doğrudan komponent kullanımı. Önkoşul: Task 10001, description edit ekranında açık.

Kimlikleri kendi kataloğunuza uyarlayın. Çalıştırma:
pytest examples/python/test_01_components.py --jira-config config.local.yaml
Beklenen: description değişikliği REST üzerinden kalıcı olarak doğrulanır.
"""

from selenium.webdriver.support.ui import WebDriverWait


def test_description_with_components(jira_session):
    client, ui = jira_session.live()
    config = jira_session.config
    issue = client.create_issue(
        {
            **config.default_fields,
            "project": {"key": config.test_project},
            "issuetype": {"id": "10001"},
            "summary": "Python komponent örneği",
        }
    )
    try:
        ui.metadata = client.edit_fields(issue["key"])
        ui.open(screen="edit", project=config.test_project, issue_type="10001", issue=issue["key"])
        ui.fill("description", "Python ile güncellendi")
        assert ui.submit()["accepted"] is True
        WebDriverWait(client, config.timeout).until(
            lambda api: api.issue(issue["key"])["fields"]["description"] == "Python ile güncellendi"
        )
    finally:
        ui.cancel()
