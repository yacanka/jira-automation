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
    from unittest.mock import Mock

    from jira_test.components import SelectField

    element = Mock()
    element.evaluate.return_value = "select"
    element.locator.return_value.count.return_value = 1
    element.locator.return_value.first.get_attribute.return_value = ""
    SelectField(element).clear()
    element.select_option.assert_called_once_with(value="")


def test_multiselect_preserves_mixed_labels_and_ids_in_one_selection():
    from unittest.mock import Mock

    from jira_test.components import MultiSelectField

    element = Mock()
    element.evaluate.return_value = "select"
    element.locator.return_value.first.evaluate.return_value = 1
    MultiSelectField(element).fill(["First", {"id": "2"}])
    element.select_option.assert_called_once_with(index=[1], label=["First"])
