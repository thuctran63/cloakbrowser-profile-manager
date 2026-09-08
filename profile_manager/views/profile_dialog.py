"""Create and edit profile dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..proxy import normalize_proxy


class ProfileDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str, name: str = "", proxy: str = "") -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: tuple[str, str] | None = None
        self.name_var = tk.StringVar(value=name)
        self.proxy_var = tk.StringVar(value=proxy)
        self.error_var = tk.StringVar()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
        self.after_idle(self._center)

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=20)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="Tên profile").grid(row=0, column=0, sticky="w")
        name_entry = ttk.Entry(frame, textvariable=self.name_var, width=52)
        name_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 14))

        ttk.Label(frame, text="Proxy (không bắt buộc)").grid(row=2, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.proxy_var, width=52).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(5, 4)
        )
        ttk.Label(
            frame,
            text="Ví dụ: http://user:pass@host:port hoặc socks5://host:port",
            foreground="#5f6b7a",
        ).grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, textvariable=self.error_var, foreground="#b42318", wraplength=420).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(10, 10)
        )
        ttk.Button(frame, text="Hủy", command=self.destroy).grid(row=6, column=0, sticky="e", padx=(0, 8))
        ttk.Button(frame, text="Lưu", command=self._save).grid(row=6, column=1, sticky="e")
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

    def _center(self) -> None:
        self.update_idletasks()
        parent = self.master.winfo_toplevel()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
