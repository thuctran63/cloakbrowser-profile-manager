"""Application settings dialog."""

from __future__ import annotations

import tkinter as tk

from ..models import AppSettings
from ..ui import BaseDialog
from .settings_page import SettingsPage


class SettingsDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, settings: AppSettings) -> None:
        super().__init__(parent, "Settings", "660x650", resizable=True)
        self.minsize(600, 600)
        self.result: AppSettings | None = None
        self.page = SettingsPage(self, lambda: settings, self._accept, on_cancel=self.destroy)
        self.page.pack(fill="both", expand=True)
        self.page.on_show()

    def _accept(self, settings: AppSettings) -> str:
        self.result = settings
        self.destroy()
        return ""

