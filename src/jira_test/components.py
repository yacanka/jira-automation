"""Reusable Playwright field components and explicit adapters for plugin widgets."""

import re
from typing import Any

from playwright.sync_api import Locator

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
    def __init__(self, element: Locator, schema: dict | None = None):
        self.element = element
        self.schema = schema or {}

    def fill(self, value: Any) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        self.fill("")

    def read(self) -> Any:
        return self.element.input_value()

    def _is_native_select(self) -> bool:
        return self.element.evaluate("element => element.tagName.toLowerCase()") == "select"


class TextField(FieldComponent):
    def fill(self, value: Any) -> None:
        self.element.fill("" if value is None else str(value))


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
        if self._is_native_select():
            if isinstance(value, dict) and "id" in value:
                self.element.select_option(index=self._option_index(value["id"]))
            else:
                self.element.select_option(label=str(value))
            return
        if not isinstance(value, str):
            raise UnsupportedFieldError("Autocomplete fields require the displayed option label")
        self.element.fill(value)
        # Jira portals may render suggestions outside the field's DOM container.
        # Ignore hidden duplicates, but reject multiple visible exact matches.
        options = self.element.page.locator(
            '.aui-list-item a:visible, [role="option"]:visible, .select2-results li:visible'
        ).filter(has_text=re.compile(r"^\s*" + re.escape(value) + r"\s*$"))
        options.first.wait_for(state="visible")
        if options.count() != 1:
            raise UnsupportedFieldError("Ambiguous autocomplete label; override the component")
        options.click()

    def _option_index(self, identity: Any) -> int:
        # Python's value selector also matches labels. Resolve IDs explicitly so a
        # label equal to another option's ID cannot select the wrong option.
        option = self.element.locator(f'option[value="{css_attribute(identity)}"]').first
        return int(option.evaluate("option => option.index"))

    def clear(self) -> None:
        if self._is_native_select():
            blanks = self.element.locator('option[value=""], option[value="-1"]')
            if not blanks.count():
                raise UnsupportedFieldError("Select has no empty option")
            self.element.select_option(value=blanks.first.get_attribute("value") or "")
            return
        self.element.fill("")
        self.element.press("Tab")


class MultiSelectField(SelectField):
    def fill(self, value: Any) -> None:
        if not isinstance(value, list):
            raise UnsupportedFieldError("Multi-select fields require a list")
        if self._is_native_select():
            # One batch is necessary: select_option replaces the whole selection.
            indices = [
                self._option_index(entry["id"])
                for entry in value
                if isinstance(entry, dict) and "id" in entry
            ]
            labels = [
                str(entry) for entry in value if not (isinstance(entry, dict) and "id" in entry)
            ]
            self.element.select_option(index=indices, label=labels)
            return
        self.clear()
        for entry in value:
            super().fill(entry)

    def clear(self) -> None:
        if self._is_native_select():
            self.element.select_option([])
            return
        buttons = self.element.locator("..").locator(
            ".remove:visible, .select2-search-choice-close:visible"
        )
        for _ in range(buttons.count()):
            buttons.first.click()
        self.element.fill("")


class UserField(SelectField):
    """Autocomplete matching uses the exact visible Jira user label."""


class CheckboxField(FieldComponent):
    def fill(self, value: Any) -> None:
        boxes = (
            [self.element]
            if self.element.get_attribute("type") == "checkbox"
            else self.element.locator('input[type="checkbox"]').all()
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
            box.set_checked(selected)

    def clear(self) -> None:
        self.fill(False if self.element.get_attribute("type") == "checkbox" else [])


class RichTextField(TextField):
    def _editor(self) -> Locator:
        if self.element.evaluate("element => element.tagName.toLowerCase()") == "iframe":
            return self.element.content_frame.locator("body")
        return self.element

    def fill(self, value: Any) -> None:
        self._editor().fill("" if value is None else str(value))

    def read(self) -> str:
        editor = self._editor()
        if editor.evaluate("element => element.isContentEditable"):
            # Chromium leaves an empty <br> after clearing editable content;
            # inner_text exposes that caret placeholder as a newline.
            return editor.inner_text() if editor.text_content() else ""
        return editor.input_value()


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


def field_label(element: Locator, field_id: str) -> str:
    labels = element.locator(
        'xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " field-group ")]'
        "[1]//label"
    )
    return labels.first.inner_text().strip().rstrip(" *") if labels.count() else field_id


def field_identity(element: Locator) -> str | None:
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
