"""Visual scenario designer sharing the CLI's safe YAML and validation rules."""

import json
import tkinter as tk
from copy import deepcopy
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import yaml

from ..errors import ScenarioError
from ..scenario import ACTIONS, CHECKS
from .document import ScenarioDocument
from .widgets import MappingDialog, PathDialog, RecordDialog

BOOLEAN_CHECKS = {
    "visible",
    "editable",
    "required",
    "accepted",
    "catalog_exists",
    "catalog_required",
    "transition_available",
}


def new_scenario():
    return {
        "id": "yeni-senaryo",
        "description": "",
        "fixture": {"issue_type": "10001", "mode": "new", "fields": {}},
        "steps": [{"action": "open", "screen": "create"}],
        "expect": [{"check": "visible", "field": "summary", "value": True}],
    }


class DesignerPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=10)
        self.app = app
        self.document = ScenarioDocument()
        self.current = 0
        self._refreshing = False
        self._form_dirty = False
        self._warning_shown = False
        self._tab = 0
        self.error = tk.StringVar()
        self.filename = tk.StringVar(value="Yeni senaryo")
        self._build()
        self.load()
        self.bind_all("<Control-s>", self._save_shortcut, add="+")

    def _build(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x")
        for label, command in (
            ("Dosya aç", self.open_file),
            ("Kaydet", self.save),
            ("Farklı kaydet", lambda: self.save(save_as=True)),
            ("Doğrula", self.validate),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side="left", padx=(0, 5))
        ttk.Label(toolbar, textvariable=self.filename).pack(side="left", padx=10)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, pady=8)
        self.visual = ttk.Frame(self.notebook)
        self.yaml_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.visual, text="Görsel düzenleyici")
        self.notebook.add(self.yaml_tab, text="YAML")
        self.notebook.bind("<<NotebookTabChanged>>", self._tab_changed)
        self.raw = tk.Text(self.yaml_tab, wrap="none", undo=True)
        scroll = ttk.Scrollbar(self.yaml_tab, command=self.raw.yview)
        self.raw.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.raw.pack(fill="both", expand=True)
        self.raw.bind("<<Modified>>", self._raw_modified)
        ttk.Label(self, textvariable=self.error, foreground="#a02020", wraplength=1000).pack(
            fill="x",
        )
        panes = ttk.Panedwindow(self.visual, orient="horizontal")
        panes.pack(fill="both", expand=True)
        sidebar = ttk.Frame(panes, padding=4)
        editor = ttk.Frame(panes, padding=6)
        panes.add(sidebar, weight=1)
        panes.add(editor, weight=4)
        ttk.Label(sidebar, text="Dosyadaki senaryolar").pack(anchor="w")
        self.cases = tk.Listbox(sidebar, width=24, exportselection=False)
        self.cases.pack(fill="both", expand=True)
        self.cases.bind("<<ListboxSelect>>", self._select_case)
        for text, command in (
            ("Yeni", self.add_case),
            ("Kopyala", self.copy_case),
            ("Kaldır", self.remove_case),
        ):
            ttk.Button(sidebar, text=text, command=command).pack(fill="x", pady=2)
        meta = ttk.LabelFrame(editor, text="Senaryo ve fixture", padding=8)
        meta.pack(fill="x")
        meta.columnconfigure(1, weight=1)
        meta.columnconfigure(3, weight=1)
        self.metadata = {}
        for index, (key, label) in enumerate(
            (
                ("id", "Senaryo kimliği"),
                ("issue_type", "İş türü kimliği"),
                ("description", "Açıklama"),
                ("mode", "Fixture modu"),
                ("catalog", "Katalog dosyası"),
            )
        ):
            row, column = divmod(index, 2)
            variable = tk.StringVar()
            variable.trace_add("write", self._metadata_modified)
            self.metadata[key] = variable
            ttk.Label(meta, text=label).grid(row=row, column=column * 2, sticky="w", padx=4)
            entry = ttk.Combobox(meta, textvariable=variable, width=28)
            entry.grid(row=row, column=column * 2 + 1, sticky="ew", pady=3)
            if key == "mode":
                entry.configure(values=("new", "none"), state="readonly")
            if key == "issue_type":
                self.issue_type_entry = entry
        controls = ttk.Frame(meta)
        controls.grid(row=3, column=0, columnspan=4, sticky="w", pady=5)
        for text, command in (
            ("Alanlar…", self.edit_fields),
            ("Üst iş…", self.edit_parent),
            ("Geçiş yolu…", self.edit_path),
            ("Üst işi kaldır", self.remove_parent),
            ("Bilgileri uygula", self.apply_metadata),
        ):
            ttk.Button(controls, text=text, command=command).pack(side="left", padx=2)
        ttk.Label(meta, text="Alanlar ve üst iş: kimlik + açık tür; geçiş yolu sıralıdır.").grid(
            row=4,
            column=0,
            columnspan=4,
            sticky="w",
        )
        lists = ttk.Panedwindow(editor, orient="vertical")
        lists.pack(fill="both", expand=True, pady=6)
        self.operation_lists = {}
        self.operation_kinds = {}
        for section, label, definitions in (
            ("steps", "Adımlar", ACTIONS),
            ("expect", "Kontroller", CHECKS),
        ):
            frame = ttk.LabelFrame(lists, text=label, padding=5)
            lists.add(frame, weight=1)
            table = ttk.Frame(frame)
            table.pack(fill="both", expand=True)
            tree = ttk.Treeview(table, columns=("kind", "detail"), show="headings", height=5)
            scroll = ttk.Scrollbar(table, command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            tree.heading("kind", text="İşlem")
            tree.heading("detail", text="Parametreler")
            tree.column("kind", width=150, stretch=False)
            tree.column("detail", width=500)
            tree.pack(fill="both", expand=True)
            tree.bind("<Double-1>", partial(self._edit_operation_event, section))
            self.operation_lists[section] = tree
            actions = ttk.Frame(frame)
            actions.pack(fill="x", pady=(5, 0))
            selected = tk.StringVar(value=next(iter(definitions)))
            self.operation_kinds[section] = selected
            ttk.Combobox(
                actions,
                textvariable=selected,
                values=tuple(definitions),
                state="readonly",
                width=21,
            ).pack(side="left")
            commands = (
                ("Ekle", lambda section=section: self.add_operation(section)),
                ("Düzenle", lambda section=section: self.edit_operation(section)),
                ("Kopyala", lambda section=section: self.copy_operation(section)),
                ("Kaldır", lambda section=section: self.remove_operation(section)),
                ("↑", lambda section=section: self.move_operation(section, -1)),
                ("↓", lambda section=section: self.move_operation(section, 1)),
            )
            for text, command in commands:
                ttk.Button(actions, text=text, command=command, width=8).pack(side="left", padx=2)

    def _save_shortcut(self, event):
        if self.winfo_ismapped():
            self.save()
            return "break"
        return None

    def refresh_catalog(self):
        catalog = getattr(self.app, "catalog", None)
        self.suggestions: dict[str, list[str] | tuple[str, ...]] = {
            "screen": ("create", "view", "edit", "transition"),
            "source": ("api", "ui"),
        }
        if catalog:
            self.suggestions.update(
                {
                    "field": sorted({item.field for item in catalog.observations}),
                    "issue_type": [str(item["id"]) for item in catalog.issue_types if "id" in item],
                    "id": sorted({str(item["id"]) for item in catalog.transitions if "id" in item}),
                    "status": sorted({item.status for item in catalog.observations if item.status}),
                }
            )
            self.suggestions["transition"] = self.suggestions["id"]
        self.issue_type_entry.configure(values=self.suggestions.get("issue_type", ()))

    def load(self, path: Path | None = None, scenario: dict | None = None):
        draft_error = None
        try:
            candidate = ScenarioDocument()
            if path:
                candidate.load(Path(path))
            else:
                source = yaml.safe_dump(
                    scenario if scenario is not None else new_scenario(),
                    sort_keys=False,
                    allow_unicode=True,
                )
                try:
                    candidate.load_text(source)
                except ScenarioError as exc:
                    if scenario is None:
                        raise
                    candidate.load_text(yaml.safe_dump(new_scenario(), sort_keys=False))
                    candidate.yaml_draft = source
                    draft_error = exc
                if scenario is not None:
                    # Explicit templates contain user data; the startup placeholder does not.
                    candidate._saved_text = ""
        except (OSError, ValueError, ScenarioError) as exc:
            self._show_error(exc)
            return False
        self.document = candidate
        self.current = 0
        self._warning_shown = False
        self._form_dirty = False
        self.refresh_catalog()
        self._refresh()
        if draft_error:
            self._tab = 1
            self.notebook.select(1)
            self._show_error(draft_error)
        else:
            self.error.set("")
        return True

    def _show_error(self, exc):
        self.error.set(str(exc))
        self.app.status("Senaryo işlemi tamamlanamadı; hata ayrıntısını kontrol edin.")

    def _metadata_modified(self, *_):
        if not self._refreshing:
            self._form_dirty = True
            self._update_filename()

    def _raw_modified(self, event=None):
        if self.raw.edit_modified():
            if not self._refreshing:
                self.document.yaml_draft = self.raw.get("1.0", "end-1c")
                self._update_filename()
            self.raw.edit_modified(False)

    def _update_filename(self):
        name = str(self.document.path) if self.document.path else "Kaydedilmemiş dosya"
        self.filename.set(name + (" *" if self.document.dirty or self._form_dirty else ""))

    def _refresh(self):
        self._refreshing = True
        try:
            self.cases.delete(0, "end")
            for case in self.document.cases:
                self.cases.insert("end", case["id"])
            self.cases.selection_set(self.current)
            case = self.document.cases[self.current]
            for key, variable in self.metadata.items():
                value = (
                    case.get(key, "")
                    if key in {"id", "description"}
                    else case["fixture"].get(
                        key,
                        "new" if key == "mode" else "",
                    )
                )
                variable.set(value)
            for section, tree in self.operation_lists.items():
                tree.delete(*tree.get_children())
                kind = "action" if section == "steps" else "check"
                for index, operation in enumerate(case[section]):
                    detail = {key: value for key, value in operation.items() if key != kind}
                    tree.insert(
                        "",
                        "end",
                        iid=str(index),
                        values=(
                            operation[kind],
                            json.dumps(
                                detail,
                                ensure_ascii=False,
                            ),
                        ),
                    )
            self.raw.delete("1.0", "end")
            self.raw.insert("1.0", self.document.yaml_draft)
            self.raw.edit_modified(False)
            self._form_dirty = False
            self._update_filename()
        finally:
            self._refreshing = False

    def _visual_warning(self):
        if not self._warning_shown and self.document.path and not self.document.visual_rewritten:
            messagebox.showinfo(
                "YAML biçimi",
                "Görsel değişiklik YAML biçimini yeniden oluşturur; "
                "yorumlar ve özel biçimlendirme korunmaz. Değişiklikler Kaydet ile yazılır.",
                parent=self,
            )
            self._warning_shown = True

    def _set_case(self, case):
        if case == self.document.cases[self.current]:
            return True
        try:
            self._visual_warning()
            self.document.set_case(self.current, case)
        except (ValueError, ScenarioError) as exc:
            self._show_error(exc)
            return False
        self.error.set("")
        self._refresh()
        return True

    def apply_metadata(self):
        if not self._form_dirty:
            return True
        case = deepcopy(self.document.cases[self.current])
        for key, variable in self.metadata.items():
            value = variable.get()
            target = case if key in {"id", "description"} else case["fixture"]
            if key == "catalog" and not value:
                target.pop(key, None)
            elif target.get(key, "new" if key == "mode" else "") != value:
                target[key] = value
        if case == self.document.cases[self.current]:
            self._form_dirty = False
            self._update_filename()
            return True
        return self._set_case(case)

    def _select_case(self, event=None):
        selected = self.cases.curselection()
        if not selected or selected[0] == self.current:
            return
        index = selected[0]
        if self.apply_metadata():
            self.current = index
            self._refresh()
        else:
            self.cases.selection_clear(0, "end")
            self.cases.selection_set(self.current)

    def _tab_changed(self, event=None):
        selected = self.notebook.index("current")
        if selected == self._tab:
            return
        if selected == 1:
            if not self.apply_metadata():
                self.notebook.select(0)
                return
        else:
            try:
                self.document.apply_yaml(self.raw.get("1.0", "end-1c"))
                self.current = min(self.current, len(self.document.cases) - 1)
                self.error.set("")
                self._refresh()
            except (ValueError, ScenarioError) as exc:
                self._show_error(exc)
                self.notebook.select(1)
                return
        self._tab = selected

    def _prepare(self):
        if self.notebook.index("current") == 1:
            try:
                self.document.apply_yaml(self.raw.get("1.0", "end-1c"))
            except (ValueError, ScenarioError) as exc:
                self._show_error(exc)
                return False
        return self.apply_metadata()

    def open_file(self):
        if not self.can_leave():
            return
        path = filedialog.askopenfilename(
            parent=self,
            initialdir=self.app.workspace,
            filetypes=[("YAML", "*.yaml *.yml"), ("Tüm dosyalar", "*")],
        )
        if path:
            self.load(Path(path))

    def save(self, save_as=False):
        if not self._prepare():
            return False
        path = self.document.path
        if save_as or path is None:
            selected = filedialog.asksaveasfilename(
                parent=self,
                initialdir=path.parent if path else self.app.workspace,
                initialfile=path.name if path else "senaryolar.yaml",
                defaultextension=".yaml",
                filetypes=[("YAML", "*.yaml *.yml")],
            )
            if not selected:
                return False
            path = Path(selected)
        try:
            self.document.save(path)
        except (OSError, ValueError, ScenarioError) as exc:
            self._show_error(exc)
            return False
        self._update_filename()
        self.error.set("")
        self.app.status(f"Kaydedildi: {path}")
        return True

    def validate(self):
        if not self._prepare():
            return False
        try:
            self.document.validate()
        except (ValueError, ScenarioError) as exc:
            self._show_error(exc)
            return False
        self.error.set("")
        self.app.status(f"Doğrulandı: {len(self.document.cases)} senaryo.")
        return True

    def can_leave(self):
        if self.notebook.index("current") == 1:
            self.document.yaml_draft = self.raw.get("1.0", "end-1c")
        if not (self.document.dirty or self._form_dirty):
            return True
        answer = messagebox.askyesnocancel(
            "Kaydedilmemiş değişiklikler", "Değişiklikler kaydedilsin mi?", parent=self
        )
        if answer is None:
            return False
        return self.save() if answer else True

    def add_case(self):
        if self.apply_metadata():
            self._visual_warning()
            self.current = self.document.add_case(new_scenario())
            self._refresh()

    def copy_case(self):
        if self.apply_metadata():
            self._visual_warning()
            self.current = self.document.add_case(self.document.cases[self.current])
            self._refresh()

    def remove_case(self):
        if len(self.document.cases) == 1:
            self.error.set("Dosyada en az bir senaryo kalmalı.")
            return
        if not self.apply_metadata():
            return
        if messagebox.askyesno(
            "Senaryoyu kaldır", "Seçili senaryo dosyadan kaldırılsın mı?", parent=self
        ):
            self._visual_warning()
            self.document.remove_case(self.current)
            self.current = min(self.current, len(self.document.cases) - 1)
            self._refresh()

    def edit_fields(self):
        if not self.apply_metadata():
            return
        case = deepcopy(self.document.cases[self.current])
        result = MappingDialog(
            self,
            "Fixture alanları",
            case["fixture"].get("fields", {}),
            self.suggestions.get("field", ()),
        ).show()
        if result is not None:
            case["fixture"]["fields"] = result
            self._set_case(case)

    def edit_parent(self):
        if not self.apply_metadata():
            return
        case = deepcopy(self.document.cases[self.current])
        result = RecordDialog(
            self,
            "Üst iş",
            case["fixture"].get("parent") or {"issue_type": ""},
            {"issue_type", "fields"},
            {"issue_type"},
            self.suggestions,
        ).show()
        if result is not None:
            case["fixture"]["parent"] = result
            self._set_case(case)

    def remove_parent(self):
        if self.apply_metadata():
            case = deepcopy(self.document.cases[self.current])
            case["fixture"].pop("parent", None)
            self._set_case(case)

    def edit_path(self):
        if not self.apply_metadata():
            return
        case = deepcopy(self.document.cases[self.current])
        result = PathDialog(self, case["fixture"].get("path", []), self.suggestions).show()
        if result is not None:
            case["fixture"]["path"] = result
            self._set_case(case)

    def _selected_operation(self, section):
        selection = self.operation_lists[section].selection()
        return int(selection[0]) if selection else None

    def _operation_dialog(self, section, value):
        key, definitions = ("action", ACTIONS) if section == "steps" else ("check", CHECKS)
        allowed, required = definitions[value[key]]
        return RecordDialog(self, value[key], value, allowed, required, self.suggestions).show()

    def add_operation(self, section):
        if not self.apply_metadata():
            return
        kind = self.operation_kinds[section].get()
        key = "action" if section == "steps" else "check"
        value: dict[str, Any] = {key: kind}
        if kind in BOOLEAN_CHECKS:
            value["value"] = True
        if kind == "open" or kind.startswith("catalog_"):
            value["screen"] = "create"
        result = self._operation_dialog(section, value)
        if result is not None:
            case = deepcopy(self.document.cases[self.current])
            case[section].append(result)
            self._set_case(case)

    def _edit_operation_event(self, section, event):
        self.edit_operation(section)

    def edit_operation(self, section):
        index = self._selected_operation(section)
        if index is None or not self.apply_metadata():
            return
        case = deepcopy(self.document.cases[self.current])
        result = self._operation_dialog(section, case[section][index])
        if result is not None:
            case[section][index] = result
            self._set_case(case)

    def copy_operation(self, section):
        index = self._selected_operation(section)
        if index is not None and self.apply_metadata():
            case = deepcopy(self.document.cases[self.current])
            case[section].insert(index + 1, deepcopy(case[section][index]))
            self._set_case(case)

    def remove_operation(self, section):
        index = self._selected_operation(section)
        if index is not None and self.apply_metadata():
            case = deepcopy(self.document.cases[self.current])
            case[section].pop(index)
            self._set_case(case)

    def move_operation(self, section, delta):
        index = self._selected_operation(section)
        if index is None or not self.apply_metadata():
            return
        case = deepcopy(self.document.cases[self.current])
        target = index + delta
        if 0 <= target < len(case[section]):
            case[section].insert(target, case[section].pop(index))
            if self._set_case(case):
                self.operation_lists[section].selection_set(str(target))
