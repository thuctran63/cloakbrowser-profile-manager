"""Launch the CloakBrowser Profile Manager."""

from __future__ import annotations

import tkinter as tk
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


def main() -> None:
    if "--install-browser" in sys.argv:
        from cloakbrowser.download import ensure_binary

        print(f"Browser installed at: {ensure_binary()}")
        return

    root = tk.Tk()
    ProfileManagerApp(root, PROJECT_ROOT)
    root.mainloop()


if __name__ == "__main__":
    main()
