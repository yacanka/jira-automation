"""Explicit real-Tk smoke suite; run with a Python distribution containing Tk.

This file is intentionally outside pytest's default test_*.py discovery, so CI
without a desktop can still test the Tk-free document and worker layers.
"""

import tkinter as tk
from copy import deepcopy
from types import SimpleNamespace

import pytest
import yaml

from jira_test.catalog import Catalog, Observation
from jira_test.gui.designer import DesignerPanel, new_scenario
from jira_test.gui.widgets import MappingDialog, PathDialog, RecordDialog, TypedEditor, ValueDialog
from jira_test.scenario import ACTIONS, CHECKS


@pytest.fixture
def root():
    window = tk.Tk()
    window.geometry("1280x850")
    yield window
    window.destroy()


@pytest.fixture
def panel(root, tmp_path):
    catalog = Catalog(
        project="TEST",
        user="test",
        issue_types=[{"id": "10001"}],
        transitions=[{"id": "21"}],
        observations=[Observation("10001", "create", "summary", "api")],
    )
    app = SimpleNamespace(workspace=tmp_path, catalog=catalog, status=lambda text: None)
    result = DesignerPanel(root, app)
    result.pack(fill="both", expand=True)
    root.update()
    return result


def test_real_designer_source_roundtrip_and_visual_metadata(panel, root, tmp_path, monkeypatch):
    source = "# retained comment\n" + yaml.safe_dump(new_scenario(), sort_keys=False)
    path = tmp_path / "scenario.yaml"
    path.write_text(source)
    assert panel.load(path)
    root.update()
    assert panel.save()
    assert path.read_text() == source
    notices = []
    monkeypatch.setattr(
        "jira_test.gui.designer.messagebox.showinfo", lambda *a, **k: notices.append(a)
    )
    panel.metadata["description"].set("Görsel düzenleme")
    assert panel.apply_metadata()
    assert len(notices) == 1
    assert panel.save()
    assert yaml.safe_load(path.read_text())["description"] == "Görsel düzenleme"
    assert panel.validate()


def test_real_yaml_invalid_draft_is_retained(panel, root):
    original = deepcopy(panel.document.cases)
    panel.notebook.select(1)
    root.update()
    panel.raw.delete("1.0", "end")
    panel.raw.insert("1.0", "id: [")
    root.update()
    panel.notebook.select(0)
    root.update()
    assert panel.notebook.index("current") == 1
    assert panel.document.cases == original
    assert panel.document.yaml_draft == "id: ["
    assert not panel.validate()
    assert panel.error.get()


def test_real_suite_and_operation_manipulation(panel, root, monkeypatch):
    panel.copy_case()
    assert len(panel.document.cases) == 2
    assert panel.current == 1
    panel.operation_lists["expect"].selection_set("0")
    panel.copy_operation("expect")
    assert len(panel.document.cases[1]["expect"]) == 2
    panel.operation_lists["expect"].selection_set("1")
    panel.move_operation("expect", -1)
    assert panel.operation_lists["expect"].selection() == ("0",)
    panel.remove_operation("expect")
    assert len(panel.document.cases[1]["expect"]) == 1
    monkeypatch.setattr("jira_test.gui.designer.messagebox.askyesno", lambda *a, **k: True)
    panel.remove_case()
    assert len(panel.document.cases) == 1
    monkeypatch.setattr("jira_test.gui.designer.messagebox.askyesnocancel", lambda *a, **k: None)
    assert not panel.can_leave()
    monkeypatch.setattr("jira_test.gui.designer.messagebox.askyesnocancel", lambda *a, **k: False)
    assert panel.can_leave()


def test_real_dynamic_record_forms_cover_engine_definitions(root):
    samples = {
        "field": "customfield_1",
        "id": "21",
        "transition": "21",
        "screen": "transition",
        "source": "api",
        "status": "Done",
        "value": False,
        "error_contains": "required",
        "contains": ["a", {"id": "001"}],
        "fields": {"customfield_1": ["001"]},
    }
    for key, definitions in (("action", ACTIONS), ("check", CHECKS)):
        for kind, (allowed, required) in definitions.items():
            record = {key: kind, **{name: deepcopy(samples[name]) for name in allowed}}
            dialog = RecordDialog(root, kind, record, allowed, required)
            root.update()
            assert dialog.value() == record
            dialog.destroy()


