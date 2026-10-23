"""Conservative browser-only fallback when REST authentication is unavailable.

Only native project/type selectors and configured issue samples are used. Workflow
buttons are inventoried, never clicked without REST confirmation of a transition screen.
"""

import re

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect

from .browser import Browser
from .catalog import Catalog
from .client import identifier
from .config import Config
from .errors import ContextUnavailable
from .ui import JiraUI


def discover_ui_only(config: Config, browser: Browser, project: str) -> Catalog:
    page = browser.start()
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
        page.goto(config.base_url + "/secure/CreateIssue!default.jspa")
        browser.assert_origin()
        ui.root = ui._visible_locator(
            ui.locators.get("create.root", "#issue-create, #create-issue-dialog")
        )
        element = page.locator("css=" + ui.locators.get("create.project_identity", "#project"))
        if element.evaluate("el => el.tagName.toLowerCase()") != "select":
            raise ContextUnavailable("Browser-only discovery requires a native project selector")
        choices = [
            option
            for option in element.locator("option").all()
            if option.get_attribute("data-project-key") == project
            or f"({project})" in option.inner_text()
            or option.inner_text().strip() == project
        ]
        if len(choices) != 1:
            raise ContextUnavailable("Cannot identify project in browser-only create selector")
        element.select_option(value=str(choices[0].get_attribute("value")))
        type_options = page.locator(
            "css=" + ui.locators.get("create.type_identity", "#issuetype")
        ).locator("option")
        expect(type_options.first).to_be_attached(timeout=config.timeout * 1000)

    try:
        create_form()
        selector = ui.locators.get("create.type_identity", "#issuetype")
        types = [
            {"id": str(option.get_attribute("value")), "name": option.inner_text()}
            for option in page.locator("css=" + selector).locator("option").all()
            if str(option.get_attribute("value")).isdigit()
        ]
        catalog.issue_types = types
        for item in types:
            create_form()
            element = page.locator("css=" + selector)
            element.select_option(value=item["id"])
            expect(element).to_have_value(item["id"], timeout=config.timeout * 1000)
            ui.screen, ui.issue_type, ui.project_key = "create", item["id"], project
            catalog.observations.extend(ui.observe({}))
    except (ContextUnavailable, PlaywrightError, AssertionError) as exc:
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
                page.goto(config.base_url + "/browse/" + identifier(key))
                browser.assert_origin()
                ui.root = ui._visible_locator(
                    ui.locators.get("view.root", "#issue-content, #issue-view")
                )
                ui.screen, ui.issue_type, ui.issue_key = "view", type_id, key
                catalog.observations.extend(ui.observe({}))
                for element in page.locator("[data-transition-id]").all():
                    catalog.transitions.append(
                        {
                            "issue_type": type_id,
                            "issue": key,
                            "id": element.get_attribute("data-transition-id"),
                            "name": element.inner_text(),
                            "source": "ui",
                            "has_screen": None,
                        }
                    )
                edit_button = ui.locators.get("edit.button", "#edit-issue")
                ui._visible_locator(edit_button).click()
                ui.root = ui._visible_locator(
                    ui.locators.get("edit.root", "#issue-edit, #edit-issue-dialog")
                )
                ui.screen = "edit"
                catalog.observations.extend(ui.observe({}))
            except PlaywrightError as exc:
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
