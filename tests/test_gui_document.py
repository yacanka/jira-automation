"""Designer document tests deliberately have no Tk/display dependency."""

from copy import deepcopy

import pytest
import yaml

from jira_test.errors import ScenarioError
from jira_test.gui.document import ScenarioDocument, parse_typed_value


def case(identifier="case"):
    return {
        "id": identifier,
        "fixture": {"issue_type": "10001"},
        "steps": [{"action": "open", "screen": "create"}],
        "expect": [{"check": "visible", "field": "summary", "value": True}],
    }


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_text_roundtrip_preserves_comments_until_visual_edit(tmp_path, newline):
    source = ("# keep this comment\n" + yaml.safe_dump(case())).replace("\n", newline)
    path = tmp_path / "suite.yaml"
    path.write_bytes(source.encode("utf-8"))
    doc = ScenarioDocument()
    doc.load(path)
    doc.save()
    assert path.read_bytes().decode("utf-8") == source
    changed = deepcopy(doc.cases[0])
    changed["description"] = "Changed"
    doc.set_case(0, changed)
    assert doc.dirty
    assert "# keep this comment" not in doc.text
    doc.save()
    assert not doc.dirty


def test_invalid_yaml_keeps_last_good_document_and_raw_draft():
    doc = ScenarioDocument()
    doc.load_text(yaml.safe_dump(case()))
    before = deepcopy(doc.cases)
    for invalid in ("id: [", "id: a\nid: b", "[]", "- id: bad"):
        with pytest.raises((ScenarioError, ValueError)):
            doc.apply_yaml(invalid)
        assert doc.cases == before
        assert doc.yaml_draft == invalid
        assert doc.dirty


def test_failed_load_does_not_replace_path_or_document(tmp_path):
    first = tmp_path / "first.yaml"
    first.write_text(yaml.safe_dump(case()))
    bad = tmp_path / "bad.yaml"
    bad.write_text("broken")
    doc = ScenarioDocument()
    doc.load(first)
    with pytest.raises(ScenarioError):
        doc.load(bad)
    assert doc.path == first
    assert doc.cases[0]["id"] == "case"
    assert not doc.dirty


def test_multi_scenario_copy_remove_and_duplicate_ids(tmp_path):
    doc = ScenarioDocument()
    doc.load_text(yaml.safe_dump([case("one"), case("two")]))
    index = doc.add_case(doc.cases[0])
    assert doc.cases[index]["id"] == "one-copy"
    doc.cases[index]["fixture"]["issue_type"] = "other"
    assert doc.cases[0]["fixture"]["issue_type"] == "10001"
    invalid = deepcopy(doc.cases[1])
    invalid["id"] = "one"
    with pytest.raises(ScenarioError):
        doc.set_case(1, invalid)
    doc.remove_case(index)
    path = tmp_path / "suite.yaml"
    doc.save(path)
    reopened = ScenarioDocument()
    reopened.load(path)
    assert [c["id"] for c in reopened.cases] == ["one", "two"]


def test_copy_and_reorder_operations_preserve_nested_values():
    doc = ScenarioDocument()
    data = case()
    data["steps"].append({"action": "fill", "field": "customfield_1", "value": [1, True]})
    doc.load_text(yaml.safe_dump(data))
    doc.copy_operation(0, "steps", 1)
    doc.cases[0]["steps"][2]["value"].append("x")
    assert doc.cases[0]["steps"][1]["value"] == [1, True]
    doc.move_operation(0, "steps", 2, -1)
    assert doc.cases[0]["steps"][1]["value"] == [1, True, "x"]


@pytest.mark.parametrize(
    "kind,text,expected",
    [
        ("str", "001", "001"),
        ("number", "12.5", 12.5),
        ("bool", "false", False),
        ("list", '["001", true, {"id":"2"}]', ["001", True, {"id": "2"}]),
        ("object", '{"id": "001"}', {"id": "001"}),
        ("null", "", None),
    ],
)
def test_typed_values(kind, text, expected):
    assert parse_typed_value(kind, text) == expected


@pytest.mark.parametrize(
    "kind,text",
    [
        ("number", "true"),
        ("number", "NaN"),
        ("bool", "yes"),
        ("list", "{}"),
        ("object", "[]"),
        ("object", '{"a":1,"a":2}'),
    ],
)
def test_typed_values_reject_type_mismatch(kind, text):
    with pytest.raises(ValueError):
        parse_typed_value(kind, text)


def test_atomic_save_failure_preserves_original(tmp_path, monkeypatch):
    import jira_test.gui.document as document

    path = tmp_path / "suite.yaml"
    path.write_text(yaml.safe_dump(case()))
    doc = ScenarioDocument()
    doc.load(path)
    changed = deepcopy(doc.cases[0])
    changed["description"] = "changed"
    doc.set_case(0, changed)
    original = path.read_text()

    def fail(*args):
        raise OSError("disk error")

    monkeypatch.setattr(document.os, "replace", fail)
    with pytest.raises(OSError):
        doc.save()
    assert path.read_text() == original
    assert doc.dirty
    assert list(tmp_path.iterdir()) == [path]
