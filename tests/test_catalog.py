from jira_test.catalog import Catalog, Observation
from jira_test.report import render_catalog


def test_sources_do_not_overwrite_each_other():
    catalog = Catalog(project="SRC", user="test-user")
    catalog.add(
        Observation(issue_type="1", screen="create", field="summary", source="api", required=True)
    )
    catalog.add(
        Observation(
            issue_type="1",
            screen="create",
            field="summary",
            source="ui",
            required=False,
            visible=True,
        )
    )
    assert len(catalog.query(field="summary")) == 2
    assert catalog.query(source="api")[0].required is True
    assert catalog.query(source="ui")[0].required is False


def test_html_escapes_untrusted_jira_text():
    catalog = Catalog(project="<script>alert(1)</script>", user="test-user")
    catalog.add(
        Observation(
            issue_type="1",
            screen="create",
            field="summary",
            source="api",
            name="<img src=x onerror=alert(1)>",
        )
    )
    html = render_catalog(catalog)
    assert "<img src=x" not in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;img" in html


def test_catalog_roundtrip_and_unknown_context(tmp_path):
    catalog = Catalog(project="SRC", user="test-user")
    catalog.gaps.append({"context": "issue_type:2", "reason": "no accessible issue"})
    path = tmp_path / "catalog.json"
    catalog.save(path)
    restored = Catalog.load(path)
    assert restored.query(field="customfield_42") == []
    assert restored.gaps == catalog.gaps
