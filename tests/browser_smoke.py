"""Explicit local Selenium tests, independent of a Jira instance.

Run with the virtual environment Python: python -m pytest tests/browser_smoke.py -q
Requires installed Chrome and a compatible local driver or Selenium Manager access.
"""

from pathlib import Path
from urllib.parse import quote

import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

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
        headless=True,
    )
    instance = Browser(config)
    try:
        instance.start()
        yield instance
    finally:
        instance.close()


@pytest.fixture
def driver(browser):
    driver = browser.start()
    driver.get("data:text/html;charset=utf-8," + quote(HTML))
    return driver


def component(driver, name, cls):
    return cls(driver.find_element(By.ID, name), WebDriverWait(driver, 3))


def test_text_fill_and_clear(driver):
    field = component(driver, "summary", TextField)
    field.fill("Synthetic text")
    assert field.read() == "Synthetic text"
    field.clear()
    assert field.read() == ""


def test_number_boundary(driver):
    field = component(driver, "customfield_1", NumberField)
    field.fill(0)
    assert field.read() == "0"


def test_select_by_label_and_id(driver):
    field = component(driver, "single", SelectField)
    field.fill("Second")
    assert field.read() == "2"
    field.fill({"id": "1"})
    assert field.read() == "1"
    field.clear()
    assert field.read() == ""


def test_multiselect_clear_removes_old_values(driver):
    field = component(driver, "multi", MultiSelectField)
    field.fill(["First", "Second"])
    field.fill(["Third"])
    assert [
        o.get_attribute("value")
        for o in field.element.find_elements(By.TAG_NAME, "option")
        if o.is_selected()
    ] == ["3"]


def test_checkbox_state(driver):
    field = component(driver, "check", CheckboxField)
    field.fill(True)
    assert field.element.is_selected()
    field.clear()
    assert not field.element.is_selected()


def test_rich_text_replaces_existing_content(driver):
    field = component(driver, "rich", RichTextField)
    field.fill("New text")
    assert field.element.text == "New text"


def test_ui_required_editable_and_validation_evidence(driver, browser):
    ui = JiraUI(browser, None, readonly=True)
    ui.screen = "edit"
    ui.root = driver.find_element(By.ID, "issue-edit")
    ui.metadata = {"summary": {"schema": {"type": "string"}}}
    assert ui.required("summary") is True
    assert ui.editable("customfield_2") is False
    assert ui.visible("missing") is False
    assert "required" in ui.errors()["summary"]


def test_catalog_html_filter_and_download(browser):
    driver = browser.start()
    from jira_test.catalog import Catalog
    from jira_test.report import render_catalog

    html = render_catalog(Catalog.load(Path("examples/demo-catalog.json")))
    driver.get("data:text/html;charset=utf-8," + quote(html))
    assert len(driver.find_elements(By.CSS_SELECTOR, "tbody tr")) == 6
    search = driver.find_element(By.ID, "search")
    search.send_keys("summary")
    assert (
        len(
            [row for row in driver.find_elements(By.CSS_SELECTOR, "tbody tr") if row.is_displayed()]
        )
        == 2
    )
    assert driver.execute_script("return typeof observations") == "object"
    driver.execute_script("""
        URL.createObjectURL = blob => {
            blob.text().then(text => window.downloadedYaml = text);
            return 'blob:synthetic-test';
        };
        URL.revokeObjectURL = () => {};
        HTMLAnchorElement.prototype.click = function() {};
    """)
    driver.find_element(By.CSS_SELECTOR, "tbody tr button").click()
    generated = WebDriverWait(driver, 3).until(
        lambda d: d.execute_script("return window.downloadedYaml")
    )
    import yaml

    from jira_test.scenario import validate

    case = validate(yaml.safe_load(generated))
    assert case.fixture["issue_type"] == "10001"
    assert case.expect[0]["field"] == "summary"
    assert case.expect[0]["value"] is True
    Path("artifacts/demo").mkdir(parents=True, exist_ok=True)
    driver.save_screenshot("artifacts/demo/catalog-preview.png")
