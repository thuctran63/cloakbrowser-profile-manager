"""Reusable embedded application settings page."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable

from ..models import AppSettings


class SettingsPage(ttk.Frame):
    """Settings editor suitable for both the main window and a dialog."""

    def __init__(
        self,
        parent: tk.Misc,
        load_settings: Callable[[], AppSettings],
        save_settings: Callable[[AppSettings], str | None],
        *,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, style="App.TFrame")
        self._load_settings = load_settings
        self._save_settings = save_settings
        self._on_cancel = on_cancel
        self._disabled = False
        self.path_var = tk.StringVar()
        self.api_host_var = tk.StringVar(value="127.0.0.1")
        self.api_port_var = tk.StringVar()
        self.api_key_var = tk.StringVar()
        self.launches_var = tk.StringVar()
        self.show_key_var = tk.BooleanVar(value=False)
        self.feedback_var = tk.StringVar()
        self.api_url_var = tk.StringVar()
        self.api_port_var.trace_add("write", self._update_api_url)
        self._build()

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=(28, 24, 28, 14), style="App.TFrame")
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Cài đặt ứng dụng", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Quản lý lưu trữ, Local API và giới hạn vận hành.", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 18))
        frame = ttk.Frame(outer, padding=24, style="Surface.TFrame")
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="LƯU TRỮ PROFILE", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="Thư mục mặc định cho profile mới", style="Surface.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.path_entry = ttk.Entry(frame, textvariable=self.path_var, width=62)
        self.path_entry.grid(row=2, column=0, sticky="ew", pady=6)
        self.browse_button = ttk.Button(frame, text="Chọn...", command=self._browse)
        self.browse_button.grid(row=2, column=1, padx=(8, 0))
        ttk.Label(frame, text="Thay đổi này chỉ áp dụng cho profile tạo mới. Profile cũ không bị di chuyển.", style="Helper.TLabel", wraplength=620).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Separator(frame).grid(row=4, column=0, columnspan=2, sticky="ew", pady=18)
        ttk.Label(frame, text="LOCAL API", style="Section.TLabel").grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Label(frame, text="Host", style="Surface.TLabel").grid(row=6, column=0, sticky="w", pady=(10, 0))
        ttk.Label(frame, text="Port", style="Surface.TLabel").grid(row=6, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        self.host_entry = ttk.Entry(frame, textvariable=self.api_host_var, state="readonly", width=28)
        self.host_entry.grid(row=7, column=0, sticky="w", pady=(4, 0))
        self.port_entry = ttk.Entry(frame, textvariable=self.api_port_var, width=12)
        self.port_entry.grid(row=7, column=1, sticky="w", padx=(8, 0), pady=(4, 0))
        ttk.Label(frame, text="API URL", style="Surface.TLabel").grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 0))
        ttk.Label(frame, textvariable=self.api_url_var, style="Helper.TLabel").grid(row=9, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(frame, text="API key", style="Surface.TLabel").grid(row=10, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.key_entry = ttk.Entry(frame, textvariable=self.api_key_var, show="•", width=62)
        self.key_entry.grid(row=11, column=0, sticky="ew", pady=(4, 0))
        self.show_key_check = ttk.Checkbutton(frame, text="Hiện", variable=self.show_key_var, command=self._toggle_key)
        self.show_key_check.grid(row=11, column=1, sticky="w", padx=(8, 0))
        ttk.Label(frame, text="API key được tạo tự động. Chỉ xóa hoặc thay đổi khi chủ động xoay khóa.", style="Helper.TLabel", wraplength=620).grid(row=12, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(frame, text="Giới hạn launch đồng thời", style="Surface.TLabel").grid(row=13, column=0, sticky="w", pady=(12, 0))
        self.launches_entry = ttk.Entry(frame, textvariable=self.launches_var, width=12)
        self.launches_entry.grid(row=14, column=0, sticky="w", pady=(4, 0))
        self.feedback_label = ttk.Label(frame, textvariable=self.feedback_var, style="Error.TLabel")
        self.feedback_label.grid(row=15, column=0, columnspan=2, sticky="w", pady=(12, 8))
        buttons = ttk.Frame(frame, style="Surface.TFrame")
        buttons.grid(row=16, column=0, columnspan=2, sticky="e")
        if self._on_cancel:
            self.cancel_button = ttk.Button(buttons, text="Hủy", command=self._on_cancel)
            self.cancel_button.pack(side="left", padx=(0, 8))
        else:
            self.cancel_button = None
        self.save_button = ttk.Button(buttons, text="Lưu cài đặt", command=self.save, style="Primary.TButton")
        self.save_button.pack(side="left")
        frame.columnconfigure(0, weight=1)

    def on_show(self) -> None:
        if self._disabled:
            return
        try:
            settings = self._load_settings()
        except Exception as exc:
            self._feedback(f"Không thể tải settings: {exc}", error=True)
            return
        self.path_var.set(settings.default_profiles_dir)
        self.api_host_var.set(settings.api_host)
        self.api_port_var.set(str(settings.api_port))
        self.api_key_var.set(settings.api_key)
        self.launches_var.set(str(settings.max_concurrent_launches))
        self.show_key_var.set(False)
        self._toggle_key()
        self._feedback("")

    def _validated_settings(self) -> AppSettings | None:
        raw = self.path_var.get().strip()
        if not raw:
            self._feedback("Vui lòng chọn thư mục lưu profile", error=True)
            return None
        try:
            port = int(self.api_port_var.get().strip())
        except ValueError:
            self._feedback("API port phải là số", error=True)
            return None
        if not 1 <= port <= 65535:
            self._feedback("API port phải nằm trong khoảng 1–65535", error=True)
            return None
        try:
            launches = int(self.launches_var.get().strip())
        except ValueError:
            self._feedback("Giới hạn launch phải là số nguyên", error=True)
            return None
        if not 1 <= launches <= 20:
            self._feedback("Giới hạn launch phải nằm trong khoảng 1–20", error=True)
            return None
        api_key = self.api_key_var.get().strip()
        if not api_key:
            self._feedback("API key không được để trống", error=True)
            return None
        return AppSettings(
            default_profiles_dir=str(Path(raw).expanduser().resolve()),
            api_host="127.0.0.1", api_port=port, api_key=api_key,
            max_concurrent_launches=launches,
        )

    def save(self) -> None:
        if self._disabled:
            return
        settings = self._validated_settings()
        if settings is None:
            return
        self.set_enabled(False)
        try:
            message = self._save_settings(settings)
        except Exception as exc:
            self._feedback(f"Không thể lưu settings: {exc}", error=True)
        else:
            self._feedback(message or "Đã lưu cài đặt", error=False)
        finally:
            if self.winfo_exists():
                self.set_enabled(True)

    def _feedback(self, message: str, *, error: bool = False) -> None:
        self.feedback_var.set(message)
        self.feedback_label.configure(style="Error.TLabel" if error else "Success.TLabel")

    def _browse(self) -> None:
        selected = filedialog.askdirectory(parent=self.winfo_toplevel(), initialdir=self.path_var.get() or None)
        if selected:
            self.path_var.set(selected)

    def _update_api_url(self, *_args: object) -> None:
        self.api_url_var.set(f"http://127.0.0.1:{self.api_port_var.get().strip() or '—'}")

    def _toggle_key(self) -> None:
        self.key_entry.configure(show="" if self.show_key_var.get() else "•")

    def set_enabled(self, enabled: bool) -> None:
        self._disabled = not enabled
        state = "normal" if enabled else "disabled"
        for widget in (self.path_entry, self.port_entry, self.key_entry, self.launches_entry, self.browse_button, self.show_key_check, self.save_button):
            widget.configure(state=state)
        self.host_entry.configure(state="readonly" if enabled else "disabled")
        if self.cancel_button:
            self.cancel_button.configure(state=state)
