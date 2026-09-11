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


class ToastManager:
    """Global toast notification overlay that stacks messages at the bottom-right of a parent."""

    _ICONS = {"success": "✓", "error": "✕", "warning": "⚠", "info": "ℹ"}

    def __init__(self, parent: tk.Misc, *, duration: int = 3500) -> None:
        self.parent = parent
        self.duration = duration
        self._toasts: list[tk.Frame] = []

    def show(self, message: str, kind: str = "info", *, duration: int | None = None) -> None:
        """Display a toast notification. *kind* is one of success, error, warning, info."""
        if duration is None:
            duration = self.duration

        # Ensure parent is mapped before placing
        self.parent.update_idletasks()

        container = tk.Frame(self.parent, bg=Theme.SURFACE, bd=0, highlightthickness=1,
                             highlightbackground=Theme.BORDER, relief="flat")
        colors = {
            "success": (Theme.SUCCESS, Theme.SUCCESS_BG),
            "error": (Theme.DANGER, Theme.DANGER_BG),
            "warning": (Theme.WARNING, Theme.WARNING_BG),
            "info": (Theme.INFO, Theme.INFO_BG),
        }
        fg, bg = colors.get(kind, colors["info"])
        container.configure(bg=bg, highlightbackground=fg)

        icon_label = tk.Label(container, text=self._ICONS.get(kind, "ℹ"), font=(Theme.FONT, 14, "bold"),
                              bg=bg, fg=fg, padx=10, pady=6)
        icon_label.pack(side="left")

        msg_label = tk.Label(container, text=message, font=(Theme.FONT, 10), bg=bg, fg=Theme.TEXT,
                             anchor="w", padx=12, pady=6, wraplength=380, justify="left")
        msg_label.pack(side="left", fill="x", expand=True)

        close_btn = tk.Label(container, text="✕", font=(Theme.FONT, 9), bg=bg, fg=Theme.MUTED,
                             padx=8, pady=6, cursor="hand2")
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e, c=container: self._dismiss(c))

        # Position at bottom-right, stacked above previous toasts
        self.parent.update_idletasks()
        parent_w = self.parent.winfo_width()
        x_offset = parent_w - 400 - 20  # 400 = approximate toast width + padding
        y_offset = self.parent.winfo_height() - 60
        for existing in self._toasts:
            y_offset -= existing.winfo_reqheight() + 6
        if y_offset < 10:
            y_offset = 10

        container.place(x=max(x_offset, 20), y=y_offset, width=400)
        self._toasts.append(container)

        # Auto-dismiss
        container.after(duration, lambda c=container: self._dismiss(c))

    def _dismiss(self, container: tk.Frame) -> None:
        if container not in self._toasts:
            return
        self._toasts.remove(container)
        container.place_forget()
        container.destroy()
        self._reposition()

    def _reposition(self) -> None:
        """Re-stack remaining toasts from the bottom."""
        self.parent.update_idletasks()
        y_offset = self.parent.winfo_height() - 60
        parent_w = self.parent.winfo_width()
        x_offset = parent_w - 400 - 20
        for toast in reversed(self._toasts):
            y_offset -= toast.winfo_reqheight() + 6
            if y_offset < 10:
                y_offset = 10
            toast.place(x=max(x_offset, 20), y=y_offset, width=400)
