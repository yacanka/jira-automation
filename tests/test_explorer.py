from jira_test.config import Config
from jira_test.explorer import Explorer


class DiscoveryClient:
    def issue_types(self, project):
        return [{"id": "1", "name": "Task"}, {"id": "2", "name": "Subtask", "subtask": True}]

    def create_fields(self, project, issue_type):
        return [
            {
                "fieldId": "summary",
                "name": "Summary",
                "required": True,
                "schema": {"type": "string", "system": "summary"},
            }
        ]

    def sample_issues(self, project, issue_type):
        return [] if issue_type == "2" else [self.issue("SRC-1")]

    def issue(self, key):
        return {
            "key": key,
            "fields": {"project": {"key": "SRC"}, "issuetype": {"id": "1"}, "status": {"id": "10"}},
        }

    def edit_fields(self, key):
        return {"summary": {"required": True, "schema": {"type": "string"}}}

    def transitions(self, key):
        return [{"id": "31", "name": "Done", "hasScreen": False, "to": {"id": "20"}, "fields": {}}]


def test_api_discovery_preserves_gaps_without_writes():
    config = Config(base_url="https://jira.test", source_project="SRC", test_project="TST")
    catalog = Explorer(config, DiscoveryClient()).discover("SRC", ui=None)
    assert catalog.query(field="summary", issue_type="1", screen="create")[0].required is True
    assert catalog.transitions[0]["id"] == "31"
    assert any(gap.get("issue_type") == "2" for gap in catalog.gaps)
    assert any("UI" in gap["reason"] for gap in catalog.gaps)


def test_explorer_never_opens_screenless_transition():
    class UI:
        def __init__(self):
            self.calls = []

        def open(self, **kwargs):
            self.calls.append(kwargs)

        def observe(self, metadata):
            return []

        def cancel(self):
            pass

    ui = UI()
    config = Config(base_url="https://jira.test", source_project="SRC", test_project="TST")
    Explorer(config, DiscoveryClient()).discover("SRC", ui=ui)
    assert not any(call["screen"] == "transition" for call in ui.calls)


def test_view_inventory_includes_fields_not_on_edit_screen():
    class ViewClient(DiscoveryClient):
        def fields(self):
            return [{"id": "customfield_50", "name": "Read only", "schema": {"type": "string"}}]

        def issue(self, key):
            issue = super().issue(key)
            issue["fields"]["customfield_50"] = "value is not exported"
            return issue

    config = Config(base_url="https://jira.test", source_project="SRC", test_project="TST")
    catalog = Explorer(config, ViewClient()).discover("SRC")
    rows = catalog.query(field="customfield_50", screen="view", source="api")
    assert rows
    assert "value is not exported" not in str(rows)
