"""Opt-in desktop smoke: run with Python containing Tk and desktop access."""

import tkinter as tk
from pathlib import Path
from tempfile import TemporaryDirectory

from jira_test.catalog import Catalog, Observation
from jira_test.gui.catalog_view import CatalogPanel
from jira_test.gui.profiles import ProfilePanel
from jira_test.gui.results import ResultsPanel


class App:
    def __init__(self, workspace):
        self.workspace = workspace
        self.profile = {
            "base_url": "https://jira.invalid",
            "source_project": "SRC",
            "test_project": "TEST",
        }
        self.catalog = Catalog(
            "SRC", "", observations=[Observation("1", "create", "summary", "api")]
        )
        self.catalog_path = None
        self.buttons = []

    def credentials(self):
        return {"username": "", "password": ""}

    def status(self, text):
        pass

    def register_job_button(self, button):
        self.buttons.append(button)

    def collect_config(self):
        return self.profile_panel.collect_config()


def main():
    root = tk.Tk()
    root.geometry("1280x850")
    with TemporaryDirectory() as directory:
        app = App(Path(directory))
        app.profile_panel = ProfilePanel(root, app)
        assert app.profile_panel.collect_config()["source_project"] == "SRC"
        assert set(app.profile_panel.credentials()) == {"username", "password"}
        catalog = CatalogPanel(root, app)
        assert len(catalog.tree.get_children()) == 1
        catalog.search.set("missing")
        assert not catalog.tree.get_children()
        catalog.search.set("summary")
        assert len(catalog.tree.get_children()) == 1
        run_dir = app.workspace / ".jira-test-studio" / "runs" / "run-one"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text('{"outcome":"failed"}')
        (run_dir / "test-results.json").write_text(
            '{"results":[{"id":"test.py::test_one","outcome":"failed","kind":"python"}]}'
        )
        results = ResultsPanel(root, app)
        assert len(results.result_tree.get_children()) == 1
        for panel in (app.profile_panel, catalog, results):
            panel.pack(fill="both", expand=True)
            root.update()
            assert panel.winfo_reqwidth() <= 1280, panel.winfo_reqwidth()
            panel.pack_forget()
        assert len(app.buttons) == 6
    root.destroy()
    print("Tk smoke passed: profile, filters, Python results, panel layout")


if __name__ == "__main__":
    main()
