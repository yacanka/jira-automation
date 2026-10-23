"""Searchable API/UI observation catalog with context-preserving scenario drafts."""

import tkinter as tk
from dataclasses import asdict
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..errors import ConfigurationError
from .platform import observation_template, redact_display


class CatalogPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(toolbar, text="Katalog JSON aç…", command=self.open_catalog).pack(side="left")
        ttk.Button(toolbar, text="HTML aç", command=self.open_html).pack(side="left", padx=5)
        self.api_only = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Yalnızca API", variable=self.api_only).pack(side="left")
        for key, title in (
            ("source_project", "Kaynak projeyi keşfet"),
            ("test_project", "Test projesini keşfet"),
        ):
            button = ttk.Button(toolbar, text=title, command=partial(self.explore, key))
            button.pack(side="left", padx=5)
            if hasattr(app, "register_job_button"):
                app.register_job_button(button)
        self.summary = ttk.Label(self, text="Henüz katalog açılmadı")
        self.summary.grid(row=1, column=0, sticky="w", pady=8)
        filters = ttk.Frame(self)
        filters.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.filters: dict[str, tk.StringVar] = {}
        self.combos: dict[str, ttk.Combobox] = {}
        for index, (key, label) in enumerate(
            (
                ("issue_type", "Tür"),
                ("screen", "Ekran"),
                ("status", "Statü"),
                ("transition", "Geçiş"),
                ("source", "Kaynak"),
            )
        ):
            ttk.Label(filters, text=label).grid(row=0, column=index, sticky="w")
            variable = tk.StringVar()
            combo = ttk.Combobox(filters, textvariable=variable, state="readonly", width=13)
            combo.grid(row=1, column=index, sticky="ew", padx=(0, 5))
            combo.bind("<<ComboboxSelected>>", lambda event: self.apply_filters())
            filters.columnconfigure(index, weight=1)
            self.filters[key] = variable
            self.combos[key] = combo
        ttk.Label(filters, text="Serbest arama").grid(row=0, column=5, sticky="w")
        self.search = tk.StringVar()
        search = ttk.Entry(filters, textvariable=self.search)
        search.grid(row=1, column=5, sticky="ew")
        filters.columnconfigure(5, weight=2)
        self.search.trace_add("write", lambda *_: self.apply_filters())
        panes = ttk.Panedwindow(self, orient="vertical")
        panes.grid(row=3, column=0, sticky="nsew")
        table = ttk.Frame(panes)
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        panes.add(table, weight=3)
        columns = (
            "issue_type",
            "screen",
            "status",
            "transition",
            "field",
            "name",
            "source",
            "required",
            "visible",
            "editable",
        )
        self.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for key, label in zip(
            columns,
            (
                "Tür",
                "Ekran",
                "Statü",
                "Geçiş",
                "Alan",
                "Ad",
                "Kaynak",
                "Zorunlu",
                "Görünür",
                "Düzenlenebilir",
            ),
            strict=True,
        ):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=100, minwidth=65)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.bind("<<TreeviewSelect>>", self.show_details)
        self.tree.bind("<Return>", lambda event: self.create_template())
        detail_frame = ttk.Frame(panes)
        panes.add(detail_frame, weight=2)
        detail_frame.columnconfigure(0, weight=1)
        detail_frame.rowconfigure(1, weight=1)
        ttk.Button(detail_frame, text="Seçili gözlemden taslak", command=self.create_template).grid(
            row=0, column=0, sticky="w", pady=6
        )
        self.details = tk.Text(detail_frame, height=9, wrap="word", state="disabled")
        self.details.grid(row=1, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.details.yview)
        detail_scroll.grid(row=1, column=1, sticky="ns")
        self.details.configure(yscrollcommand=detail_scroll.set)
        self.refresh()

    def refresh(self) -> None:
        catalog = self.app.catalog
        self.summary.configure(
            text=(
                f"{catalog.project} · {len(catalog.observations)} gözlem · "
                f"{len(catalog.gaps)} kapsam eksiği · {catalog.created_at}"
                if catalog
                else "Henüz katalog açılmadı"
            )
        )
        for key, combo in self.combos.items():
            values = (
                sorted(
                    {
                        str(getattr(item, key))
                        for item in catalog.observations
                        if getattr(item, key) is not None
                    }
                )
                if catalog
                else []
            )
            combo.configure(values=[""] + values)
            if self.filters[key].get() not in values:
                self.filters[key].set("")
        self.apply_filters()
        self.show_details()

    def apply_filters(self) -> None:
        self.tree.delete(*self.tree.get_children())
        if not self.app.catalog:
            return
        query = self.search.get().casefold()
        for index, item in enumerate(self.app.catalog.observations):
            if any(
                var.get() and var.get() != str(getattr(item, key))
                for key, var in self.filters.items()
            ):
                continue
            if query not in str(asdict(item)).casefold():
                continue
            values = [getattr(item, key) for key in self.tree["columns"]]
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=["unknown" if value is None else str(value) for value in values],
            )

    def show_details(self, event=None) -> None:
        catalog = self.app.catalog
        selection = self.tree.selection()
        content: dict = {"not": "unknown doğrulanmış false değildir; API ve UI ayrı gözlemlerdir."}
        if catalog:
            content["kapsam_eksikleri"] = catalog.gaps
            if selection:
                content["gözlem"] = asdict(catalog.observations[int(selection[0])])
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", redact_display(content, self.app.credentials()))
        self.details.configure(state="disabled")

    def open_catalog(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Katalog aç", filetypes=[("Katalog JSON", "*.json")]
        )
        if path:
            try:
                self.app.set_catalog(Path(path))
                self.refresh()
            except (OSError, ConfigurationError) as exc:
                messagebox.showerror("Katalog açılamadı", str(exc), parent=self)

    def open_html(self) -> None:
        path = self.app.catalog_path
        if path:
            try:
                self.app.open_path(path.with_suffix(".html"))
            except (OSError, ValueError) as exc:
                messagebox.showerror("HTML açılamadı", str(exc), parent=self)

    def explore(self, project_key: str) -> None:
        try:
            config = (
                self.app.collect_config()
                if hasattr(self.app, "collect_config")
                else self.app.profile
            )
            self.app.start_job(
                "explore",
                {
                    "config": config,
                    "credentials": self.app.credentials(),
                    "project": config[project_key],
                    "api_only": self.api_only.get(),
                },
            )
        except (ConfigurationError, KeyError) as exc:
            messagebox.showerror("Keşif başlatılamadı", str(exc), parent=self)

    def create_template(self) -> None:
        selection = self.tree.selection()
        if selection and self.app.catalog:
            item = self.app.catalog.observations[int(selection[0])]
            expected = None
            if item.source == "ui" and item.visible is None:
                expected = messagebox.askyesnocancel(
                    "Görünürlük bilinmiyor",
                    "Gözlem görünürlük değerini doğrulamıyor. Beklenen görünürlük ne olsun?\n"
                    "Evet: görünür, Hayır: görünmez, İptal: taslak oluşturma.",
                    parent=self,
                )
                if expected is None:
                    return
            self.app.open_designer(
                scenario=observation_template(
                    item, self.app.catalog_path, expected_visible=expected
                )
            )
