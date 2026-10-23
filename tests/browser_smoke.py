"""Local Playwright integration tests, independent of a Jira instance.

Run: python -m pytest tests/browser_smoke.py -q
Uses installed Chrome by default; set JIRA_SMOKE_BROWSER=edge or firefox to override.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from jira_test.browser import Browser
from jira_test.components import (
    CheckboxField,
    MultiSelectField,
    NumberField,
    RichTextField,
    SelectField,
    TextField,
)
from jira_test.config import Config
from jira_test.errors import UnsupportedFieldError
from jira_test.ui import JiraUI

HTML = """<!doctype html><html><body><form id="issue-edit">
<div class="field-group"><label for="summary">Summary
<span class="aui-icon-required">*</span></label><input id="summary" required>
<div class="error" id="summary-error">Summary is required</div></div>
<input id="customfield_1" type="number"><input id="customfield_2" disabled>
<select id="single"><option value="">None</option><option value="1">First</option>
<option value="2">Second</option></select>
<select id="multi" multiple><option value="1">First</option>
<option value="2">Second</option><option value="3">Third</option></select>
<input type="checkbox" id="check"><div contenteditable="true" id="rich">Old text</div>
</form></body></html>"""


@pytest.fixture(scope="module")
def browser():
    config = Config(
        base_url="https://jira.example.test",
        source_project="SRC",
        test_project="TST",
        browser=os.environ.get("JIRA_SMOKE_BROWSER", "chrome"),
        timeout=3,
        headless=True,
    )
    instance = Browser(config)
    try:
        instance.start()
        yield instance
    finally:
        instance.close()


@pytest.fixture
def page(browser):
    page = browser.start()
    assert page is browser.page
    page.set_content(HTML)
    return page


def component(page, name, cls):
    return cls(page.locator(f'[id="{name}"]'))


def test_text_fill_and_clear(page):
    field = component(page, "summary", TextField)
    field.fill("Synthetic text")
    assert field.read() == "Synthetic text"
    field.clear()
    assert field.read() == ""


def test_number_boundary(page):
    field = component(page, "customfield_1", NumberField)
    field.fill(0)
    assert field.read() == "0"
    with pytest.raises(UnsupportedFieldError, match="YAML number"):
        field.fill("not a number")


def test_select_by_label_and_id(page):
    field = component(page, "single", SelectField)
    field.fill("Second")
    assert field.read() == "2"
    field.fill({"id": "1"})
    assert field.read() == "1"
    field.clear()
    assert field.read() == ""


def test_multiselect_preserves_mixed_values_and_clears_old_values(page):
    field = component(page, "multi", MultiSelectField)
    field.fill(["First", {"id": "2"}])
    assert field.element.locator("option:checked").evaluate_all(
        "options => options.map(option => option.value)"
    ) == ["1", "2"]
    field.fill(["Third"])
    assert field.element.locator("option:checked").evaluate_all(
        "options => options.map(option => option.value)"
    ) == ["3"]
    field.clear()
    assert field.element.locator("option:checked").count() == 0


def test_checkbox_state(page):
    field = component(page, "check", CheckboxField)
    field.fill(True)
    assert field.element.is_checked()
    field.clear()
    assert not field.element.is_checked()


def test_rich_text_replaces_existing_content(page):
    field = component(page, "rich", RichTextField)
    field.fill("New text")
    assert field.read() == "New text"
    field.clear()
    assert field.read() == ""


def test_iframe_rich_text_does_not_change_page_context(page):
    page.set_content(
        '<input id="summary"><iframe id="editor" '
        'srcdoc="<body contenteditable=true>Old text</body>"></iframe>'
    )
    field = component(page, "editor", RichTextField)
    field.fill("New iframe text")
    assert field.read() == "New iframe text"
    field.clear()
    assert field.read() == ""
    component(page, "summary", TextField).fill("Still on parent page")
    assert page.locator("#summary").input_value() == "Still on parent page"


def test_text_waits_for_delayed_dom(page):
    page.set_content("<main></main>")
    page.evaluate("""() => setTimeout(() => {
        document.querySelector('main').innerHTML = '<input id="late">';
    }, 150)""")
    field = component(page, "late", TextField)
    field.fill("Ready")
    assert field.read() == "Ready"


def test_autocomplete_waits_for_exact_visible_label(page):
    page.set_content("""<input id="picker">
        <div role="option" style="display:none">Target</div>
        <div role="option">Target extra</div>
        <script>document.querySelector('input').addEventListener('input', () => {
            setTimeout(() => {
                const option = document.createElement('div');
                option.setAttribute('role', 'option');
                option.textContent = 'Target';
                option.onclick = () => document.body.dataset.selected = 'Target';
                document.body.append(option);
            }, 150);
        });</script>""")
    component(page, "picker", SelectField).fill("Target")
    assert page.locator("body").get_attribute("data-selected") == "Target"


def test_autocomplete_rejects_ambiguous_visible_labels(page):
    page.set_content(
        '<input id="picker"><div role="option">Same</div><div role="option">Same</div>'
    )
    with pytest.raises(UnsupportedFieldError, match="Ambiguous"):
        component(page, "picker", SelectField).fill("Same")


def test_missing_autocomplete_option_times_out(page):
    page.set_content('<input id="picker"><div role="option">Different</div>')
    page.set_default_timeout(200)
    try:
        with pytest.raises(PlaywrightTimeoutError):
            component(page, "picker", SelectField).fill("Missing")
    finally:
        page.set_default_timeout(3000)


def test_native_select_without_blank_rejects_clear(page):
    page.set_content('<select id="single"><option value="1">First</option></select>')
    with pytest.raises(UnsupportedFieldError, match="no empty option"):
        component(page, "single", SelectField).clear()


def test_ui_required_editable_and_validation_evidence(page, browser):
    ui = JiraUI(browser, None, readonly=True)
    assert ui.page is page
    ui.screen = "edit"
    ui.root = page.locator("#issue-edit")
    ui.metadata = {"summary": {"schema": {"type": "string"}}}
    assert ui.required("summary") is True
    assert ui.editable("customfield_2") is False
    assert ui.visible("missing") is False
    assert "required" in ui.errors()["summary"]


def test_catalog_html_filter_and_download(page, tmp_path):
    import yaml

    from jira_test.catalog import Catalog
    from jira_test.report import render_catalog
    from jira_test.scenario import validate

    html = render_catalog(Catalog.load(Path("examples/demo-catalog.json")))
    page.set_content(html)
    assert page.locator("tbody tr").count() == 6
    page.locator("#search").fill("summary")
    assert page.locator("tbody tr:visible").count() == 2
    assert page.evaluate("typeof observations") == "object"
    with page.expect_download() as event:
        page.locator("tbody tr:visible button").first.click()
    download = event.value
    destination = tmp_path / "generated.yaml"
    download.save_as(destination)
    assert download.failure() is None
    case = validate(yaml.safe_load(destination.read_text()))
    assert case.fixture["issue_type"] == "10001"
    assert case.expect[0]["field"] == "summary"
    assert case.expect[0]["value"] is True