def test_real_structured_parent_path_and_typed_values(root):
    parent = {"issue_type": "001", "fields": {"priority": {"id": "02"}}}
    dialog = RecordDialog(root, "Üst iş", parent, {"issue_type", "fields"}, {"issue_type"})
    assert dialog.value() == parent
    dialog.destroy()
    path = [{"id": "21", "status": "Done", "fields": {"labels": ["a", "b"]}}, {"id": "22"}]
    dialog = PathDialog(root, path, {})
    dialog.rows.selection_clear(0, "end")
    dialog.rows.selection_set(1)
    dialog.move(-1)
    assert dialog.value() == [path[1], path[0]]
    dialog.destroy()
    mapping = MappingDialog(root, "Alanlar", {"customfield_1": None})
    assert mapping.value() == {"customfield_1": None}
    mapping.destroy()
    editor = TypedEditor(root, "001")
    assert editor.get() == "001"
    editor.kind.set("number")
    with pytest.raises(ValueError):
        editor.get()
    editor.destroy()
    value = ValueDialog(root, "Null", None)
    value.accept()
    assert value.accepted
    assert value.result is None


def test_metadata_error_does_not_erase_form(panel, root):
    panel.copy_case()
    panel.metadata["id"].set("")
    panel.cases.selection_clear(0, "end")
    panel.cases.selection_set(0)
    panel._select_case()
    assert panel.current == 1
    assert panel.metadata["id"].get() == ""
    assert panel._form_dirty


def test_invalid_template_opens_raw_draft(panel, root):
    scenario = new_scenario()
    scenario["expect"][0]["value"] = None
    assert panel.load(scenario=scenario)
    root.update()
    assert panel.notebook.index("current") == 1
    assert "null" in panel.document.yaml_draft
    assert panel.error.get()


def test_initial_placeholder_is_clean_and_first_edit_is_dirty(panel, monkeypatch):
    def unexpected_prompt(*args, **kwargs):
        raise AssertionError("Untouched placeholder must not prompt")

    monkeypatch.setattr("jira_test.gui.designer.messagebox.askyesnocancel", unexpected_prompt)
    assert panel.document.path is None
    assert not panel.document.dirty
    assert panel.can_leave()
    panel.metadata["description"].set("İlk değişiklik")
    assert panel._form_dirty
    monkeypatch.setattr("jira_test.gui.designer.messagebox.askyesnocancel", lambda *a, **k: None)
    before = deepcopy(panel.document.cases)
    assert not panel.can_leave()
    assert panel.metadata["description"].get() == "İlk değişiklik"
    assert panel.document.cases == before
    assert panel.apply_metadata()
    assert panel.document.dirty


def test_save_as_cancel_preserves_edits_and_failed_load_keeps_document(
    panel, tmp_path, monkeypatch
):
    panel.metadata["description"].set("Kaydedilmeyen değişiklik")
    monkeypatch.setattr("jira_test.gui.designer.filedialog.asksaveasfilename", lambda **k: "")
    assert not panel.save()
    assert panel.document.path is None
    assert panel.document.dirty
    assert panel.document.cases[0]["description"] == "Kaydedilmeyen değişiklik"
    original = panel.document
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("id: [", encoding="utf-8")
    assert not panel.load(invalid)
    assert panel.document is original
    assert panel.metadata["description"].get() == "Kaydedilmeyen değişiklik"


def test_open_file_cancel_preserves_invalid_raw_draft(panel, root, monkeypatch):
    panel.notebook.select(1)
    root.update()
    panel.raw.delete("1.0", "end")
    panel.raw.insert("1.0", "id: [")
    root.update()
    original = deepcopy(panel.document.cases)
    monkeypatch.setattr("jira_test.gui.designer.messagebox.askyesnocancel", lambda *a, **k: False)
    monkeypatch.setattr("jira_test.gui.designer.filedialog.askopenfilename", lambda **k: "")
    panel.open_file()
    assert panel.document.cases == original
    assert panel.raw.get("1.0", "end-1c") == "id: ["
    assert panel.document.dirty
