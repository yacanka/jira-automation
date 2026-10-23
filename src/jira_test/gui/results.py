"""Run history and evidence browser, including interrupted or partial runs."""

import tkinter as tk
from tkinter import messagebox, ttk

from .platform import open_jira_issue, redact_display, run_artifact, scan_runs


class ResultsPanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.runs: list[dict] = []
        self.current: dict | None = None
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for index, (text, command) in enumerate(
            (
                ("Geçmişi yenile", self.refresh),
                ("Çalıştırma klasörü", self.open_directory),
                ("Tümünü yeniden çalıştır", lambda: self.rerun(False)),
                ("Başarısızları yeniden çalıştır", lambda: self.rerun(True)),
                ("Senaryoyu düzenle", self.edit_selected),
                ("Ekran görüntüsü", self.open_screenshot),
                ("Jira kaydını aç", self.open_issue),
            )
        ):
            button = ttk.Button(toolbar, text=text, command=command)
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=(0, 5), pady=3)
            toolbar.columnconfigure(index % 4, weight=1)
            if "yeniden çalıştır" in text and hasattr(app, "register_job_button"):
                app.register_job_button(button)
        panes = ttk.Panedwindow(self, orient="vertical")
        panes.grid(row=1, column=0, sticky="nsew")
        runs_frame = ttk.Frame(panes)
        panes.add(runs_frame, weight=1)
        self.run_tree = self.make_table(
            runs_frame,
            (
                ("run", "Çalıştırma"),
                ("started", "Başlangıç"),
                ("status", "Durum"),
                ("count", "Sonuç"),
                ("incomplete", "Rapor bütünlüğü"),
            ),
            height=5,
        )
        self.run_tree.bind("<<TreeviewSelect>>", self.select_run)
        results_frame = ttk.Frame(panes)
        panes.add(results_frame, weight=1)
        self.result_tree = self.make_table(
            results_frame,
            (
                ("id", "Test / senaryo"),
                ("outcome", "Sonuç"),
                ("issue", "Oluşan kayıt"),
                ("reason", "Açıklama"),
            ),
            height=6,
        )
        self.result_tree.bind("<<TreeviewSelect>>", self.show_details)
        self.result_tree.bind("<Return>", lambda event: self.edit_selected())
        details_frame = ttk.Frame(panes)
        panes.add(details_frame, weight=2)
        details_frame.rowconfigure(1, weight=1)
        details_frame.columnconfigure(0, weight=1)
        ttk.Label(
            details_frame,
            text=("Ayrıntılar: adımlar, beklentiler, hata, oluşturulan kayıtlar ve olay günlüğü"),
        ).grid(row=0, column=0, sticky="w", pady=5)
        self.details = tk.Text(details_frame, wrap="word", height=12, state="disabled")
        self.details.grid(row=1, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(details_frame, command=self.details.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.details.configure(yscrollcommand=scrollbar.set)
        self.refresh()

    @staticmethod
    def make_table(parent, columns, height):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        table = ttk.Treeview(
            parent,
            columns=[key for key, _ in columns],
            show="headings",
            selectmode="browse",
            height=height,
        )
        for key, label in columns:
            table.heading(key, text=label)
            table.column(key, width=180 if key in {"run", "id", "reason"} else 100, minwidth=60)
        table.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, command=table.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(parent, orient="horizontal", command=table.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        table.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        return table

    def refresh(self) -> None:
        previous = self.current["directory"] if self.current else None
        try:
            self.runs = scan_runs(self.app.workspace)
        except OSError as exc:
            self.app.status(f"Geçmiş okunamadı: {exc}")
            self.runs = []
        self.run_tree.delete(*self.run_tree.get_children())
        selected = None
        for index, run in enumerate(self.runs):
            manifest = run["manifest"]
            self.run_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    manifest.get("run_id", run["directory"].name),
                    manifest.get("started_at", "—"),
                    run["status"],
                    len(run["results"]),
                    "eksik / kısmi" if run["incomplete"] else "tam",
                ),
            )
            if run["directory"] == previous:
                selected = str(index)
        if self.runs:
            self.run_tree.selection_set(selected or "0")
        self.select_run()

    def select_run(self, event=None) -> None:
        selection = self.run_tree.selection()
        self.current = self.runs[int(selection[0])] if selection else None
        self.result_tree.delete(*self.result_tree.get_children())
        if self.current:
            for index, result in enumerate(self.current["results"]):
                reason = redact_display(result.get("reason", ""), self.app.credentials())
                self.result_tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(
                        result.get("id", result.get("nodeid", "bilinmiyor")),
                        result.get("outcome", "bilinmiyor"),
                        result.get("issue") or "—",
                        reason,
                    ),
                )
        self.show_details()

    def selected_result(self) -> dict | None:
        selection = self.result_tree.selection()
        return self.current["results"][int(selection[0])] if self.current and selection else None

    def show_details(self, event=None) -> None:
        result = self.selected_result()
        content = {}
        if self.current:
            content = {
                "sonuç": result,
                "oluşturulan_kayıtlar": self.current["report"].get("created_issues", []),
                "pytest_raporları": self.current["report"].get("reports", []),
                "manifest": self.current["manifest"],
                "olaylar": self.current["events"],
            }
            if self.current["incomplete"]:
                content["uyarı"] = (
                    "Rapor veya günlük eksik; tamamlanmamış testler başarılı sayılmaz."
                )
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", redact_display(content, self.app.credentials()))
        self.details.configure(state="disabled")

    def rerun(self, failed_only: bool) -> None:
        if not self.current:
            return
        if not self.current["manifest"].get("request"):
            messagebox.showinfo(
                "Yeniden çalıştırılamıyor", "Çalıştırma isteği bulunamadı.", parent=self
            )
            return
        self.app.rerun(self.current["manifest"], failed_only=failed_only)

    def edit_selected(self) -> None:
        result = self.selected_result()
        if result:
            self.app.edit_result(result)

    def open_directory(self) -> None:
        if self.current:
            self.app.open_path(self.current["directory"])

    def open_screenshot(self) -> None:
        result = self.selected_result()
        if not result or not self.current or not result.get("screenshot"):
            self.app.status("Seçili sonuç için ekran görüntüsü yok")
            return
        try:
            self.app.open_path(run_artifact(self.current["directory"], result["screenshot"]))
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Ekran görüntüsü açılamadı", str(exc), parent=self)

    def open_issue(self) -> None:
        result = self.selected_result()
        if not result or not self.current or not result.get("issue"):
            self.app.status("Önce Jira kaydı olan bir sonuç seçin")
            return
        config = self.current["manifest"].get("request", {}).get("config", {})
        try:
            open_jira_issue(config.get("base_url", ""), result["issue"])
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Jira bağlantısı açılamadı", str(exc), parent=self)
