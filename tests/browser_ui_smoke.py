"""Real-browser safety and discovery regressions against intercepted local HTML only.

Run explicitly: python -m pytest tests/browser_ui_smoke.py -q
"""

import os
from unittest.mock import Mock

import pytest

from jira_test.browser import Browser
from jira_test.client import JiraClient
from jira_test.components import LocatorMap
from jira_test.config import Config
from jira_test.errors import WriteBoundaryError
from jira_test.ui import JiraUI
from jira_test.ui_discovery import discover_ui_only
from jira_test.waiting import WaitTimeoutError

EDIT_FORM = """<form id="issue-edit" onsubmit="return false">
<input id="summary" value="Original"><button type="button" id="issue-edit-submit">
Save</button></form>"""


@pytest.fixture(scope="module")
def browser():
    instance = Browser(
        Config(
            base_url="https://jira.example.test",
            source_project="SRC",
            test_project="TST",
            browser=os.environ.get("JIRA_SMOKE_BROWSER", "chrome"),
            headless=True,
            timeout=3,
        )
    )
    try:
        instance.start()
        yield instance
    finally:
        instance.close()


@pytest.fixture
def page(browser):
    page = browser.start()
    browser.config.timeout = 0.2
    browser.config.samples = {}
    browser.locators = LocatorMap()
    page.route("**/*", lambda route: route.fulfill(content_type="text/html", body=EDIT_FORM))
    page.goto("https://jira.example.test/local-fixture")
    yield page
    page.unroute("**/*")


def edit_ui(browser):
    client = Mock(spec=JiraClient)
    client.issue.return_value = {"fields": {"project": {"key": "TST"}, "updated": "before"}}
    ui = JiraUI(browser, client)
    ui.screen, ui.project_key, ui.issue_key = "edit", "TST", "TST-1"
    ui.root = ui.page.locator("#issue-edit")
    ui.metadata = {"summary": {"schema": {"type": "string"}}}
    return ui


def click_result(page, html):
    page.locator("#issue-edit-submit").evaluate(
        "(button, html) => button.onclick = () => document.body.innerHTML = html", html
    )


def test_submit_disappearance_without_key_is_not_success(page, browser):
    ui = edit_ui(browser)
    click_result(page, "<p>Form closed</p>")
    with pytest.raises(WaitTimeoutError):
        ui.submit()


def test_submit_requires_persisted_update_and_matching_key(page, browser):
    ui = edit_ui(browser)
    before = {"fields": {"project": {"key": "TST"}, "updated": "before"}}
    after = {"fields": {"project": {"key": "TST"}, "updated": "after"}}
    # Boundary check and pre-submit snapshot precede the persisted result check.
    ui.client.issue.side_effect = [before, before, after]
    click_result(page, '<span id="key-val">TST-1</span>')
    assert ui.submit() == {"accepted": True, "errors": {}, "key": "TST-1"}
    ui.client.assert_owned.assert_called_once_with("TST-1")


@pytest.mark.parametrize("key", ["TST-1", "TST-2"])
def test_submit_does_not_accept_unchanged_or_wrong_issue(page, browser, key):
    ui = edit_ui(browser)
    click_result(page, f'<span id="key-val">{key}</span>')
    with pytest.raises(WaitTimeoutError):
        ui.submit()


def test_submit_reports_visible_validation_rejection(page, browser):
    ui = edit_ui(browser)
    page.locator("#issue-edit-submit").evaluate("""button => button.onclick = () => {
        const error = document.createElement('div');
        error.id = 'summary-error';
        error.textContent = 'Summary is required';
        button.parentElement.append(error);
    }""")
    result = ui.submit()
    assert result["accepted"] is False
    assert result["errors"]["summary"] == "Summary is required"


