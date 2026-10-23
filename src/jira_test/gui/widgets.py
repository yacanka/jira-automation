"""Small reusable Tk editors for explicit values and structured scenario records."""

import json
import tkinter as tk
from copy import deepcopy
from tkinter import ttk
from typing import Any

from .document import parse_typed_value, value_kind


class TypedEditor(ttk.Frame):
    """Explicit types avoid silently converting numeric Jira IDs to numbers."""

    def __init__(self, parent, value: Any = "", fixed_type: str | None = None):
        super().__init__(parent)
        self.kind = tk.StringVar(value=fixed_type or value_kind(value))
        ttk.Combobox(
            self,
            textvariable=self.kind,
            values=("str", "number", "bool", "list", "object", "null"),
            state="disabled" if fixed_type else "readonly",
            width=12,
        ).pack(anchor="w")
        ttk.Label(
            self,
            text="str: metin · number: sayı · bool: true/false · list/object: JSON",
        ).pack(anchor="w")
        self.text = tk.Text(self, height=4, width=54, wrap="word", undo=True)
        self.text.pack(fill="both", expand=True)
        self.text.insert(
            "1.0",
            value
            if isinstance(value, str)
            else json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
            ),
        )

    def get(self):
        return parse_typed_value(self.kind.get(), self.text.get("1.0", "end-1c"))


class EditorDialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.result = None
        self.accepted = False
        self.error = tk.StringVar()
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)
        ttk.Label(self, textvariable=self.error, foreground="#a02020", wraplength=650).pack(
            fill="x",
            padx=12,
        )
        buttons = ttk.Frame(self, padding=10)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Uygula", command=self.accept).pack(side="right", padx=5)
        self.bind("<Escape>", lambda event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def accept(self):
        try:
            self.result = self.value()
        except (ValueError, TypeError) as exc:
            self.error.set(str(exc))
            return
        self.accepted = True
        self.destroy()

    def show(self):
        previous = self.grab_current()
        self.wait_visibility()
        self.grab_set()
        self.wait_window()
        if previous is not None and previous.winfo_exists():
            previous.grab_set()
        return self.result

    def value(self):
        raise NotImplementedError


class ValueDialog(EditorDialog):
    def __init__(self, parent, title, value, fixed_type=None):
        super().__init__(parent, title)
        self.editor = TypedEditor(self.body, value, fixed_type)
        self.editor.pack(fill="both", expand=True)

    def value(self):
        return self.editor.get()


class MappingDialog(EditorDialog):
    """Field mappings use individual key/value rows, with typed nested values."""

    def __init__(self, parent, title, value, suggestions=()):
        super().__init__(parent, title)
        self.mapping = deepcopy(value)
        self.suggestions = suggestions
        table = ttk.Frame(self.body)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("type", "value"), height=10)
        scroll = ttk.Scrollbar(table, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.heading("#0", text="Alan kimliği")
        self.tree.heading("type", text="Tür")
        self.tree.heading("value", text="Değer")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda event: self.edit())
        controls = ttk.Frame(self.body)
        controls.pack(fill="x")
        for label, command in (("Ekle", self.add), ("Düzenle", self.edit), ("Kaldır", self.remove)):
            ttk.Button(controls, text=label, command=command).pack(side="left", pady=5)
        self.refresh()

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for index, (key, value) in enumerate(self.mapping.items()):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                text=key,
                values=(value_kind(value), json.dumps(value, ensure_ascii=False)),
            )

    def selected(self):
        selection = self.tree.selection()
        return list(self.mapping)[int(selection[0])] if selection else None

    def add(self):
        dialog = RecordDialog(
            self,
            "Alan ekle",
            {"field": "", "value": ""},
            {"field", "value"},
            {"field", "value"},
            {"field": self.suggestions},
        )
        result = dialog.show()
        if result is None:
            return
        key = result["field"]
        if key in self.mapping:
            self.error.set("Bu alan zaten var; düzenlemeyi kullanın.")
            return
        self.mapping[key] = result["value"]
        self.refresh()

    def edit(self):
        key = self.selected()
        if key is None:
            return
        dialog = ValueDialog(self, f"Değer: {key}", self.mapping[key])
        result = dialog.show()
        # None is also a valid explicit null; distinguish cancellation by a flag.
        if getattr(dialog, "accepted", False):
            self.mapping[key] = result
            self.refresh()

    def remove(self):
        key = self.selected()
        if key is not None:
            del self.mapping[key]
            self.refresh()

    def value(self):
        return deepcopy(self.mapping)


LABELS = {
    "field": "Alan kimliği",
    "id": "Geçiş kimliği",
    "issue_type": "İş türü kimliği",
    "screen": "Ekran",
    "source": "Kaynak",
    "transition": "Geçiş kimliği",
    "status": "Durum",
    "error_contains": "Beklenen hata metni",
    "value": "Değer",
    "contains": "İçerdiği seçenekler",
    "fields": "Alan değerleri",
}


