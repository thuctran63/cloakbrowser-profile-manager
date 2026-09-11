"""Create and edit profile dialog."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..models import ProfileSettings
from ..proxy import normalize_proxy
from ..ui import BaseDialog


class ProfileDialog(BaseDialog):
    def __init__(
        self, parent: tk.Misc, title: str, name: str = "", proxy: str = "",
        settings: ProfileSettings | None = None,
    ) -> None:
        super().__init__(parent, title)
        self.result: dict[str, object] | None = None
        settings = settings or ProfileSettings()
        self.name_var = tk.StringVar(value=name)
        self.proxy_var = tk.StringVar(value=proxy)
        self.error_var = tk.StringVar()
        self.geoip_var = tk.BooleanVar(value=settings.geoip)
        self.timezone_var = tk.StringVar(value=settings.timezone or "")
        self.locale_var = tk.StringVar(value=settings.locale or "")
        self.channel_var = tk.StringVar(value=settings.release_channel)
        self.version_var = tk.StringVar(value=settings.browser_version or "")
        self.humanize_var = tk.BooleanVar(value=settings.humanize)
        self.human_preset_var = tk.StringVar(value=settings.human_preset)
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
        ttk.Separator(frame).grid(row=7, column=0, columnspan=2, sticky="ew", pady=14)
        ttk.Label(frame, text="DANH TÍNH STEALTH", style="Section.TLabel").grid(row=8, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(frame, text="Tự động đồng bộ múi giờ, ngôn ngữ và WebRTC theo IP thoát", variable=self.geoip_var).grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 6))
        ttk.Label(frame, text="Múi giờ IANA (để trống = tự động)", style="Surface.TLabel").grid(row=10, column=0, sticky="w")
        ttk.Label(frame, text="Locale BCP 47 (để trống = tự động)", style="Surface.TLabel").grid(row=10, column=1, sticky="w", padx=(8, 0))
        ttk.Entry(frame, textvariable=self.timezone_var).grid(row=11, column=0, sticky="ew", pady=(4, 8))
        ttk.Entry(frame, textvariable=self.locale_var).grid(row=11, column=1, sticky="ew", padx=(8, 0), pady=(4, 8))
        ttk.Label(frame, text="Kênh browser", style="Surface.TLabel").grid(row=12, column=0, sticky="w")
        ttk.Label(frame, text="Phiên bản chính xác (không bắt buộc)", style="Surface.TLabel").grid(row=12, column=1, sticky="w", padx=(8, 0))
        ttk.Combobox(frame, textvariable=self.channel_var, values=("stable", "preview"), state="readonly").grid(row=13, column=0, sticky="ew", pady=(4, 8))
        ttk.Entry(frame, textvariable=self.version_var).grid(row=13, column=1, sticky="ew", padx=(8, 0), pady=(4, 8))
        ttk.Checkbutton(frame, text="Humanize thao tác Playwright nội bộ", variable=self.humanize_var).grid(row=14, column=0, sticky="w")
        ttk.Combobox(frame, textvariable=self.human_preset_var, values=("default", "careful"), state="readonly").grid(row=14, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(frame, textvariable=self.error_var, style="Error.TLabel", wraplength=420).grid(
            row=15, column=0, columnspan=2, sticky="w", pady=(12, 12)
        )
        buttons = ttk.Frame(frame, style="Surface.TFrame")
        buttons.grid(row=16, column=0, columnspan=2, sticky="e")
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
        try:
            settings = ProfileSettings.from_dict({
                "geoip": self.geoip_var.get(), "timezone": self.timezone_var.get(),
                "locale": self.locale_var.get(), "release_channel": self.channel_var.get(),
                "browser_version": self.version_var.get(), "humanize": self.humanize_var.get(),
                "human_preset": self.human_preset_var.get(),
            })
        except ValueError as exc:
            self.error_var.set(str(exc))
            return
        self.result = {"name": name, "proxy": proxy, "settings": settings}
        self.destroy()

