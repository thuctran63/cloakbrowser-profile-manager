"""Application settings dialog."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..models import AppSettings


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, settings: AppSettings) -> None:
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.result: AppSettings | None = None
        self.path_var = tk.StringVar(value=settings.default_profiles_dir)
        self.api_host_var = tk.StringVar(value=settings.api_host)
        self.api_port_var = tk.StringVar(value=str(settings.api_port))
        self.api_key_var = tk.StringVar(value=settings.api_key)
        self.launches_var = tk.StringVar(value=str(settings.max_concurrent_launches))
        self.rate_var = tk.StringVar(value=str(settings.requests_per_minute))
        self.show_key_var = tk.BooleanVar(value=False)
        self.error_var = tk.StringVar()
        self._build()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.after_idle(self._center)

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=20)
        frame.grid(sticky="nsew")
        ttk.Label(frame, text="Thư mục mặc định cho profile mới").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Entry(frame, textvariable=self.path_var, width=62).grid(row=1, column=0, sticky="ew", pady=(6, 6))
        ttk.Button(frame, text="Chọn…", command=self._browse).grid(row=1, column=1, padx=(8, 0))
        ttk.Label(
            frame,
            text="Thay đổi này chỉ áp dụng cho profile tạo mới. Profile cũ không bị di chuyển.",
            foreground="#5f6b7a",
            wraplength=500,
        ).grid(row=2, column=0, columnspan=2, sticky="w")

        ttk.Separator(frame).grid(row=3, column=0, columnspan=2, sticky="ew", pady=16)
        ttk.Label(frame, text="Local API", font=("Segoe UI", 10, "bold")).grid(
            row=4, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(frame, text="Host").grid(row=5, column=0, sticky="w", pady=(10, 0))
        host_entry = ttk.Entry(frame, textvariable=self.api_host_var, state="readonly", width=28)
        host_entry.grid(row=6, column=0, sticky="w", pady=(4, 0))
        ttk.Label(frame, text="Port").grid(row=5, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        ttk.Entry(frame, textvariable=self.api_port_var, width=12).grid(
            row=6, column=1, sticky="w", padx=(8, 0), pady=(4, 0)
        )
        ttk.Label(frame, text="API URL").grid(row=7, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Label(frame, textvariable=self._api_url_var(), foreground="#175cd3").grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        ttk.Label(frame, text="API key").grid(row=9, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.key_entry = ttk.Entry(frame, textvariable=self.api_key_var, show="•", width=62)
        self.key_entry.grid(row=10, column=0, sticky="ew", pady=(4, 0))
        ttk.Checkbutton(
            frame, text="Hiện", variable=self.show_key_var, command=self._toggle_key
        ).grid(row=10, column=1, sticky="w", padx=(8, 0))
        ttk.Label(
            frame,
            text="Để trống API key sẽ tắt xác thực. API và CDP chỉ được truy cập từ máy này.",
            foreground="#5f6b7a",
            wraplength=500,
        ).grid(row=11, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(frame, text="Giới hạn launch đồng thời").grid(row=12, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.launches_var, width=12).grid(row=13, column=0, sticky="w", pady=(4, 0))
        ttk.Label(frame, text="API requests/phút").grid(row=14, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.rate_var, width=12).grid(row=15, column=0, sticky="w", pady=(4, 0))
        ttk.Label(frame, textvariable=self.error_var, foreground="#b42318").grid(
            row=16, column=0, columnspan=2, sticky="w", pady=(10, 10)
        )
        buttons = ttk.Frame(frame)
        buttons.grid(row=17, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Hủy", command=self.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Lưu", command=self._save).pack(side="left")

    def _browse(self) -> None:
        selected = filedialog.askdirectory(parent=self, initialdir=self.path_var.get() or None)
        if selected:
            self.path_var.set(selected)

    def _save(self) -> None:
        raw = self.path_var.get().strip()
        if not raw:
            self.error_var.set("Vui lòng chọn thư mục lưu profile")
            return
        try:
            port = int(self.api_port_var.get().strip())
        except ValueError:
            self.error_var.set("API port phải là số")
            return
        if not 1 <= port <= 65535:
            self.error_var.set("API port phải nằm trong khoảng 1–65535")
            return
        try:
            launches = int(self.launches_var.get())
            rate = int(self.rate_var.get())
        except ValueError:
            self.error_var.set("Các giới hạn phải là số nguyên")
            return
        if not 1 <= launches <= 20 or not 10 <= rate <= 10_000:
            self.error_var.set("Giới hạn không hợp lệ (launch 1–20, rate 10–10000)")
            return
        self.result = AppSettings(
            default_profiles_dir=str(Path(raw).expanduser().resolve()),
            api_host="127.0.0.1",
            api_port=port,
            api_key=self.api_key_var.get().strip(),
            max_concurrent_launches=launches,
            requests_per_minute=rate,
        )
        self.destroy()

    def _api_url_var(self) -> tk.StringVar:
        value = tk.StringVar()

        def update(*_args: object) -> None:
            value.set(f"http://127.0.0.1:{self.api_port_var.get().strip() or '—'}")

        self.api_port_var.trace_add("write", update)
        update()
        return value

    def _toggle_key(self) -> None:
        self.key_entry.configure(show="" if self.show_key_var.get() else "•")

    def _center(self) -> None:
        self.update_idletasks()
        parent = self.master.winfo_toplevel()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
