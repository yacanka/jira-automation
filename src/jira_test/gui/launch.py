"""Lazy desktop entry point, keeping Tk optional for command line users."""

from pathlib import Path


def launch(workspace: Path | None = None) -> int:
    try:
        import tkinter as tk
    except ImportError:
        print(
            "Tk desteği bulunamadı. Windows Python kurulumunda 'Tcl/Tk and IDLE' "
            "bileşenini etkinleştirin. 'python -m tkinter' ile doğrulayın; "
            "gerekirse sanal ortamı Tk destekli Python ile yeniden oluşturun."
        )
        return 2
    try:
        root = tk.Tk()
    except tk.TclError:
        print(
            "Tk penceresi açılamadı. Grafik masaüstü oturumunu ve Tcl/Tk kurulumunu kontrol edin."
        )
        return 2
    from .app import StudioApp

    try:
        StudioApp(root, workspace or Path.cwd())
    except (OSError, ValueError) as exc:
        root.destroy()
        print(f"Arayüz başlatılamadı: {exc}")
        return 2
    root.mainloop()
    return 0
