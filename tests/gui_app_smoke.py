"""Real Tk + worker integration; explicitly run with a desktop and Tk-enabled Python."""

import time
import tkinter as tk
from unittest.mock import patch

import pytest

from jira_test.gui.app import StudioApp


@pytest.fixture
def app(tmp_path):
    root = tk.Tk()
    studio = StudioApp(root, tmp_path)
    with (
        patch("tkinter.messagebox.showerror", side_effect=AssertionError),
        patch("tkinter.messagebox.showinfo"),
    ):
        yield studio
    root.destroy()


def finish(app):
    deadline = time.monotonic() + 20
    while app.active_operation or app.jobs.running:
        app.root.update()
        assert time.monotonic() < deadline, "worker did not finish"
        time.sleep(0.02)
    app.root.update()


def test_demo_run_history_and_rerun(app):
    app.load_demo()
    assert len(app.run_panel.entries) == 1
    app.run_panel.run_selected()
    finish(app)
    run = app.results_panel.runs[0]
    assert run["manifest"]["outcome"] == "completed"
    assert len(run["results"]) == 1
    assert run["results"][0]["outcome"] == "passed"
    assert not run["incomplete"]
    assert next(iter(app.run_panel.entries.values()))["outcome"] == "passed"
    app.rerun(run["manifest"])
    finish(app)
    assert len(app.results_panel.runs) == 2
    assert app.results_panel.runs[0]["manifest"]["outcome"] == "completed"
    assert app.results_panel.runs[0]["results"][0]["path"] == str(
        app.workspace / "studio-demo" / "demo.yaml"
    )


def test_collect_python_failure_and_failed_rerun(app):
    source = app.workspace / "test_example.py"
    source.write_text("def test_pass():\n    assert True\n\ndef test_fail():\n    assert False\n")
    app.run_panel.add_paths([source])
    finish(app)
    assert len(app.run_panel.entries) == 2
    app.run_panel.run_all()
    finish(app)
    run = app.results_panel.runs[0]
    assert {r["outcome"] for r in run["results"]} == {"passed", "failed"}
    app.rerun(run["manifest"], failed_only=True)
    finish(app)
    latest = app.results_panel.runs[0]
    assert app.results_panel.current["directory"] == latest["directory"]
    assert len(latest["results"]) == 1
    assert latest["results"][0]["outcome"] == "failed"
    assert latest["manifest"]["request"]["python_tests"][0].endswith("::test_fail")


def test_navigation_and_layout(app):
    from jira_test.gui.app import PAGES

    for name in PAGES:
        app.show_page(name)
        app.root.update()
        assert app.current_page == name
        assert app.panels[name].winfo_width() > 800
        assert app.panels[name].winfo_reqwidth() <= 1120
    assert not app.designer_panel.document.dirty
