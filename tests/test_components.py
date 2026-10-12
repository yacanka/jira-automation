import pytest

from jira_test.components import FieldRegistry, LocatorMap
from jira_test.errors import UnsupportedFieldError


def test_registry_does_not_guess_plugin_widgets():
    with pytest.raises(UnsupportedFieldError):
        FieldRegistry().resolve({"type": "string", "custom": "vendor:secret-widget"})


def test_registry_accepts_builtin_custom_text():
    component = FieldRegistry().resolve(
        {"type": "string", "custom": "com.atlassian.jira.plugin.system.customfieldtypes:textfield"}
    )
    assert component.__name__ == "TextField"


def test_locator_identity_is_separate_from_field_identity():
    locators = LocatorMap({"create.customfield_42": "#custom-input"})
    assert locators.field("create", "customfield_42") == "#custom-input"
    assert locators.field("create", "summary") == '[id="summary"]'


def test_native_select_clear_uses_empty_option_value():
    class Option:
        def get_attribute(self, name):
            return ""

    class Selection:
        tag_name = "select"

        def get_dom_attribute(self, name):
            return None

        def find_elements(self, by, value):
            return [Option()]

    from unittest.mock import patch

    from jira_test.components import SelectField

    with patch("jira_test.components.Select") as select:
        select.return_value.options = [Option()]
        SelectField(Selection(), None).clear()
        select.return_value.select_by_value.assert_called_once_with("")
