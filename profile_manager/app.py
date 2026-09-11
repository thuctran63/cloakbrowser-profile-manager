"""Tkinter application for managing persistent CloakBrowser profiles."""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from .browser_service import BrowserService
from .api_server import ProfileApiServer
from .extensions import ExtensionLibrary
from .models import AppSettings, ProfileConfig, RuntimeState
from .profile_store import ProfileStore
from .proxy import mask_proxy
from .ui import Theme, ToastManager
from .views.extension_manager_page import ExtensionManagerPage
from .views.profile_dialog import ProfileDialog
from .views.settings_page import SettingsPage
from .worker import AsyncWorker


class ProfileManagerApp:
    def __init__(self, root: tk.Tk, project_root: Path) -> None:
        self.root = root
        self.project_root = project_root.resolve()
        self.store = ProfileStore(
            app_data_dir=self.project_root / ".profile-manager",
            default_profiles_dir=self.project_root / "profiles",
        )
        self.worker = AsyncWorker()
        api_settings = self.store.load_settings()
        self.extension_library = ExtensionLibrary(
            self.store.database_path,
            self.store.app_data_dir / "extensions",
        )
        self.service = BrowserService(
            self._on_worker_state,
            api_settings.max_concurrent_launches,
            self.extension_library,
        )
        self.api_server = ProfileApiServer(
            self.store,
            self.worker,
            self.service,
            host=api_settings.api_host,
            port=api_settings.api_port,
            api_key=api_settings.api_key or None,
        )
        self.api_server.start()
        self.profiles: dict[str, ProfileConfig] = {}
        self.states: dict[str, RuntimeState] = {}
        self.shutting_down = False
        self.current_page = "profiles"
        self.status_var = tk.StringVar(value="Sẵn sàng")
        self.search_var = tk.StringVar()
        self.toast = ToastManager(self.root)
        self._configure_window()
        self._build_ui()
        self.refresh_profiles()
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

    def _configure_window(self) -> None:
        self.root.title("CloakBrowser Profile Manager")
        self.root.geometry("1240x740")
        self.root.minsize(980, 600)
        self.root.configure(background=Theme.CANVAS)
        Theme.apply(self.root)

    def _build_ui(self) -> None:
        shell = ttk.Frame(self.root, style="App.TFrame")
        shell.pack(fill="both", expand=True)
        sidebar = ttk.Frame(shell, width=220, style="Sidebar.TFrame")
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = ttk.Frame(sidebar, style="Sidebar.TFrame", padding=(20, 24))
        brand.pack(fill="x")
        ttk.Label(brand, text="CLOAKBROWSER", style="Sidebar.TLabel", font=(Theme.FONT, 13, "bold")).pack(anchor="w")
        ttk.Label(brand, text="Operations Console", style="SidebarMuted.TLabel").pack(anchor="w", pady=(4, 0))
        self.profiles_nav = ttk.Button(sidebar, text="Profiles", style="NavActive.TButton", command=lambda: self.show_page("profiles"))
        self.profiles_nav.pack(fill="x", padx=12, pady=(10, 4))
        self.extensions_button = ttk.Button(sidebar, text="Extension Library", style="Nav.TButton", command=lambda: self.show_page("extensions"))
        self.extensions_button.pack(fill="x", padx=12, pady=4)
        self.settings_button = ttk.Button(sidebar, text="Settings", style="Nav.TButton", command=lambda: self.show_page("settings"))
        self.settings_button.pack(fill="x", padx=12, pady=4)
        ttk.Label(sidebar, text="DỮ LIỆU CỤC BỘ", style="SidebarMuted.TLabel", font=(Theme.FONT, 8, "bold")).pack(side="bottom", anchor="w", padx=20, pady=(0, 5))
        ttk.Label(sidebar, text="Profile và fingerprint được lưu\nan toàn trên thiết bị này.", style="SidebarMuted.TLabel", justify="left").pack(side="bottom", anchor="w", padx=20, pady=(0, 6))

        self.content_host = ttk.Frame(shell, style="App.TFrame")
        self.content_host.pack(side="left", fill="both", expand=True)
        container = ttk.Frame(self.content_host, style="App.TFrame", padding=(28, 24, 28, 14))
        container.pack(side="left", fill="both", expand=True)
        self.profiles_page = container
        header = ttk.Frame(container, style="App.TFrame")
        header.pack(fill="x", pady=(0, 18))
        heading = ttk.Frame(header, style="App.TFrame")
        heading.pack(side="left", fill="x", expand=True)
        ttk.Label(heading, text="Quản lý hồ sơ trình duyệt", style="Title.TLabel").pack(anchor="w")
        ttk.Label(heading, text="Khởi chạy và vận hành các danh tính trình duyệt từ một nơi.", style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))
        self.create_button = ttk.Button(header, text="Tạo profile", command=self.create_profile, style="Primary.TButton")
        self.create_button.pack(side="right", anchor="n")

        stats = ttk.Frame(container, style="App.TFrame")
        stats.pack(fill="x", pady=(0, 18))
        self.total_var, self.running_var, self.stopped_var = tk.StringVar(value="0"), tk.StringVar(value="0"), tk.StringVar(value="0")
        for label, variable in (("Tổng profile", self.total_var), ("Đang chạy", self.running_var), ("Đã dừng", self.stopped_var)):
            card = ttk.Frame(stats, style="Card.TFrame", padding=(16, 12))
            card.pack(side="left", fill="x", expand=True, padx=(0, 10))
            ttk.Label(card, textvariable=variable, style="StatValue.TLabel").pack(anchor="w")
            ttk.Label(card, text=label, style="StatLabel.TLabel").pack(anchor="w")

        controls = ttk.Frame(container, style="App.TFrame")
        controls.pack(fill="x", pady=(0, 10))
        ttk.Label(controls, text="Tìm kiếm", style="Subtitle.TLabel").pack(side="left", padx=(0, 8))
        self.search_entry = ttk.Entry(controls, textvariable=self.search_var, width=34)
        self.search_entry.pack(side="left")
        self.search_var.trace_add("write", lambda *_args: self._render_profiles())

        action_bar = ttk.Frame(container, style="Surface.TFrame", padding=(10, 8))
        action_bar.pack(fill="x", pady=(0, 1))
        ttk.Label(action_bar, text="Hành động", style="SurfaceSubtitle.TLabel").pack(side="left", padx=(2, 12))
        self.open_button = ttk.Button(action_bar, text="Mở profile", command=self.open_profile, style="Primary.TButton")
        self.close_button = ttk.Button(action_bar, text="Đóng", command=self.close_profile)
        self.edit_button = ttk.Button(action_bar, text="Chỉnh sửa", command=self.edit_profile)
        self.delete_button = ttk.Button(action_bar, text="Xóa", command=self.delete_profile, style="Danger.TButton")
        for button in (self.open_button, self.close_button, self.edit_button, self.delete_button):
            button.pack(side="left", padx=(0, 7))

        table_frame = ttk.Frame(container, style="Surface.TFrame")
        table_frame.pack(fill="both", expand=True)
        columns = ("name", "proxy", "status", "storage")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="PROFILE")
        self.tree.heading("proxy", text="Proxy")
        self.tree.heading("status", text="TRẠNG THÁI")
        self.tree.heading("storage", text="THƯ MỤC DỮ LIỆU")
        self.tree.column("name", width=190, minwidth=130)
        self.tree.column("proxy", width=260, minwidth=180)
        self.tree.column("status", width=100, minwidth=90, anchor="center")
        self.tree.column("storage", width=430, minwidth=220)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_actions())
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.tag_configure("running", foreground=Theme.SUCCESS, background=Theme.SUCCESS_BG)
        self.tree.tag_configure("working", foreground=Theme.WARNING, background=Theme.WARNING_BG)
        self.tree.tag_configure("error", foreground=Theme.DANGER, background=Theme.DANGER_BG)

        self.empty_label = ttk.Label(table_frame, text="Chưa có profile phù hợp\nTạo profile mới hoặc thay đổi từ khóa tìm kiếm.", style="SurfaceSubtitle.TLabel", justify="center")

        footer = ttk.Frame(container, style="Surface.TFrame", padding=(10, 8))
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").pack(side="left")
        ttk.Label(footer, text="Fingerprint cố định theo từng profile", style="Status.TLabel").pack(side="right")
        self.extension_page = ExtensionManagerPage(
            self.content_host, [], {}, self.service, self.worker, self.status_var.set, on_toast=self._show_toast
        )
        self.settings_page = SettingsPage(self.content_host, self.store.load_settings, self._save_settings)
        self.pages = {"profiles": self.profiles_page, "extensions": self.extension_page, "settings": self.settings_page}
        self.nav_buttons = {"profiles": self.profiles_nav, "extensions": self.extensions_button, "settings": self.settings_button}
        self.root.bind("<Control-n>", lambda event: self._profile_shortcut(event, self.create_profile))
        self.root.bind("<Control-f>", lambda event: self._profile_shortcut(event, self.search_entry.focus_set))
        self.root.bind("<Return>", lambda event: self._profile_shortcut(event, self.open_profile, require_non_input=True))
        self.root.bind("<Delete>", lambda event: self._profile_shortcut(event, self.delete_profile, require_non_input=True))
        self.root.bind("<F5>", lambda event: self._profile_shortcut(event, self.refresh_profiles))
        self._update_actions()

    def show_page(self, name: str) -> None:
        if self.shutting_down or name not in self.pages:
            return
        for page_name, page in self.pages.items():
            if page_name == name:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()
            self.nav_buttons[page_name].configure(style="NavActive.TButton" if page_name == name else "Nav.TButton")
        self.current_page = name
        if name == "profiles":
            self.refresh_profiles()
        elif name == "extensions":
            selected = self.selected_profile()
            self.extension_page.on_show(list(self.profiles.values()), dict(self.states), selected.id if selected else None)
        else:
            self.settings_page.on_show()

    def _profile_shortcut(self, event: tk.Event[tk.Misc], action: Any, *, require_non_input: bool = False) -> str | None:
        if self.shutting_down or self.current_page != "profiles":
            return None
        focused = self.root.focus_get()
        if require_non_input and isinstance(focused, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, tk.Listbox)):
            return None
        action()
        return "break"

    def refresh_profiles(self, select_id: str | None = None) -> None:
        try:
            profiles = self.store.list_profiles()
        except Exception as exc:
            messagebox.showerror("Lỗi dữ liệu", str(exc), parent=self.root)
            profiles = []
        self.profiles = {profile.id: profile for profile in profiles}
        self._render_profiles(select_id)

    def _render_profiles(self, select_id: str | None = None) -> None:
        self.tree.delete(*self.tree.get_children())
        query = self.search_var.get().strip().casefold()
        visible = [profile for profile in self.profiles.values() if not query or query in profile.name.casefold() or query in mask_proxy(profile.proxy).casefold() or query in profile.data_dir.casefold()]
        for profile in visible:
            state = self.states.get(profile.id, RuntimeState.STOPPED)
            self.tree.insert(
                "", "end", iid=profile.id,
                values=(profile.name, mask_proxy(profile.proxy), self._localized_state(state), profile.data_dir),
                tags=(self._state_tag(state),),
            )
        if select_id and self.tree.exists(select_id):
            self.tree.selection_set(select_id)
            self.tree.focus(select_id)
        self.total_var.set(str(len(self.profiles)))
        self.running_var.set(str(sum(self._state(item.id) == RuntimeState.RUNNING for item in self.profiles.values())))
        self.stopped_var.set(str(sum(self._state(item.id) == RuntimeState.STOPPED for item in self.profiles.values())))
        if visible:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=.5, rely=.5, anchor="center")
        self._update_actions()

    @staticmethod
    def _localized_state(state: RuntimeState) -> str:
        return {RuntimeState.STOPPED: "Đã dừng", RuntimeState.STARTING: "Đang mở", RuntimeState.RUNNING: "Đang chạy", RuntimeState.STOPPING: "Đang đóng", RuntimeState.ERROR: "Lỗi"}[state]

    @staticmethod
    def _state_tag(state: RuntimeState) -> str:
        if state == RuntimeState.RUNNING:
            return "running"
        if state in {RuntimeState.STARTING, RuntimeState.STOPPING}:
            return "working"
        if state == RuntimeState.ERROR:
            return "error"
        return "stopped"

    def _on_double_click(self, event: tk.Event[tk.Misc]) -> None:
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.open_profile()

    def selected_profile(self) -> ProfileConfig | None:
        selection = self.tree.selection()
        return self.profiles.get(selection[0]) if selection else None

    def create_profile(self) -> None:
        dialog = ProfileDialog(self.root, "Tạo profile")
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        try:
            profile = self.store.create_profile(**dialog.result)
            self.refresh_profiles(profile.id)
            self.status_var.set(f"Đã tạo {profile.name}")
            self.toast.show(f"Đã tạo profile \"{profile.name}\"", kind="success")
        except Exception as exc:
            messagebox.showerror("Không thể tạo profile", str(exc), parent=self.root)

    def edit_profile(self) -> None:
        profile = self.selected_profile()
        if not profile or self._state(profile.id) != RuntimeState.STOPPED:
            return
        dialog = ProfileDialog(self.root, "Sửa profile", profile.name, profile.proxy or "", profile.settings)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        try:
            updated = self.store.update_profile(profile.id, **dialog.result)
            self.refresh_profiles(updated.id)
            self.status_var.set(f"Đã cập nhật {updated.name}")
            self.toast.show(f"Đã cập nhật profile \"{updated.name}\"", kind="success")
        except Exception as exc:
            messagebox.showerror("Không thể cập nhật profile", str(exc), parent=self.root)

    def delete_profile(self) -> None:
        profile = self.selected_profile()
        if not profile or self._state(profile.id) != RuntimeState.STOPPED:
            return
        confirmed = messagebox.askyesno(
            "Xóa profile",
            f"Xóa “{profile.name}” và toàn bộ cookie, cache, lịch sử?\n\nThao tác này không thể hoàn tác.",
            icon="warning",
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self.store.delete_profile(profile.id)
            self.states.pop(profile.id, None)
            self.refresh_profiles()
            self.status_var.set(f"Đã xóa {profile.name}")
            self.toast.show(f"Đã xóa profile \"{profile.name}\"", kind="success")
        except Exception as exc:
            messagebox.showerror("Không thể xóa profile", str(exc), parent=self.root)

    def open_profile(self) -> None:
        profile = self.selected_profile()
        if not profile or self.shutting_down or self._state(profile.id) not in {RuntimeState.STOPPED, RuntimeState.ERROR}:
            return
        future = self.worker.submit(self.service.open(profile))
        self._observe(future, "Không thể mở profile", profile)

    def close_profile(self) -> None:
        profile = self.selected_profile()
        if not profile or self._state(profile.id) != RuntimeState.RUNNING:
            return
        future = self.worker.submit(self.service.close(profile.id))
        self._observe(future, "Không thể đóng profile", profile)

    def open_extensions(self) -> None:
        """Compatibility route for callers that previously opened the sidebar dialog."""
        self.show_page("extensions")

    def open_settings(self) -> None:
        """Compatibility route for callers that previously opened the sidebar dialog."""
        self.show_page("settings")

    def _show_toast(self, message: str, kind: str = "info") -> None:
        """Display a global toast notification."""
        self.toast.show(message, kind=kind)

    def _save_settings(self, settings: AppSettings) -> str:
        previous = self.store.load_settings()
        try:
            self.worker.submit(self._apply_runtime_settings(settings)).result(timeout=5)
            self.api_server.stop()
            self.api_server = ProfileApiServer(
                self.store,
                self.worker,
                self.service,
                host=settings.api_host,
                port=settings.api_port,
                api_key=settings.api_key or None,
            )
            self.api_server.start()
            self.store.save_settings(settings)
        except Exception:
            self.worker.submit(self._apply_runtime_settings(previous)).result(timeout=5)
            try:
                self.api_server = ProfileApiServer(self.store, self.worker, self.service, previous.api_host, previous.api_port, previous.api_key or None)
                self.api_server.start()
            except Exception:
                pass
            raise
        message = f"Đã lưu settings · API: {self.api_server.address}"
        self.status_var.set(message)
        self.toast.show("Đã lưu settings thành công", kind="success")
        return message

    async def _apply_runtime_settings(self, settings: AppSettings) -> None:
        self.service.configure_limits(settings.max_concurrent_launches)

    def _observe(self, future: Future[Any], error_title: str, profile: ProfileConfig) -> None:
        def complete(done: Future[Any]) -> None:
            try:
                done.result()
            except Exception as exc:
                if not self.shutting_down:
                    messagebox.showerror(error_title, str(exc), parent=self.root)
                    self.toast.show(str(exc), kind="error")
            self._update_actions()
        future.add_done_callback(lambda done: self.root.after(0, complete, done))

    def _on_worker_state(self, profile_id: str, state: RuntimeState, message: str | None) -> None:
        if not self.shutting_down:
            self.root.after(0, self._apply_state, profile_id, state, message)

    def _apply_state(self, profile_id: str, state: RuntimeState, message: str | None) -> None:
        self.states[profile_id] = state
        if self.tree.exists(profile_id):
            values = list(self.tree.item(profile_id, "values"))
            values[2] = self._localized_state(state)
            self.tree.item(profile_id, values=values, tags=(self._state_tag(state),))
        profile = self.profiles.get(profile_id)
        name = profile.name if profile else "Profile"
        self.status_var.set(message or f"{name}: {self._localized_state(state)}")
        self._render_profiles(profile_id)
        self._update_actions()

    def _state(self, profile_id: str) -> RuntimeState:
        return self.states.get(profile_id, RuntimeState.STOPPED)

    def _update_actions(self) -> None:
        profile = self.selected_profile()
        state = self._state(profile.id) if profile else None
        active = not self.shutting_down
        self.create_button.configure(state="normal" if active else "disabled")
        self.settings_button.configure(state="normal" if active else "disabled")
        self.profiles_nav.configure(state="normal" if active else "disabled")
        self.edit_button.configure(state="normal" if active and state == RuntimeState.STOPPED else "disabled")
        self.delete_button.configure(state="normal" if active and state == RuntimeState.STOPPED else "disabled")
        self.extensions_button.configure(state="disabled" if self.shutting_down else "normal")
        self.open_button.configure(state="normal" if active and state in {RuntimeState.STOPPED, RuntimeState.ERROR} else "disabled")
        self.close_button.configure(state="normal" if active and state == RuntimeState.RUNNING else "disabled")

    def shutdown(self) -> None:
        if self.shutting_down:
            return
        self.shutting_down = True
        self.status_var.set("Đang đóng các browser…")
        self.settings_page.set_enabled(False)
        self.extension_page.set_enabled(False)
        self._update_actions()
        self.service.begin_draining()
        self.api_server.stop()
        future = self.worker.submit(self.service.close_all())

        def finish(_done: Future[Any]) -> None:
            self.worker.stop()
            self.root.destroy()

        future.add_done_callback(lambda done: self.root.after(0, finish, done))
