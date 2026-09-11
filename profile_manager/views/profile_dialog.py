"""Create and edit profile dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..proxy import normalize_proxy
from ..ui import BaseDialog


class ProfileDialog(BaseDialog):
    def __init__(self, parent: tk.Misc, title: str, name: str = "", proxy: str = "") -> None:
        super().__init__(parent, title)
        self.result: tuple[str, str] | None = None
        self.name_var = tk.StringVar(value=name)
        self.proxy_var = tk.StringVar(value=proxy)
        self.error_var = tk.StringVar()
        self._build()
        self.bind("<Return>", lambda _event: self._save())

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=26, style="Surface.TFrame")
        frame.grid(sticky="nsew")
        ttk.Label(frame, text=self.title(), style="DialogTitle.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="Thiết lập danh tính và kết nối cho hồ sơ trình duyệt.", style="SurfaceSubtitle.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 22))
        ttk.Label(frame, text="Tên profile", style="Section.TLabel").grid(row=2, column=0, sticky="w")
        name_entry = ttk.Entry(frame, textvariable=self.name_var, width=52)
        name_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(7, 18))

        ttk.Label(frame, text="Proxy (không bắt buộc)", style="Section.TLabel").grid(row=4, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.proxy_var, width=52).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(7, 5)
        )
        ttk.Label(
            frame,
            text="Ví dụ: http://user:pass@host:port hoặc socks5://host:port",
            style="Helper.TLabel",
        ).grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, textvariable=self.error_var, style="Error.TLabel", wraplength=420).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(12, 12)
        )
        buttons = ttk.Frame(frame, style="Surface.TFrame")
        buttons.grid(row=8, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Hủy", command=self.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Lưu profile", command=self._save, style="Primary.TButton").pack(side="left")
        frame.columnconfigure(0, weight=1)
        name_entry.focus_set()

    def _save(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            self.error_var.set("Tên profile không được để trống")
            return
        try:
            proxy = normalize_proxy(self.proxy_var.get()) or ""
        except ValueError as exc:
            self.error_var.set(str(exc))
            return
        self.result = (name, proxy)
        self.destroy()

