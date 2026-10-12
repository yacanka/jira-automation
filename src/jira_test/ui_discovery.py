"""Conservative browser-only fallback when REST authentication is unavailable.

Only native project/type selectors and configured issue samples are used. Workflow
buttons are inventoried, never clicked without REST confirmation of a transition screen.
"""

import re

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from .browser import Browser
from .catalog import Catalog
from .client import identifier
from .config import Config
from .errors import ContextUnavailable
from .ui import JiraUI


def discover_ui_only(config: Config, browser: Browser, project: str) -> Catalog:
    driver = browser.start()
    wait = WebDriverWait(driver, config.timeout)
    catalog = Catalog(project=project, user="configured-user")
    catalog.gaps.append(
        {
            "reason": "Browser-only mode: field schemas, API required flags, "
            "full workflow rules and REST capabilities remain unknown"
        }
    )
    # Observation methods need no API calls; write methods are disabled.
    ui = JiraUI(browser, None, readonly=True)  # type: ignore[arg-type]
    types: list[dict] = []

    def create_form() -> None:
        driver.get(config.base_url + "/secure/CreateIssue!default.jspa")
        browser.assert_origin()
        ui.root = wait.until(
            EC.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    ui.locators.get("create.root", "#issue-create, #create-issue-dialog"),
                )
            )
        )
        element = driver.find_element(
            By.CSS_SELECTOR, ui.locators.get("create.project_identity", "#project")
        )
        if element.tag_name != "select":
            raise ContextUnavailable("Browser-only discovery requires a native project selector")
        select = Select(element)
        choices = [
            option
            for option in select.options
            if option.get_attribute("data-project-key") == project
            or f"({project})" in option.text
            or option.text.strip() == project
        ]
        if len(choices) != 1:
            raise ContextUnavailable("Cannot identify project in browser-only create selector")
        select.select_by_value(str(choices[0].get_attribute("value")))
        wait.until(lambda d: Select(d.find_element(By.CSS_SELECTOR, "#issuetype")).options)

    try:
        create_form()
        selector = ui.locators.get("create.type_identity", "#issuetype")
        types = [
            {"id": str(option.get_attribute("value")), "name": option.text}
            for option in Select(driver.find_element(By.CSS_SELECTOR, selector)).options
            if str(option.get_attribute("value")).isdigit()
        ]
        catalog.issue_types = types
        for item in types:
            create_form()
            element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
            Select(element).select_by_value(item["id"])

            def selected_type(d: WebDriver, type_id: str = item["id"]) -> bool:
                return d.find_element(By.CSS_SELECTOR, selector).get_attribute("value") == type_id

            wait.until(selected_type)
            ui.screen, ui.issue_type, ui.project_key = "create", item["id"], project
            catalog.observations.extend(ui.observe({}))
    except (ContextUnavailable, WebDriverException) as exc:
        catalog.gaps.append(
            {
                "screen": "create",
                "reason": type(exc).__name__ + "; browser-only create discovery incomplete",
            }
        )
    finally:
        ui.cancel()
    for type_id, keys in config.samples.items():
        for key in keys:
            if not re.fullmatch(re.escape(project) + r"-\d+", key):
                catalog.gaps.append(
                    {"issue_type": type_id, "reason": "Sample key project mismatch"}
                )
                continue
            try:
                driver.get(config.base_url + "/browse/" + identifier(key))
                browser.assert_origin()
                ui.root = wait.until(
                    EC.visibility_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            ui.locators.get("view.root", "#issue-content, #issue-view"),
                        )
                    )
                )
                ui.screen, ui.issue_type, ui.issue_key = "view", type_id, key
                catalog.observations.extend(ui.observe({}))
                for element in driver.find_elements(By.CSS_SELECTOR, "[data-transition-id]"):
                    catalog.transitions.append(
                        {
                            "issue_type": type_id,
                            "issue": key,
                            "id": element.get_attribute("data-transition-id"),
                            "name": element.text,
                            "source": "ui",
                            "has_screen": None,
                        }
                    )
                edit_button = ui.locators.get("edit.button", "#edit-issue")
                wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, edit_button))).click()
                ui.root = wait.until(
                    EC.visibility_of_element_located(
                        (
                            By.CSS_SELECTOR,
                            ui.locators.get("edit.root", "#issue-edit, #edit-issue-dialog"),
                        )
                    )
                )
                ui.screen = "edit"
                catalog.observations.extend(ui.observe({}))
            except WebDriverException as exc:
                catalog.gaps.append(
                    {"issue": key, "reason": type(exc).__name__ + "; sample discovery incomplete"}
                )
            finally:
                ui.cancel()
    if not config.samples:
        catalog.gaps.append({"reason": "Configure samples for browser-only view/edit discovery"})
    catalog.gaps.append(
        {
            "reason": "Transition buttons were never clicked: their side effects "
            "cannot be classified without REST metadata"
        }
    )
    return catalog