def test_create_identity_reads_selected_property_not_attribute(page, browser):
    page.set_content("""<form id="issue-create">
        <select name="pid" value="wrong"><option value="10">Test</option>
        <option value="99">Other</option></select>
        <select id="issuetype" value="wrong"><option value="100">Bug</option>
        <option value="200">Task</option></select></form>""")
    ui = JiraUI(browser, Mock())
    ui.screen, ui.project_key, ui.issue_type = "create", "TST", "100"
    ui.root = page.locator("#issue-create")
    ui.client.project.return_value = {"id": "10"}
    ui._validate_create_identity()
    page.locator('[name="pid"]').select_option("99")
    with pytest.raises(WriteBoundaryError, match="selected test project"):
        ui._validate_create_identity()
    page.locator('[name="pid"]').select_option("10")
    page.locator("#issuetype").select_option("200")
    with pytest.raises(WriteBoundaryError, match="issue type"):
        ui._validate_create_identity()


@pytest.mark.parametrize("operation", ["fill", "clear", "submit"])
@pytest.mark.parametrize("boundary", ["readonly", "wrong_origin", "source_project"])
def test_writes_reject_unsafe_context(page, browser, operation, boundary):
    ui = edit_ui(browser)
    if boundary == "readonly":
        ui.readonly = True
    elif boundary == "source_project":
        ui.project_key = "SRC"
    else:
        page.goto("https://other.example.test/local-fixture")
    with pytest.raises(WriteBoundaryError):
        if operation == "fill":
            ui.fill("summary", "Changed")
        elif operation == "clear":
            ui.clear("summary")
        else:
            ui.submit()
    assert page.locator("#summary").input_value() == "Original"
    ui.client.assert_owned.assert_not_called()


def test_browser_only_discovery_inventories_without_transition_or_submit(page, browser):
    page.unroute("**/*")
    browser.config.timeout = 3
    browser.config.samples = {"100": ["SRC-1"]}
    browser.locators = LocatorMap({"create.type_identity": "#custom-type"})
    requests = []
    create_html = """<form id="issue-create" action="/forbidden-submit" method="post">
        <select id="project"><option value="10" data-project-key="SRC">Source</option></select>
        <select id="custom-type"><option value="100">Bug</option>
        <option value="200">Task</option></select>
        <div class="field-group"><label>Summary *</label><input id="summary" required></div>
        <button id="issue-create-submit">Create</button></form>"""
    view_html = """<div id="issue-content"><input id="summary" value="Existing"></div>
        <a data-transition-id="31" href="/forbidden-transition">Done</a>
        <button id="edit-issue" onclick="document.querySelector('#issue-edit').hidden=false">
        Edit</button><form id="issue-edit" hidden action="/forbidden-submit" method="post">
        <input id="summary" value="Existing"><button id="issue-edit-submit">Save</button></form>"""

    def respond(route):
        requests.append((route.request.method, route.request.url))
        if "CreateIssue" in route.request.url:
            body = create_html
        elif "/browse/" in route.request.url:
            body = view_html
        else:
            body = "<p>Dashboard</p>"
        route.fulfill(content_type="text/html", body=body)

    page.route("**/*", respond)
    catalog = discover_ui_only(browser.config, browser, "SRC")
    assert catalog.issue_types == [{"id": "100", "name": "Bug"}, {"id": "200", "name": "Task"}]
    assert {(item.screen, item.issue_type) for item in catalog.observations} >= {
        ("create", "100"),
        ("create", "200"),
        ("view", "100"),
        ("edit", "100"),
    }
    assert catalog.transitions == [
        {
            "issue_type": "100",
            "issue": "SRC-1",
            "id": "31",
            "name": "Done",
            "source": "ui",
            "has_screen": None,
        }
    ]
    assert requests
    assert all(method == "GET" and "forbidden" not in url for method, url in requests)
    assert not any("incomplete" in gap["reason"] for gap in catalog.gaps)


def test_screenless_rejection_survives_replaced_view_root(page, browser):
    page.set_content('<div id="issue-content">Issue</div>')
    ui = edit_ui(browser)
    ui.screen = "transition"
    ui.root = page.locator("#issue-content")
    ui.client.issue.return_value = {"fields": {"status": {"id": "10"}, "updated": "before"}}
    page.set_content('<div class="aui-message-error">Transition rejected</div>')
    result = ui._screenless_outcome({"status": {"id": "10"}, "updated": "before"}, "20")
    assert result["accepted"] is False
    assert result["errors"]["_form"] == "Transition rejected"
