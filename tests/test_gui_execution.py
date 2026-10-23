"""Exercise GUI dispatch without a display; only Tk widget boundaries are replaced."""

import subprocess
import sys


def test_run_target_matches_dispatched_request_and_survives_navigation():
    script = """
import sys
from types import ModuleType, SimpleNamespace

# No widgets are constructed: import the controllers with inert Tk base classes.
tk = ModuleType("tkinter")
tk.Tk = tk.Toplevel = object
tk.ttk = SimpleNamespace(Frame=object)
tk.filedialog = tk.messagebox = tk.simpledialog = SimpleNamespace()
sys.modules["tkinter"] = tk
from jira_test.gui.app import StudioApp
from jira_test.gui.run_view import RunPanel

app = object.__new__(StudioApp)
app.profile = {"base_url": "https://current.invalid", "test_project": "CURRENT"}
pending = {"base_url": "https://pending.invalid", "test_project": "PENDING"}
app.profile_panel = SimpleNamespace(collect_config=lambda: dict(pending))
app.credentials = lambda: {}
app.active_operation = ""
app.catalog_path = None
app.job_buttons = []
app.cancel_button = SimpleNamespace(state=lambda _: None)
app.progress = SimpleNamespace(start=lambda _: None)
app.status_var = SimpleNamespace(get=lambda: "running")
app.status = lambda _: None
app.root = SimpleNamespace(update_idletasks=lambda: None)
shown = []
panel = SimpleNamespace(app=app, target=SimpleNamespace(set=shown.append), log=lambda _: None)
panel.refresh_target = lambda *args: RunPanel.refresh_target(panel, *args)
app.run_panel = panel
app.show_page = lambda _: panel.refresh_target()
sent = []
app.jobs = SimpleNamespace(running=False, start=lambda operation, request:
                          sent.append((request, shown[-1])) or True)

panel.refresh_target()
assert "PENDING" in shown[-1] and "https://pending.invalid" in shown[-1]
historical = {"base_url": "https://history.invalid", "test_project": "HISTORY"}
assert app.start_job("run", {"config": historical, "rerun_of": "old-run"})
assert sent[-1][0]["config"] == historical
assert "HISTORY" in sent[-1][1] and "https://history.invalid" in sent[-1][1]
assert "Geçmiş" in sent[-1][1]
pending["test_project"] = "CHANGED"
panel.refresh_target()
assert "HISTORY" in shown[-1] and "CHANGED" not in shown[-1]
app.active_operation = ""
assert app.start_job("run", {})
assert "CHANGED" in sent[-1][1]
assert sent[-1][0]["config"]["test_project"] == "CHANGED"
"""
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stdout + result.stderr
