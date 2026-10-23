"""Non-secret profile editor and in-memory connection credentials."""

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import yaml

from ..errors import ConfigurationError
from .platform import validate_profile


class ProfilePanel(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.columnconfigure(1, weight=1)
        self.username = tk.StringVar(value=os.environ.get("JIRA_USERNAME", ""))
        self.password = tk.StringVar(value=os.environ.get("JIRA_PASSWORD", ""))
        self.variables: dict[str, tk.Variable] = {}
        self.editors: dict[str, tk.Text] = {}
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        for text, command in (
            ("Profil aç…", self.open_profile),
            ("Profili kaydet…", self.save_profile),
            ("API kontrolü", lambda: self.doctor(True)),
            ("API + tarayıcı kontrolü", lambda: self.doctor(False)),
        ):
            button = ttk.Button(toolbar, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            if "kontrolü" in text and hasattr(app, "register_job_button"):
                app.register_job_button(button)
        self.path_label = ttk.Label(self, text="Profil: kaydedilmedi")
        self.path_label.grid(row=1, column=0, columnspan=2, sticky="w")
        basic = ttk.Frame(self)
        basic.grid(row=2, column=0, columnspan=2, sticky="ew", pady=8)
        basic.columnconfigure(1, weight=1)
        basic.columnconfigure(3, weight=1)
        fields = (
            ("base_url", "Jira HTTPS adresi", ""),
            ("source_project", "Kaynak proje", ""),
            ("test_project", "Test projesi", ""),
            ("browser", "Tarayıcı", "chrome"),
            ("timeout", "Zaman aşımı (saniye)", "20"),
            ("sample_limit", "Örnek sınırı", "100"),
            ("artifact_dir", "Çıktı klasörü", "artifacts"),
            ("verify_tls", "CA dosyası (boş: sistem)", ""),
        )
        for index, (key, label, default) in enumerate(fields):
            row, column = divmod(index, 2)
            column *= 2
            ttk.Label(basic, text=label).grid(row=row, column=column, sticky="w", padx=5, pady=5)
            variable = tk.StringVar(value=default)
            self.variables[key] = variable
            widget: ttk.Entry
            if key == "browser":
                widget = ttk.Combobox(
                    basic,
                    textvariable=variable,
                    values=("chrome", "edge", "firefox"),
                    state="readonly",
                )
            else:
                widget = ttk.Entry(basic, textvariable=variable)
            widget.grid(row=row, column=column + 1, sticky="ew", padx=5, pady=5)
        for index, (key, text) in enumerate(
            (
                ("headless", "Tarayıcıyı arka planda çalıştır"),
                ("screenshots", "Hata ekran görüntülerini kaydet"),
            )
        ):
            flag = tk.BooleanVar()
            self.variables[key] = flag
            ttk.Checkbutton(basic, text=text, variable=flag).grid(
                row=4, column=index * 2, columnspan=2, sticky="w", pady=5
            )
        credentials = ttk.LabelFrame(self, text="Bağlantı — yalnızca bellekte", padding=8)
        credentials.grid(row=3, column=0, columnspan=2, sticky="ew")
        credentials.columnconfigure(1, weight=1)
        credentials.columnconfigure(3, weight=1)
        ttk.Label(credentials, text="Kullanıcı adı").grid(row=0, column=0, padx=5)
        ttk.Entry(credentials, textvariable=self.username).grid(row=0, column=1, sticky="ew")
        ttk.Label(credentials, text="Parola").grid(row=0, column=2, padx=5)
        ttk.Entry(credentials, textvariable=self.password, show="•").grid(
            row=0, column=3, sticky="ew"
        )
        ttk.Label(credentials, text="Kullanıcı adı ve parola profil dosyasına kaydedilmez.").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(6, 0)
        )
        notebook = ttk.Notebook(self)
        notebook.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=10)
        self.rowconfigure(4, weight=1)
        for key, title in (
            ("default_fields", "Varsayılan alanlar"),
            ("samples", "Örnek kayıtlar"),
            ("locators", "CSS seçiciler"),
        ):
            frame = ttk.Frame(notebook, padding=6)
            notebook.add(frame, text=title)
            ttk.Label(frame, text=f"Gelişmiş: {key} — güvenli YAML eşlemesi ({{}} = boş)").pack(
                anchor="w"
            )
            editor = tk.Text(frame, height=7, wrap="none", undo=True)
            scrollbar = ttk.Scrollbar(frame, command=editor.yview)
            scrollbar.pack(side="right", fill="y")
            editor.configure(yscrollcommand=scrollbar.set)
            editor.pack(fill="both", expand=True)
            editor.insert("1.0", "{}\n")
            self.editors[key] = editor
        self.load_profile(app.profile)

    def refresh_profiles(self) -> None:
        self.path_label.configure(text=f"Profil klasörü: {self.profile_directory()}")

    def credentials(self) -> dict:
        return {"username": self.username.get(), "password": self.password.get()}

    def load_profile(self, data: dict) -> None:
        for key, variable in self.variables.items():
            if key in data:
                value = data[key]
                variable.set("" if key == "verify_tls" and value is True else value)
        for key, editor in self.editors.items():
            editor.delete("1.0", "end")
            editor.insert("1.0", yaml.safe_dump(data.get(key, {}), allow_unicode=True))

    def collect_config(self) -> dict:
        values = {key: variable.get() for key, variable in self.variables.items()}
        try:
            values["timeout"] = float(values["timeout"])
            values["sample_limit"] = int(values["sample_limit"])
            values["verify_tls"] = values["verify_tls"].strip() or True
            for key, editor in self.editors.items():
                values[key] = yaml.safe_load(editor.get("1.0", "end"))
            config = validate_profile(values)
        except (ValueError, TypeError, yaml.YAMLError) as exc:
            raise ConfigurationError(
                "Sayısal ayarları ve gelişmiş YAML eşlemelerini kontrol edin"
            ) from exc
        self.app.profile = config
        return config

    def open_profile(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Jira profili aç",
            initialdir=self.profile_directory(),
            filetypes=[("YAML", "*.yaml *.yml")],
        )
        if not path:
            return
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
            config = validate_profile(data)
            self.load_profile(config)
            self.app.profile = config
            self.path_label.configure(text=f"Profil: {path}")
            self.app.status("Profil yüklendi")
        except (OSError, UnicodeError, yaml.YAMLError, ConfigurationError) as exc:
            messagebox.showerror("Profil açılamadı", str(exc), parent=self)

    def profile_directory(self) -> Path:
        return self.app.workspace / ".jira-test-studio" / "profiles"

    def save_profile(self) -> None:
        try:
            config = self.collect_config()
            name = simpledialog.askstring("Profili kaydet", "Profil adı:", parent=self)
            if not name:
                return
            if not all(char.isalnum() or char in "-_ " for char in name) or not name.strip():
                raise ConfigurationError("Profil adı yalnızca harf, rakam, boşluk, - ve _ içermeli")
            directory = self.profile_directory()
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / (name.strip() + ".yaml")
            if path.exists() and not messagebox.askyesno(
                "Profili güncelle", "Bu profil zaten var. Üzerine kaydedilsin mi?", parent=self
            ):
                return
            path.write_text(
                yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            self.path_label.configure(text=f"Profil: {path}")
            self.app.status("Profil kaydedildi; kimlik bilgileri yalnızca bellekte")
        except (OSError, ConfigurationError) as exc:
            messagebox.showerror("Profil kaydedilemedi", str(exc), parent=self)

    def doctor(self, api_only: bool) -> None:
        try:
            self.app.start_job(
                "doctor",
                {
                    "config": self.collect_config(),
                    "credentials": self.credentials(),
                    "api_only": api_only,
                },
            )
        except ConfigurationError as exc:
            messagebox.showerror("Profil geçersiz", str(exc), parent=self)
