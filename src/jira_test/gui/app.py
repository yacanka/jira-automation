"""Tk composition root: screens stay on the UI thread, work runs in isolated processes."""

import json
import tkinter as tk
from functools import partial
from importlib.resources import files
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..catalog import Catalog
from ..errors import JiraTestError
from .catalog_view import CatalogPanel
from .designer import DesignerPanel
from .jobs import JobController
from .platform import open_path, open_source, validate_profile
from .profiles import ProfilePanel
from .rerun import changed_sources, rerun_request
from .results import ResultsPanel
from .run_view import RunPanel

PAGES = {
    "home": "Başlangıç",
    "profiles": "Bağlantı ve profiller",
    "catalog": "Jira keşfi",
    "designer": "Test tasarımcısı",
    "run": "Test çalıştırma",
    "results": "Sonuçlar ve hatalar",
}
OUTCOMES = {
    "completed": "Tamamlandı",
    "failed": "Başarısız",
    "canceled": "İptal edildi",
    "incomplete": "Eksik / tamamlanmadı",
}


class StudioApp:
    def __init__(self, root: tk.Tk, workspace: Path):
        self.root = root
        self.workspace = workspace.expanduser().resolve()
        if not self.workspace.is_dir():
            raise ValueError("Çalışma klasörü bulunamadı")
        self.profile = validate_profile(
            {
                "base_url": "https://jira.example.test",
                "source_project": "DEMO",
                "test_project": "AUTOTEST",
            }
        )
        self.catalog: Catalog | None = None
        self.catalog_path: Path | None = None
        self.jobs = JobController(self.workspace)
        self.job_buttons: list[ttk.Button] = []
        self.closing = False
        self.active_operation = ""
        self.active_payload: dict = {}
        self.current_page = "home"
        self.status_var = tk.StringVar(value="Hazır · çevrimdışı demo ile başlayabilirsiniz")
        self.workspace_var = tk.StringVar(value=str(self.workspace))
        self.connection_var = tk.StringVar(value="Bağlantı kontrol edilmedi")
        self.root.title("Jira Test Studio · Playwright")
        self.root.geometry("1320x880")
        self.root.minsize(1060, 720)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.report_callback_exception = self.callback_error
        self._style()
        self._layout()
        self.root.after(100, self.poll_jobs)

    def _style(self):
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f6f8fb")
        style.configure("TLabel", background="#f6f8fb", foreground="#172b4d")
        style.configure("Title.TLabel", font=("TkDefaultFont", 20, "bold"))
        style.configure("Subtitle.TLabel", foreground="#52647a")
        style.configure("TButton", padding=(10, 7))
        style.configure("Nav.TButton", anchor="w", padding=(12, 13))
        style.configure("Treeview", rowheight=29)
        style.configure("Treeview.Heading", font=("TkDefaultFont", 10, "bold"))
        style.map(
            "Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#123052")]
        )

    def _layout(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(1, weight=1)
        header = ttk.Frame(self.root, padding=(18, 12))
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="JIRA TEST STUDIO", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=0, sticky="w", padx=(0, 24)
        )
        ttk.Label(header, textvariable=self.workspace_var, style="Subtitle.TLabel").grid(
            row=0, column=1, sticky="w"
        )
        button = ttk.Button(header, text="Çalışma klasörü…", command=self.change_workspace)
        button.grid(row=0, column=2, padx=8)
        self.register_job_button(button)
        ttk.Label(header, textvariable=self.connection_var).grid(row=1, column=1, sticky="w")
        sidebar = ttk.Frame(self.root, padding=(10, 12))
        sidebar.grid(row=1, column=0, sticky="ns")
        self.nav = {}
        for key, title in PAGES.items():
            button = ttk.Button(
                sidebar,
                text=title,
                style="Nav.TButton",
                command=partial(self.show_page, key),
            )
            button.pack(fill="x", pady=3)
            self.nav[key] = button
        ttk.Label(sidebar, text="Python · Tkinter\nPlaywright", style="Subtitle.TLabel").pack(
            side="bottom", anchor="w", pady=16
        )
        self.content = ttk.Frame(self.root)
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self.profile_panel = ProfilePanel(self.content, self)
        self.catalog_panel = CatalogPanel(self.content, self)
        self.designer_panel = DesignerPanel(self.content, self)
        self.run_panel = RunPanel(self.content, self)
        self.results_panel = ResultsPanel(self.content, self)
        self.home_panel = self._home()
        self.panels = {
            "home": self.home_panel,
            "profiles": self.profile_panel,
            "catalog": self.catalog_panel,
            "designer": self.designer_panel,
            "run": self.run_panel,
            "results": self.results_panel,
        }
        for panel in self.panels.values():
            panel.grid(row=0, column=0, sticky="nsew")
        footer = ttk.Frame(self.root, padding=(16, 8))
        footer.grid(row=2, column=0, columnspan=2, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=170)
        self.progress.grid(row=0, column=1, padx=10)
        self.cancel_button = ttk.Button(
            footer, text="İşlemi durdur", command=self.cancel_job, state="disabled"
        )
        self.cancel_button.grid(row=0, column=2)
        self.show_page("home")

    def _home(self):
        frame = ttk.Frame(self.content, padding=28)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="Keşfet. Test oluştur. Sonucu incele.", style="Title.TLabel").grid(
            row=0, sticky="w", pady=(8, 12)
        )
        ttk.Label(
            frame,
            text=(
                "Jira alanlarını ve ekranlarını keşfedin; senaryoları görsel olarak "
                "veya YAML ile hazırlayın.\nYAML ve Python testlerini seçerek "
                "çalıştırın, hata kanıtlarına tek yerden ulaşın."
            ),
            wraplength=850,
            style="Subtitle.TLabel",
        ).grid(row=1, sticky="w", pady=(0, 24))
        for row, (title, detail, command) in enumerate(
            [
                (
                    "1  Bağlantıyı hazırlayın",
                    "Jira adresi, kaynak/test projesi ve tarayıcı ayarları.",
                    lambda: self.show_page("profiles"),
                ),
                (
                    "2  Jira’yı keşfedin",
                    "API ve ekran gözlemleri, alan seçenekleri ve kapsam eksikleri.",
                    lambda: self.show_page("catalog"),
                ),
                (
                    "3  Test tasarlayın",
                    "Fixture, adımlar ve beklentiler; kaydetmeden önce doğrulama.",
                    lambda: self.show_page("designer"),
                ),
                (
                    "4  Çalıştırın ve inceleyin",
                    "Seçili testler, canlı günlük, hata ve geçmiş koşular.",
                    lambda: self.show_page("run"),
                ),
            ],
            start=2,
        ):
            card = ttk.LabelFrame(frame, text=title, padding=12)
            card.grid(row=row, sticky="ew", pady=6)
            card.columnconfigure(0, weight=1)
            ttk.Label(card, text=detail).grid(row=0, column=0, sticky="w")
            ttk.Button(card, text="Aç →", command=command).grid(row=0, column=1)
        demo = ttk.Button(frame, text="Çevrimdışı demo yükle", command=self.load_demo)
        demo.grid(row=6, sticky="w", pady=(24, 8))
        self.register_job_button(demo)
        ttk.Label(
            frame,
            text="Demo için Jira hesabı veya tarayıcı gerekmez. "
            "Demo yüklendikten sonra ‘Seçilenleri çalıştır’ düğmesini kullanın.",
            wraplength=850,
        ).grid(row=7, sticky="w")
        self.home_history = tk.StringVar()
        ttk.Label(frame, textvariable=self.home_history, style="Subtitle.TLabel").grid(
            row=8, sticky="w", pady=18
        )
        self.home_history.set(
            f"Geçmiş: {len(self.results_panel.runs)} işlem · "
            "Python 3.11+ · Tk hazır · Playwright motoru"
        )
        return frame

    def register_job_button(self, button):
        self.job_buttons.append(button)

    def status(self, text):
        self.status_var.set(text)

    def credentials(self):
        return self.profile_panel.credentials()

    def collect_config(self):
        self.profile = self.profile_panel.collect_config()
        self.run_panel.refresh_target()
        return self.profile

    def show_page(self, name):
        self.panels[name].tkraise()
        self.current_page = name
        for key, button in self.nav.items():
            button.state(["disabled"] if key == name else ["!disabled"])
        if name == "run":
            self.run_panel.refresh_target()
        if name == "results":
            self.refresh_history()

    def open_designer(self, path=None, scenario=None):
        if not self.designer_panel.can_leave():
            return
        self.designer_panel.load(path=path, scenario=scenario)
        self.show_page("designer")

    def open_path(self, path):
        try:
            open_path(Path(path))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Dosya açılamadı", str(exc), parent=self.root)

    def open_source(self, path):
        try:
            open_source(Path(path))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Kaynak açılamadı", str(exc), parent=self.root)

    def set_catalog(self, path):
        catalog = Catalog.load(Path(path))
        self.catalog, self.catalog_path = catalog, Path(path).resolve()
        self.catalog_panel.refresh()
        self.designer_panel.refresh_catalog()
        self.status(f"Katalog yüklendi: {catalog.project} · {len(catalog.observations)} gözlem")

    def refresh_history(self):
        self.results_panel.refresh()
        self.home_history.set(
            f"Geçmiş: {len(self.results_panel.runs)} işlem · "
            "Python 3.11+ · Tk hazır · Playwright motoru"
        )

    def change_workspace(self):
        if self.jobs.running or not self.designer_panel.can_leave():
            return
        folder = filedialog.askdirectory(parent=self.root, initialdir=self.workspace)
        if not folder:
            return
        self.workspace = Path(folder).resolve()
        self.workspace_var.set(str(self.workspace))
        self.jobs = JobController(self.workspace)
        self.catalog = self.catalog_path = None
        self.catalog_panel.refresh()
        self.designer_panel.load()
        self.designer_panel.refresh_catalog()
        self.profile_panel.refresh_profiles()
        self.run_panel.entries.clear()
        self.run_panel.refresh()
        self.refresh_history()
        self.status("Çalışma klasörü değiştirildi")

    def load_demo(self):
        directory = self.workspace / "studio-demo"
        directory.mkdir(exist_ok=True)
        for name in ("demo-catalog.json", "demo.yaml"):
            path = directory / name
            if not path.exists():
                path.write_bytes(files("jira_test.gui").joinpath("data", name).read_bytes())
        self.set_catalog(directory / "demo-catalog.json")
        self.run_panel.add_paths([directory / "demo.yaml"])
        self.show_page("run")
        self.status("Demo hazır · seçili katalog testi çevrimdışı çalışır")

    def start_job(self, operation, payload):
        if self.jobs.running or self.active_operation:
            self.status("Bir işlem sürüyor; yeni işlem için tamamlanmasını bekleyin")
            return False
        try:
            request = dict(payload)
            if operation != "collect":
                if "config" not in request:
                    request["config"] = self.collect_config()
            request.setdefault("credentials", self.credentials())
            if operation == "run" and self.catalog_path:
                request.setdefault("catalog", str(self.catalog_path))
            if operation == "run":
                self.show_page("run")
                self.run_panel.refresh_target(request)
                self.root.update_idletasks()
            if not self.jobs.start(operation, request):
                self.run_panel.refresh_target()
                return False
        except (JiraTestError, OSError, ValueError) as exc:
            messagebox.showerror("İşlem başlatılamadı", str(exc), parent=self.root)
            return False
        self.active_operation = operation
        self.active_payload = payload
        for button in self.job_buttons:
            button.state(["disabled"])
        self.cancel_button.state(["!disabled"])
        self.progress.start(12)
        self.status(
            {
                "collect": "Python testleri toplanıyor",
                "doctor": "Bağlantı kontrol ediliyor",
                "explore": "Jira keşfi sürüyor",
                "run": "Testler çalışıyor",
            }[operation]
        )
        self.run_panel.log(self.status_var.get())
        return True

    def cancel_job(self):
        if self.jobs.running:
            self.jobs.cancel()
            self.status("Durdurma istendi · devam eden işlem güvenli kontrol noktasında sonlanacak")
            self.cancel_button.state(["disabled"])

    def poll_jobs(self):
        try:
            for event in self.jobs.poll():
                self.handle_event(event)
            if self.active_operation and not self.jobs.running:
                # Drain reader events before enabling a new job to avoid crossing job boundaries.
                for event in self.jobs.poll():
                    self.handle_event(event)
                self.active_operation = ""
                self.active_payload = {}
                self.progress.stop()
                for button in self.job_buttons:
                    button.state(["!disabled"])
                self.cancel_button.state(["disabled"])
                if self.closing:
                    self.root.destroy()
                    return
        finally:
            if self.root.winfo_exists():
                self.root.after(100, self.poll_jobs)

    def handle_event(self, event):
        kind, data = event.get("type"), event.get("data", {})
        operation = event.get("operation")
        if kind == "log":
            self.run_panel.log(data.get("message", ""))
        elif kind == "progress":
            self.run_panel.progress(data)
            self.run_panel.log(json.dumps(data, ensure_ascii=False))
        elif kind == "collected" and operation == "collect":
            self.run_panel.add_collected(
                data.get("tests", []), self.active_payload.get("paths", [])
            )
        elif kind == "error":
            self.run_panel.log(data.get("message", "İşlem başarısız"))
            messagebox.showerror(
                "İşlem hatası", data.get("message", "İşlem başarısız"), parent=self.root
            )
        elif kind == "result":
            if operation == "explore" and data.get("catalog"):
                self.set_catalog(data["catalog"])
                self.show_page("catalog")
            elif operation == "doctor" and data.get("outcome") == "completed":
                self.connection_var.set("Bağlantı doğrulandı")
                messagebox.showinfo(
                    "Bağlantı kontrolü",
                    json.dumps(data, ensure_ascii=False, indent=2),
                    parent=self.root,
                )
        elif kind == "finished":
            self.status(OUTCOMES.get(data.get("outcome"), "İşlem sona erdi"))
            if operation == "doctor" and data.get("outcome") != "completed":
                self.connection_var.set("Bağlantı kontrolü başarısız")
            if operation in {"run", "explore"}:
                self.refresh_history()
            if operation == "run" and not self.closing:
                for index, run in enumerate(self.results_panel.runs):
                    if str(run["directory"]) == data.get("run_dir"):
                        self.results_panel.run_tree.selection_set(str(index))
                        self.results_panel.select_run()
                        break
                self.show_page("results")

    def rerun(self, manifest, failed_only=False):
        try:
            request = rerun_request(manifest, failed_only)
            changed = [path for path in changed_sources(manifest) if Path(path).suffix == ".py"]
            if changed and not messagebox.askyesno(
                "Python kaynakları değişti",
                "Python testleri ve conftest dosyaları mevcut kaynaklarından çalışır. "
                "Önceki koşudan beri değişen dosyalar:\n"
                + "\n".join(changed)
                + "\nGüncel kaynaklarla devam edilsin mi?",
                parent=self.root,
            ):
                return
            if self.start_job("run", request):
                self.show_page("run")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Yeniden çalıştırılamadı", str(exc), parent=self.root)

    def edit_result(self, result):
        path = result.get("path")
        if not path:
            self.status("Sonuçta kaynak dosyası bilgisi yok")
            return
        if result.get("kind") == "yaml" or Path(path).suffix in {".yaml", ".yml"}:
            self.open_designer(path=Path(path))
        else:
            self.open_source(path)

    def close(self):
        if not self.designer_panel.can_leave():
            return
        if self.jobs.running:
            if messagebox.askyesno(
                "İşlem sürüyor",
                "İşlem durdurulsun ve güvenli biçimde tamamlanınca pencere kapatılsın mı?",
                parent=self.root,
            ):
                self.closing = True
                self.cancel_job()
            return
        self.root.destroy()

    def callback_error(self, exception_type, exception, traceback):
        # Raw exception text can contain connection credentials or test input.
        messagebox.showerror(
            "Arayüz hatası",
            "İşlem tamamlanamadı ("
            + exception_type.__name__
            + "). Girdileri kontrol edip yeniden deneyin.",
            parent=self.root,
        )
