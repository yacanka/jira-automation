"""Doğrudan komponent kullanımı. Önkoşul: Task 10001, description edit ekranında açık.

Kimlikleri kendi kataloğunuza uyarlayın. Çalıştırma:
pytest examples/python/test_01_components.py --jira-config config.local.yaml
Beklenen: description değişikliği REST üzerinden kalıcı olarak doğrulanır.
"""

from jira_test.waiting import wait_until


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
        wait_until(
            lambda: client.issue(issue["key"])["fields"]["description"] == "Python ile güncellendi",
            config.timeout,
        )
    finally:
        ui.cancel()
