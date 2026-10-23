"""Test selection and live progress without running automation in the Tk thread."""

import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..errors import JiraTestError
from ..scenario import load_scenarios


class RunPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=16)
        self.app = app
        self.entries: dict[str, dict] = {}
        self.filter = tk.StringVar()
        self.summary = tk.StringVar(value="Henüz test eklenmedi.")
        self.target = tk.StringVar()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=3)
        self.rowconfigure(6, weight=2)
        ttk.Label(self, text="Test çalıştırma", style="Title.TLabel").grid(sticky="w")
        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, sticky="ew", pady=(12, 8))
        for label, command in [
            ("Dosya ekle", self.add_files),
            ("Klasör ekle", self.add_folder),
            ("Listeyi yenile", self.reload),
            ("Tümünü seç", lambda: self.select_all(True)),
            ("Seçimi kaldır", lambda: self.select_all(False)),
            ("Listeden çıkar", self.remove),
        ]:
            ttk.Button(toolbar, text=label, command=command).pack(side="left", padx=(0, 5))
        search = ttk.Frame(self)
        search.grid(row=2, sticky="ew", pady=(0, 8))
        ttk.Label(search, text="Test ara").pack(side="left")
        ttk.Entry(search, textvariable=self.filter).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Label(search, textvariable=self.summary).pack(side="right")
        self.filter.trace_add("write", lambda *_: self.refresh())
        container = ttk.Frame(self)
        container.grid(row=3, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            container,
            columns=("selected", "kind", "name", "path", "outcome"),
            show="headings",
            selectmode="extended",
        )
        for key, label, width in [
            ("selected", "Koş", 55),
            ("kind", "Tür", 70),
            ("name", "Test", 220),
            ("path", "Dosya", 270),
            ("outcome", "Son durum", 110),
        ]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=45, stretch=key in {"name", "path"})
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        horizontal = ttk.Scrollbar(container, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=horizontal.set)
        self.tree.bind("<space>", self.toggle)
        self.tree.bind("<Double-1>", self.edit_selected)
        self.tree.bind("<Button-1>", self._click_selection)
        actions = ttk.Frame(self)
        actions.grid(row=4, sticky="ew", pady=10)
        for label, callback in [
            ("Seçilenleri çalıştır", self.run_selected),
            ("Tümünü çalıştır", self.run_all),
        ]:
            button = ttk.Button(actions, text=label, command=callback)
            button.pack(side="left", padx=(0, 8))
            app.register_job_button(button)
        ttk.Button(actions, text="Testi düzenle / kaynağı aç", command=self.edit_selected).pack(
            side="left"
        )
        ttk.Button(actions, text="Durdur", command=app.cancel_job).pack(side="right")
        ttk.Label(self, textvariable=self.target, wraplength=950).grid(row=5, sticky="w")
        self.console = tk.Text(self, height=9, wrap="word", state="disabled", font="TkFixedFont")
        self.console.grid(row=6, sticky="nsew", pady=(10, 0))
        self.refresh_target()

    def refresh_target(self, request=None):
        if request is not None:
            self._execution_request = {
                "config": deepcopy(request.get("config", {})),
                "rerun_of": request.get("rerun_of"),
            }
        elif getattr(self.app, "active_operation", "") == "run":
            request = self._execution_request
        if request is None:
            try:
                config = (
                    self.app.profile_panel.collect_config()
                    if hasattr(self.app, "profile_panel")
                    else self.app.profile
                )
            except JiraTestError:
                self.target.set("Hedef belirlenemedi: bağlantı profilindeki hataları düzeltin.")
                return
        else:
            config = request.get("config", {})
        project = config.get("test_project", "—")
        address = config.get("base_url", "—")
        source = (
            "Geçmiş koşunun ayarları" if request and request.get("rerun_of") else "Güncel profil"
        )
        self.target.set(
            f"Hedef Jira: {address} · Test projesi: {project} · {source}. "
            "Canlı testler kayıt oluşturabilir ve değiştirebilir; "
            "oluşturulan kayıtlar otomatik silinmez. Çift tık: düzenle. "
            "Boşluk: koşum seçimini değiştir."
        )

    def add_files(self):
        files = filedialog.askopenfilenames(
            parent=self,
            initialdir=self.app.workspace,
            title="Test dosyalarını seç",
            filetypes=[("Test dosyaları", "*.yaml *.yml *.py"), ("Tüm dosyalar", "*")],
        )
        self.add_paths([Path(p) for p in files])

    def add_folder(self):
        folder = filedialog.askdirectory(parent=self, initialdir=self.app.workspace)
        if not folder:
            return
        paths = [p for p in Path(folder).rglob("*") if self._is_test_file(p)]
        self.add_paths(paths)

    @staticmethod
    def _is_test_file(path):
        if any(part.startswith(".") or part in {"__pycache__", "artifacts"} for part in path.parts):
            return False
        return path.suffix.lower() in {".yaml", ".yml"} or (
            path.suffix == ".py" and (path.name.startswith("test_") or path.stem.endswith("_test"))
        )

    def add_paths(self, paths):
        if self.app.jobs.running:
            messagebox.showinfo("İşlem sürüyor", "Test eklemek için aktif işin bitmesini bekleyin.")
            return
        python_files = []
        errors = []
        for path in paths:
            path = path.resolve()
            if path.suffix == ".py":
                python_files.append(str(path))
                continue
            try:
                cases = load_scenarios(path)
                old = {k: v for k, v in self.entries.items() if v["path"] == str(path)}
                self.entries = {k: v for k, v in self.entries.items() if v["path"] != str(path)}
                for case in cases:
                    key = f"{path}::{case.id}"
                    self.entries[key] = {
                        "path": str(path),
                        "id": case.id,
                        "name": case.id,
                        "kind": "yaml",
                        "selected": old.get(key, {}).get("selected", True),
                        "outcome": "—",
                        "catalog_only": case.catalog_only,
                    }
            except (JiraTestError, OSError) as exc:
                errors.append(f"{path.name}: {exc}")
        self.refresh()
        if errors:
            messagebox.showerror("Dosya doğrulama", "\n".join(errors), parent=self)
        if python_files:
            self.app.start_job("collect", {"paths": sorted(set(python_files))})

    def add_collected(self, tests, requested_paths=()):
        paths = {str(Path(item["path"]).resolve()) for item in tests}
        paths.update(str(Path(path).resolve()) for path in requested_paths)
        old = dict(self.entries)
        self.entries = {
            k: v for k, v in self.entries.items() if v["kind"] != "python" or v["path"] not in paths
        }
        for item in tests:
            key = item.get("selector", item["nodeid"])
            self.entries[key] = {
                **item,
                "kind": "python",
                "selected": old.get(key, {}).get("selected", True),
                "outcome": "—",
                "id": key,
            }
        self.refresh()

    def reload(self):
        self.add_paths([Path(p) for p in sorted({e["path"] for e in self.entries.values()})])

    def refresh(self):
        selected_rows = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        query = self.filter.get().casefold()
        for key, entry in self.entries.items():
            if query and query not in f"{entry['name']} {entry['path']}".casefold():
                continue
            self.tree.insert(
                "",
                "end",
                iid=key,
                values=(
                    "✓" if entry["selected"] else "",
                    entry["kind"].upper(),
                    entry["name"],
                    entry["path"],
                    entry.get("outcome", "—"),
                ),
            )
        for key in selected_rows:
            if self.tree.exists(key):
                self.tree.selection_add(key)
        count = sum(bool(e["selected"]) for e in self.entries.values())
        self.summary.set(f"{len(self.entries)} test · {count} seçili")

    def select_all(self, selected):
        for key in self.tree.get_children():
            self.entries[key]["selected"] = selected
        self.refresh()

    def toggle(self, event=None):
        for key in self.tree.selection():
            self.entries[key]["selected"] = not self.entries[key]["selected"]
        self.refresh()
        return "break"

    def _click_selection(self, event):
        key = self.tree.identify_row(event.y)
        if key and self.tree.identify_column(event.x) == "#1":
            self.entries[key]["selected"] = not self.entries[key]["selected"]
            self.refresh()
            return "break"
        return None

    def remove(self):
        for key in self.tree.selection():
            self.entries.pop(key, None)
        self.refresh()

    def edit_selected(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        entry = self.entries[selection[0]]
        if entry["kind"] == "yaml":
            self.app.open_designer(path=Path(entry["path"]))
        else:
            self.app.open_source(Path(entry["path"]))

    def run_all(self):
        self._run(list(self.entries.values()))

    def run_selected(self):
        self._run([e for e in self.entries.values() if e["selected"]])

    def _run(self, entries):
        if not entries:
            messagebox.showinfo("Test seçimi", "Çalıştırılacak en az bir test seçin.", parent=self)
            return
        payload = {
            "yaml_cases": [
                {"path": e["path"], "id": e["id"]} for e in entries if e["kind"] == "yaml"
            ],
            "python_tests": [
                e.get("selector", e["nodeid"]) for e in entries if e["kind"] == "python"
            ],
        }
        if self.app.start_job("run", payload):
            for entry in entries:
                entry["outcome"] = "Bekliyor"
            self.refresh()

    def log(self, text):
        self.console.configure(state="normal")
        self.console.insert("end", text.rstrip() + "\n")
        # Keep UI memory bounded while the complete journal stays on disk.
        lines = int(self.console.index("end-1c").split(".")[0])
        if lines > 2000:
            self.console.delete("1.0", f"{lines - 1500}.0")
        self.console.see("end")
        self.console.configure(state="disabled")

    def progress(self, data):
        for key, entry in self.entries.items():
            matches_node = (
                data["selector"] == entry.get("selector", key)
                if data.get("selector")
                else data.get("nodeid") in {key, entry.get("nodeid", key)}
            )
            matches_case = (
                data.get("scenario_id") == entry.get("id")
                and entry["kind"] == "yaml"
                and (not data.get("path") or data["path"] == entry["path"])
            )
            if matches_node or matches_case:
                entry["outcome"] = data.get("outcome") or "Çalışıyor"
        self.refresh()
