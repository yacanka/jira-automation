from types import SimpleNamespace

import pytest
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait

from jira_test.ui import JiraUI


class StateClient:
    def __init__(self, fields):
        self.fields = fields

    def issue(self, key):
        return {"fields": self.fields}


def ui_with_state(fields, errors):
    ui = object.__new__(JiraUI)
    ui.client = StateClient(fields)
    ui.issue_key = "TST-1"
    ui.driver = SimpleNamespace()
    ui.browser = SimpleNamespace(assert_origin=lambda: None)
    ui.wait = WebDriverWait(ui.driver, 0.01, poll_frequency=0.001)
    ui.errors = lambda: errors
    return ui


def test_screenless_click_is_not_success_without_persisted_transition():
    ui = ui_with_state({"status": {"id": "10"}, "updated": "before"}, {})
    with pytest.raises(TimeoutException):
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
    with pytest.raises(TimeoutException):
        ui._screenless_outcome({"status": {"id": "10"}, "updated": "before"}, "10")


def test_form_disappearance_without_issue_view_is_not_success():
    from selenium.common.exceptions import StaleElementReferenceException

    ui = ui_with_state({"status": {"id": "10"}, "updated": "after"}, {})

    class StaleRoot:
        def is_displayed(self):
            raise StaleElementReferenceException()

    ui.root = StaleRoot()
    ui.browser = SimpleNamespace(assert_origin=lambda: None)
    ui.driver.find_elements = lambda *args: []
    ui.locators = SimpleNamespace(get=lambda name, default: default)
    ui.screen = "edit"
    with pytest.raises(TimeoutException):
        ui._form_outcome({"status": {"id": "10"}, "updated": "before"})