class RecordDialog(EditorDialog):
    """Build a record from the engine's allowed/required key definitions."""

    def __init__(self, parent, title, value, allowed, required, suggestions=None):
        super().__init__(parent, title)
        self.original = deepcopy(value)
        self.allowed = allowed
        self.required = required
        self.suggestions = suggestions or {}
        self.editors = {}
        self.enabled = {}
        self.mapping_values = {}
        self.body.columnconfigure(1, weight=1)
        for row, key in enumerate(sorted(allowed)):
            self.add_field(row, key, value)

    def add_field(self, row, key, value):
        enabled = tk.BooleanVar(value=key in value or key in self.required)
        self.enabled[key] = enabled
        label = LABELS.get(key, key) + (" *" if key in self.required else "")
        ttk.Checkbutton(
            self.body,
            text=label,
            variable=enabled,
            state="disabled" if key in self.required else "normal",
        ).grid(
            row=row,
            column=0,
            sticky="nw",
            padx=6,
            pady=6,
        )
        if key == "fields":
            self.mapping_values[key] = deepcopy(value.get(key, {}))
            ttk.Button(
                self.body, text="Alan tablosunu düzenle…", command=lambda: self.edit_mapping(key)
            ).grid(row=row, column=1, sticky="w")
        elif key in {"value", "contains"}:
            editor = TypedEditor(self.body, value.get(key, [] if key == "contains" else ""))
            editor.grid(row=row, column=1, sticky="ew", pady=4)
            self.editors[key] = editor
        else:
            variable = tk.StringVar(value=value.get(key, ""))
            options = self.suggestions.get(key, ())
            ttk.Combobox(self.body, textvariable=variable, values=options, width=45).grid(
                row=row,
                column=1,
                sticky="ew",
                pady=4,
            )
            self.editors[key] = variable

    def edit_mapping(self, key):
        result = MappingDialog(
            self, "Alan değerleri", self.mapping_values[key], self.suggestions.get("field", ())
        ).show()
        if result is not None:
            self.mapping_values[key] = result
            self.enabled[key].set(True)

    def value(self):
        result = {key: value for key, value in self.original.items() if key not in self.allowed}
        for key in self.allowed:
            if not self.enabled[key].get():
                continue
            value = (
                deepcopy(self.mapping_values[key]) if key == "fields" else self.editors[key].get()
            )
            if key in self.required and isinstance(value, str) and not value.strip():
                raise ValueError(f"{LABELS.get(key, key)} gerekli.")
            result[key] = value
        return result


class PathDialog(EditorDialog):
    def __init__(self, parent, path, suggestions):
        super().__init__(parent, "Fixture geçiş yolu")
        self.path = deepcopy(path)
        self.suggestions = suggestions
        self.rows = tk.Listbox(self.body, width=70, height=10, exportselection=False)
        self.rows.pack(fill="both", expand=True)
        self.rows.bind("<Double-1>", lambda event: self.edit())
        controls = ttk.Frame(self.body)
        controls.pack(fill="x")
        actions = (
            ("Ekle", self.add),
            ("Düzenle", self.edit),
            ("Kaldır", self.remove),
            ("Yukarı", lambda: self.move(-1)),
            ("Aşağı", lambda: self.move(1)),
        )
        for label, command in actions:
            ttk.Button(controls, text=label, command=command).pack(side="left")
        self.refresh()

    def refresh(self, selected=0):
        self.rows.delete(0, "end")
        for item in self.path:
            self.rows.insert("end", json.dumps(item, ensure_ascii=False))
        if self.path:
            self.rows.selection_set(min(selected, len(self.path) - 1))

    def selected(self):
        selected = self.rows.curselection()
        return selected[0] if selected else None

    def edit_value(self, value):
        return RecordDialog(
            self, "Geçiş", value, {"id", "status", "fields"}, {"id"}, self.suggestions
        ).show()

    def add(self):
        result = self.edit_value({"id": ""})
        if result is not None:
            self.path.append(result)
            self.refresh(len(self.path) - 1)

    def edit(self):
        index = self.selected()
        if index is not None:
            result = self.edit_value(self.path[index])
            if result is not None:
                self.path[index] = result
                self.refresh(index)

    def remove(self):
        index = self.selected()
        if index is not None:
            self.path.pop(index)
            self.refresh(index)

    def move(self, delta):
        index = self.selected()
        if index is not None and 0 <= index + delta < len(self.path):
            self.path.insert(index + delta, self.path.pop(index))
            self.refresh(index + delta)

    def value(self):
        return deepcopy(self.path)
