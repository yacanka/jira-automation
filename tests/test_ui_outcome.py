from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jira_test.ui import JiraUI
from jira_test.waiting import WaitTimeoutError


class StateClient:
    def __init__(self, fields):
        self.fields = fields

    def issue(self, key):
        return {"fields": self.fields}


def ui_with_state(fields, errors):
    ui = object.__new__(JiraUI)
    ui.client = StateClient(fields)
    ui.issue_key = "TST-1"
    ui.page = Mock()
    ui.root = None
    ui.browser = SimpleNamespace(assert_origin=lambda: None, config=SimpleNamespace(timeout=0.01))
    ui.errors = lambda: errors
    return ui


def test_screenless_click_is_not_success_without_persisted_transition():
    ui = ui_with_state({"status": {"id": "10"}, "updated": "before"}, {})
    with pytest.raises(WaitTimeoutError):
        ui._screenless_outcome({"status": {"id": "10"}, "updated": "before"}, "20")


def test_screenless_validation_rejection_is_reported():
    ui = ui_with_state({"status": {"id": "10"}, "updated": "before"}, {"_form": "Value required"})
    result = ui._screenless_outcome({"status": {"id": "10"}, "updated": "before"}, "20")
    assert result["accepted"] is False
    assert result["errors"]["_form"] == "Value required"


def test_screenless_target_status_confirms_success():
    ui = ui_with_state({"status": {"id": "20"}, "updated": "after"}, {})
    assert (
        ui._screenless_outcome({"status": {"id": "10"}, "updated": "before"}, "20")["accepted"]
        is True
    )


def test_self_transition_requires_changed_updated_timestamp():
    ui = ui_with_state({"status": {"id": "10"}, "updated": "before"}, {})
    with pytest.raises(WaitTimeoutError):
        ui._screenless_outcome({"status": {"id": "10"}, "updated": "before"}, "10")


def test_form_disappearance_without_issue_view_is_not_success():
    ui = ui_with_state({"status": {"id": "10"}, "updated": "after"}, {})

    ui.root = Mock()
    ui.root.is_visible.return_value = False
    ui.browser = SimpleNamespace(assert_origin=lambda: None, config=SimpleNamespace(timeout=0.01))
    ui.page.locator.return_value.all.return_value = []
    ui.locators = SimpleNamespace(get=lambda name, default: default)
    ui.screen = "edit"
    with pytest.raises(WaitTimeoutError):
        ui._form_outcome({"status": {"id": "10"}, "updated": "before"})


def test_readonly_ui_rejects_writes_before_any_browser_action():
    from jira_test.errors import WriteBoundaryError

    ui = ui_with_state({}, {})
    ui.readonly = True
    ui.project_key = "SRC"
    with pytest.raises(WriteBoundaryError):
        ui.fill("summary", "forbidden")
    ui.page.locator.assert_not_called()


def test_form_outcome_checks_origin_before_inspection():
    from jira_test.errors import WriteBoundaryError

    ui = ui_with_state({}, {})
    ui.browser.assert_origin = Mock(side_effect=WriteBoundaryError("Origin changed"))
    with pytest.raises(WriteBoundaryError):
        ui._form_outcome(None)
    ui.page.locator.assert_not_called()


def test_unverified_ui_created_issue_remains_reportable_without_ownership():
    from jira_test.client import JiraClient
    from jira_test.config import Config
    from jira_test.errors import WriteBoundaryError

    config = Config(base_url="https://jira.test", source_project="SRC", test_project="TST")
    api = JiraClient(config, session=Mock())
    api.issue = Mock(return_value={"fields": {"project": {"key": "TST"}, "summary": "No marker"}})
    ui = ui_with_state({}, {})
    ui.client = api
    ui.screen = "create"
    ui.browser.config = config
    key = Mock()
    key.is_visible.return_value = True
    key.inner_text.return_value = "TST-2"
    ui.page.locator.return_value.all.return_value = [key]
    ui.locators = SimpleNamespace(get=lambda name, default: default)
    with pytest.raises(WriteBoundaryError, match="test run"):
        ui._form_outcome(None)
    assert api.created_keys == ["TST-2"]
    assert api.owned_keys == []
