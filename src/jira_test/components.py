"""Reusable field components. Unsupported plugin widgets require an explicit adapter."""

import re
from typing import Any, Literal

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import Select, WebDriverWait

from .errors import UnsupportedFieldError


def css_attribute(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\a ")


class LocatorMap:
    def __init__(self, overrides: dict[str, str] | None = None):
        self.overrides = overrides or {}

    def get(self, name: str, default: str) -> str:
        return self.overrides.get(name, default)

    def field(self, screen: str, field_id: str) -> str:
        default = f'[id="{css_attribute(field_id)}"]'
        if screen == "view":
            default = f'[id="{css_attribute(field_id)}-val"], {default}'
        return self.get(f"{screen}.{field_id}", default)


class FieldComponent:
    def __init__(self, element: WebElement, wait: WebDriverWait, schema: dict | None = None):
        self.element = element
        self.wait = wait
        self.schema = schema or {}

    def fill(self, value: Any) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        self.fill("")

    def read(self) -> Any:
        return self.element.get_attribute("value")


class TextField(FieldComponent):
    def fill(self, value: Any) -> None:
        self.element.clear()
        if value is not None and str(value):
            self.element.send_keys(str(value))


class NumberField(TextField):
    def fill(self, value: Any) -> None:
        if value not in (None, "") and not isinstance(value, (int, float)):
            raise UnsupportedFieldError("Numeric fields require a YAML number")
        super().fill(value)


class DateField(TextField):
    """Uses Jira's displayed date format; the test supplies that format explicitly."""


class SelectField(FieldComponent):
    def fill(self, value: Any) -> None:
        if value is None or value == "":
            self.clear()
            return
        if self.element.tag_name == "select":
            select = Select(self.element)
            if isinstance(value, dict) and "id" in value:
                select.select_by_value(str(value["id"]))
            else:
                select.select_by_visible_text(str(value))
            return
        # AUI autocomplete options are scoped to the active visible suggestion list.
        self.element.clear()
        if value in (None, ""):
            self.element.send_keys(Keys.TAB)
            return
        if not isinstance(value, str):
            raise UnsupportedFieldError("Autocomplete fields require the displayed option label")
        self.element.send_keys(value)

        def exact_option(driver: Any) -> WebElement | Literal[False]:
            candidates = driver.find_elements(
                By.CSS_SELECTOR, '.aui-list-item a, [role="option"], .select2-results li'
            )
            matches = [el for el in candidates if el.is_displayed() and el.text.strip() == value]
            if len(matches) > 1:
                raise UnsupportedFieldError("Ambiguous autocomplete label; override the component")
            return matches[0] if matches else False

        option = self.wait.until(exact_option)
        option.click()

    def clear(self) -> None:
        if self.element.tag_name == "select":
            select = Select(self.element)
            blanks = [
                option.get_attribute("value")
                for option in select.options
                if option.get_attribute("value") in {"", "-1"}
            ]
            if not blanks:
                raise UnsupportedFieldError("Select has no empty option")
            select.select_by_value(str(blanks[0]))
            return
        self.element.clear()
        self.element.send_keys(Keys.TAB)


class MultiSelectField(SelectField):
    def fill(self, value: Any) -> None:
        if not isinstance(value, list):
            raise UnsupportedFieldError("Multi-select fields require a list")
        self.clear()
        for entry in value:
            super().fill(entry)

    def clear(self) -> None:
        if self.element.tag_name == "select":
            Select(self.element).deselect_all()
            return
        container = self.element.find_element(By.XPATH, "..")
        for button in container.find_elements(
            By.CSS_SELECTOR, ".remove, .select2-search-choice-close"
        ):
            if button.is_displayed():
                button.click()
        self.element.clear()


class UserField(SelectField):
    """Autocomplete matching uses the exact visible Jira user label."""


class CheckboxField(FieldComponent):
    def fill(self, value: Any) -> None:
        boxes = (
            [self.element]
            if self.element.get_attribute("type") == "checkbox"
            else self.element.find_elements(By.CSS_SELECTOR, 'input[type="checkbox"]')
        )
        if not boxes:
            raise UnsupportedFieldError("Checkbox container has no checkbox controls")
        if isinstance(value, bool) and len(boxes) == 1:
            targets = [value]
        elif isinstance(value, list):
            targets = [box.get_attribute("value") in [str(v) for v in value] for box in boxes]
        else:
            raise UnsupportedFieldError("Checkbox value must be boolean or a list of option IDs")
        for box, selected in zip(boxes, targets, strict=True):
            if box.is_selected() != selected:
                box.click()

    def clear(self) -> None:
        self.fill(False if self.element.get_attribute("type") == "checkbox" else [])


class RichTextField(TextField):
    def fill(self, value: Any) -> None:
        if self.element.tag_name == "iframe":
            driver = self.wait._driver
            driver.switch_to.frame(self.element)
            try:
                body = driver.find_element(By.CSS_SELECTOR, "body")
                body.send_keys(
                    Keys.COMMAND
                    if driver.capabilities.get("platformName") == "mac"
                    else Keys.CONTROL,
                    "a",
                )
                body.send_keys(Keys.BACKSPACE)
                if value is not None:
                    body.send_keys(str(value))
            finally:
                driver.switch_to.default_content()
            return
        if self.element.get_attribute("contenteditable") == "true":
            self.element.send_keys(
                Keys.COMMAND
                if self.wait._driver.capabilities.get("platformName") == "mac"
                else Keys.CONTROL,
                "a",
            )
            self.element.send_keys(Keys.BACKSPACE)
            self.element.send_keys(str(value or ""))
            return
        super().fill(value)


class FieldRegistry:
    def __init__(self) -> None:
        self._custom: dict[str, type[FieldComponent]] = {}

    def register(self, schema_key: str, component: type[FieldComponent]) -> None:
        """Register a schema.custom or schema.system adapter before running tests."""
        if not issubclass(component, FieldComponent):
            raise TypeError("Field adapters must extend FieldComponent")
        self._custom[schema_key] = component

    def resolve(self, schema: dict) -> type[FieldComponent]:
        custom = schema.get("custom")
        key = custom or schema.get("system", "")
        if key in self._custom:
            return self._custom[key]
        if custom:
            prefix = "com.atlassian.jira.plugin.system.customfieldtypes:"
            builtins = {
                "textfield": TextField,
                "textarea": RichTextField,
                "float": NumberField,
                "datepicker": DateField,
                "datetime": DateField,
                "select": SelectField,
                "multiselect": MultiSelectField,
                "userpicker": UserField,
                "multiuserpicker": MultiSelectField,
                "multicheckboxes": CheckboxField,
                "url": TextField,
            }
            if custom.startswith(prefix) and custom[len(prefix) :] in builtins:
                return builtins[custom[len(prefix) :]]
            raise UnsupportedFieldError(f"No adapter registered for custom schema {custom}")
        if schema.get("system") == "description":
            return RichTextField
        types = {
            "string": TextField,
            "number": NumberField,
            "date": DateField,
            "datetime": DateField,
            "option": SelectField,
            "user": UserField,
            "priority": SelectField,
            "resolution": SelectField,
        }
        if schema.get("type") == "array":
            if schema.get("items") in {"option", "user", "version", "component"}:
                return MultiSelectField
            raise UnsupportedFieldError("Array schema needs a dedicated adapter")
        if schema.get("type") not in types:
            raise UnsupportedFieldError(f"No adapter for schema type {schema.get('type')}")
        return types[schema["type"]]


def field_label(element: WebElement, field_id: str) -> str:
    try:
        labels = element.find_elements(
            By.XPATH,
            'ancestor::*[contains(concat(" ", normalize-space(@class), " "), " field-group ")]'
            "[1]//label",
        )
        return labels[0].text.strip().rstrip(" *") if labels else field_id
    except NoSuchElementException:
        return field_id


def field_identity(element: WebElement) -> str | None:
    identity = element.get_attribute("id") or element.get_attribute("name") or ""
    if re.fullmatch(r"customfield_\d+", identity) or identity in {
        "summary",
        "description",
        "priority",
        "assignee",
        "reporter",
        "duedate",
        "environment",
        "resolution",
        "fixVersions",
        "versions",
        "components",
        "labels",
    }:
        return identity
    return None
