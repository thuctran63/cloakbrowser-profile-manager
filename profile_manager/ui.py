"""Shared Tkinter presentation primitives for the profile manager."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class Theme:
    """Central visual tokens and ttk style configuration."""

    NAVY = "#111827"
    NAVY_HOVER = "#1F2937"
    NAVY_MUTED = "#94A3B8"
    INDIGO = "#4F46E5"
    INDIGO_DARK = "#4338CA"
    INDIGO_SOFT = "#EEF2FF"
    CANVAS = "#F4F6FA"
    SURFACE = "#FFFFFF"
    BORDER = "#E2E8F0"
    TEXT = "#111827"
    MUTED = "#64748B"
    SUCCESS = "#15803D"
    SUCCESS_BG = "#F0FDF4"
    WARNING = "#B45309"
    WARNING_BG = "#FFFBEB"
    DANGER = "#B91C1C"
    DANGER_BG = "#FEF2F2"
    INFO = "#1D4ED8"
    INFO_BG = "#EFF6FF"
    FONT = "Segoe UI"

    @classmethod
    def apply(cls, root: tk.Misc) -> ttk.Style:
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        root.option_add("*Font", (cls.FONT, 10))
        root.option_add("*selectBackground", cls.INDIGO)
        root.option_add("*selectForeground", cls.SURFACE)
        style.configure(".", font=(cls.FONT, 10), foreground=cls.TEXT, background=cls.CANVAS)
        style.configure("App.TFrame", background=cls.CANVAS)
        style.configure("Surface.TFrame", background=cls.SURFACE)
        style.configure("Sidebar.TFrame", background=cls.NAVY)
        style.configure("Card.TFrame", background=cls.SURFACE, relief="solid", borderwidth=1)
        style.configure("TLabel", background=cls.CANVAS, foreground=cls.TEXT)
        style.configure("Surface.TLabel", background=cls.SURFACE)
        style.configure("Sidebar.TLabel", background=cls.NAVY, foreground=cls.SURFACE)
        style.configure("SidebarMuted.TLabel", background=cls.NAVY, foreground=cls.NAVY_MUTED)
        style.configure("Title.TLabel", font=(cls.FONT, 22, "bold"), foreground=cls.TEXT)
        style.configure("DialogTitle.TLabel", font=(cls.FONT, 18, "bold"), foreground=cls.TEXT, background=cls.SURFACE)
        style.configure("Subtitle.TLabel", foreground=cls.MUTED)
        style.configure("SurfaceSubtitle.TLabel", foreground=cls.MUTED, background=cls.SURFACE)
        style.configure("Section.TLabel", font=(cls.FONT, 11, "bold"), background=cls.SURFACE)
        style.configure("StatValue.TLabel", font=(cls.FONT, 20, "bold"), background=cls.SURFACE)
        style.configure("StatLabel.TLabel", foreground=cls.MUTED, background=cls.SURFACE)
        style.configure("Helper.TLabel", foreground=cls.MUTED, background=cls.SURFACE)
        style.configure("Error.TLabel", foreground=cls.DANGER, background=cls.SURFACE)
        style.configure("Success.TLabel", foreground=cls.SUCCESS, background=cls.SURFACE)
        style.configure("Status.TLabel", foreground=cls.MUTED, background=cls.SURFACE)
        style.configure("TButton", padding=(13, 8), borderwidth=1, relief="flat")
        style.map("TButton", background=[("active", "#E8ECF3")])
        style.configure("Primary.TButton", font=(cls.FONT, 10, "bold"), foreground=cls.SURFACE, background=cls.INDIGO, bordercolor=cls.INDIGO)
        style.map("Primary.TButton", background=[("active", cls.INDIGO_DARK), ("disabled", "#A5B4FC")], foreground=[("disabled", "#F8FAFC")])
        style.configure("Danger.TButton", foreground=cls.DANGER, background=cls.SURFACE, bordercolor="#FECACA")
        style.map("Danger.TButton", background=[("active", cls.DANGER_BG)])
        style.configure("Nav.TButton", anchor="w", padding=(18, 11), foreground="#CBD5E1", background=cls.NAVY, borderwidth=0)
        style.map("Nav.TButton", background=[("active", cls.NAVY_HOVER)])
        style.configure("NavActive.TButton", anchor="w", padding=(18, 11), font=(cls.FONT, 10, "bold"), foreground=cls.SURFACE, background=cls.INDIGO, borderwidth=0)
        style.map("NavActive.TButton", background=[("active", cls.INDIGO_DARK)])
        style.configure("TEntry", padding=8, fieldbackground=cls.SURFACE, bordercolor=cls.BORDER, lightcolor=cls.BORDER, darkcolor=cls.BORDER)
        style.map("TEntry", bordercolor=[("focus", cls.INDIGO)])
        style.configure("Treeview", rowheight=38, background=cls.SURFACE, fieldbackground=cls.SURFACE, foreground=cls.TEXT, borderwidth=0)
        style.configure("Treeview.Heading", font=(cls.FONT, 9, "bold"), foreground=cls.MUTED, background="#F8FAFC", padding=(10, 10), relief="flat")
        style.map("Treeview", background=[("selected", cls.INDIGO_SOFT)], foreground=[("selected", cls.TEXT)])
        style.map("Treeview.Heading", background=[("active", "#F1F5F9")])
        style.configure("Card.TLabelframe", background=cls.SURFACE, bordercolor=cls.BORDER, relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=cls.SURFACE, foreground=cls.TEXT, font=(cls.FONT, 10, "bold"))
        style.configure("Horizontal.TProgressbar", background=cls.INDIGO, troughcolor=cls.INDIGO_SOFT, borderwidth=0)
        return style


def center_window(window: tk.Toplevel) -> None:
    window.update_idletasks()
    parent = window.master.winfo_toplevel()
    x = parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 2
    window.geometry(f"+{max(x, 0)}+{max(y, 0)}")


class BaseDialog(tk.Toplevel):
    """Consistent modal behavior for application dialogs."""

    def __init__(self, parent: tk.Misc, title: str, geometry: str | None = None, *, resizable: bool = False) -> None:
        super().__init__(parent)
        Theme.apply(self)
        self.title(title)
        if geometry:
            self.geometry(geometry)
        self.resizable(resizable, resizable)
        self.configure(background=Theme.CANVAS)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.after_idle(lambda: center_window(self))
