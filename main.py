"""Launch the CloakBrowser Profile Manager."""

from __future__ import annotations

import tkinter as tk
import ctypes
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
load_dotenv(PROJECT_ROOT / ".env")
os.environ.setdefault("CLOAKBROWSER_CACHE_DIR", str(PROJECT_ROOT / "binaries"))

from profile_manager.app import ProfileManagerApp


def _resource_path(relative: str) -> Path:
    bundle_root = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT))
    return bundle_root / relative


def _set_app_icon(root: tk.Tk) -> None:
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "CloakBrowser.ProfileManager"
        )

    png_path = _resource_path("assets/cloakbrowser.png")
    if png_path.exists():
        icon = tk.PhotoImage(file=png_path)
        root.iconphoto(True, icon)
        root._cloakbrowser_icon = icon

    ico_path = _resource_path("assets/cloakbrowser.ico")
    if sys.platform == "win32" and ico_path.exists():
        root.iconbitmap(default=str(ico_path))


def main() -> None:
    if "--install-browser" in sys.argv:
        from cloakbrowser.download import ensure_binary

        print(f"Browser installed at: {ensure_binary()}")
        return

    root = tk.Tk()
    _set_app_icon(root)
    ProfileManagerApp(root, PROJECT_ROOT)
    root.mainloop()


if __name__ == "__main__":
    main()
