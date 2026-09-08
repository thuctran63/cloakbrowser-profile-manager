"""Tkinter application for managing persistent CloakBrowser profiles."""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from .browser_service import BrowserService
from .api_server import ProfileApiServer
from .models import AppSettings, ProfileConfig, RuntimeState
from .profile_store import ProfileStore
from .proxy import mask_proxy
from .views.profile_dialog import ProfileDialog
from .views.settings_dialog import SettingsDialog
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
        self.service = BrowserService(
            self._on_worker_state,
            api_settings.max_concurrent_launches,
            api_settings.max_running_profiles,
        )
        self.api_server = ProfileApiServer(
            self.store,
            self.worker,
            self.service,
            host=api_settings.api_host,
            port=api_settings.api_port,
            api_key=api_settings.api_key or None,
            requests_per_minute=api_settings.requests_per_minute,
        )
        self.api_server.start()
        self.profiles: dict[str, ProfileConfig] = {}
        self.states: dict[str, RuntimeState] = {}
        self.shutting_down = False
        self.status_var = tk.StringVar(value="Sẵn sàng")
        self._configure_window()
        self._build_ui()
        self.refresh_profiles()
        self.root.protocol("WM_DELETE_WINDOW", self.shutdown)

    def _configure_window(self) -> None:
        self.root.title("CloakBrowser Profile Manager")
        self.root.geometry("1080x620")
        self.root.minsize(820, 460)
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=30)
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"))

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container)
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text="Browser Profiles", font=("Segoe UI", 20, "bold")).pack(side="left")
        ttk.Button(header, text="Settings", command=self.open_settings).pack(side="right")

        toolbar = ttk.Frame(container)
        toolbar.pack(fill="x", pady=(0, 12))
        self.create_button = ttk.Button(toolbar, text="Tạo profile", command=self.create_profile, style="Primary.TButton")
        self.edit_button = ttk.Button(toolbar, text="Sửa", command=self.edit_profile)
        self.delete_button = ttk.Button(toolbar, text="Xóa", command=self.delete_profile)
        self.open_button = ttk.Button(toolbar, text="Open", command=self.open_profile)
        self.close_button = ttk.Button(toolbar, text="Close", command=self.close_profile)
        for button in (self.create_button, self.edit_button, self.delete_button, self.open_button, self.close_button):
            button.pack(side="left", padx=(0, 8))

        table_frame = ttk.Frame(container)
        table_frame.pack(fill="both", expand=True)
        columns = ("name", "proxy", "status", "storage")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="Tên")
        self.tree.heading("proxy", text="Proxy")
        self.tree.heading("status", text="Trạng thái")
        self.tree.heading("storage", text="Nơi lưu")
        self.tree.column("name", width=190, minwidth=130)
        self.tree.column("proxy", width=260, minwidth=180)
        self.tree.column("status", width=100, minwidth=90, anchor="center")
        self.tree.column("storage", width=430, minwidth=220)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._update_actions())
        self.tree.bind("<Double-1>", lambda _event: self.open_profile())

        footer = ttk.Frame(container)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(footer, textvariable=self.status_var, foreground="#475467").pack(side="left")
        ttk.Label(footer, text="Fingerprint được giữ cố định theo từng profile", foreground="#667085").pack(side="right")
        self._update_actions()

    def refresh_profiles(self, select_id: str | None = None) -> None:
        try:
            profiles = self.store.list_profiles()
        except Exception as exc:
            messagebox.showerror("Lỗi dữ liệu", str(exc), parent=self.root)
            profiles = []
        self.profiles = {profile.id: profile for profile in profiles}
        self.tree.delete(*self.tree.get_children())
        for profile in profiles:
            state = self.states.get(profile.id, RuntimeState.STOPPED)
            self.tree.insert(
                "", "end", iid=profile.id,
                values=(profile.name, mask_proxy(profile.proxy), state.value, profile.data_dir),
            )
        if select_id and self.tree.exists(select_id):
            self.tree.selection_set(select_id)
            self.tree.focus(select_id)
        self._update_actions()

    def selected_profile(self) -> ProfileConfig | None:
        selection = self.tree.selection()
        return self.profiles.get(selection[0]) if selection else None

    def create_profile(self) -> None:
        dialog = ProfileDialog(self.root, "Tạo profile")
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        try:
            profile = self.store.create_profile(*dialog.result)
            self.refresh_profiles(profile.id)
            self.status_var.set(f"Đã tạo {profile.name}")
        except Exception as exc:
            messagebox.showerror("Không thể tạo profile", str(exc), parent=self.root)

    def edit_profile(self) -> None:
        profile = self.selected_profile()
        if not profile or self._state(profile.id) != RuntimeState.STOPPED:
            return
        dialog = ProfileDialog(self.root, "Sửa profile", profile.name, profile.proxy or "")
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        try:
            updated = self.store.update_profile(profile.id, *dialog.result)
            self.refresh_profiles(updated.id)
            self.status_var.set(f"Đã cập nhật {updated.name}")
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

    def open_settings(self) -> None:
        settings = self.store.load_settings()
        dialog = SettingsDialog(self.root, settings)
        self.root.wait_window(dialog)
        if not dialog.result:
            return
        try:
            self.store.save_settings(dialog.result)
            self.worker.submit(self._apply_runtime_settings(dialog.result)).result(timeout=5)
            self.api_server.stop()
            self.api_server = ProfileApiServer(
                self.store,
                self.worker,
                self.service,
                host=dialog.result.api_host,
                port=dialog.result.api_port,
                api_key=dialog.result.api_key or None,
                requests_per_minute=dialog.result.requests_per_minute,
            )
            self.api_server.start()
            self.status_var.set(f"Đã lưu settings · API: {self.api_server.address}")
        except Exception as exc:
            messagebox.showerror("Không thể lưu settings", str(exc), parent=self.root)

    async def _apply_runtime_settings(self, settings: AppSettings) -> None:
        self.service.configure_limits(
            settings.max_concurrent_launches, settings.max_running_profiles
        )

    def _observe(self, future: Future[Any], error_title: str, profile: ProfileConfig) -> None:
        def complete(done: Future[Any]) -> None:
            try:
                done.result()
            except Exception as exc:
                if not self.shutting_down:
                    messagebox.showerror(error_title, str(exc), parent=self.root)
            self._update_actions()
        future.add_done_callback(lambda done: self.root.after(0, complete, done))

    def _on_worker_state(self, profile_id: str, state: RuntimeState, message: str | None) -> None:
        self.root.after(0, self._apply_state, profile_id, state, message)

    def _apply_state(self, profile_id: str, state: RuntimeState, message: str | None) -> None:
        self.states[profile_id] = state
        if self.tree.exists(profile_id):
            values = list(self.tree.item(profile_id, "values"))
            values[2] = state.value
            self.tree.item(profile_id, values=values)
        profile = self.profiles.get(profile_id)
        name = profile.name if profile else "Profile"
        self.status_var.set(message or f"{name}: {state.value}")
        self._update_actions()

    def _state(self, profile_id: str) -> RuntimeState:
        return self.states.get(profile_id, RuntimeState.STOPPED)

    def _update_actions(self) -> None:
        profile = self.selected_profile()
        state = self._state(profile.id) if profile else None
        self.edit_button.configure(state="normal" if state == RuntimeState.STOPPED else "disabled")
        self.delete_button.configure(state="normal" if state == RuntimeState.STOPPED else "disabled")
        self.open_button.configure(state="normal" if state in {RuntimeState.STOPPED, RuntimeState.ERROR} else "disabled")
        self.close_button.configure(state="normal" if state == RuntimeState.RUNNING else "disabled")

    def shutdown(self) -> None:
        if self.shutting_down:
            return
        self.shutting_down = True
        self.status_var.set("Đang đóng các browser…")
        self.create_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.service.begin_draining()
        self.api_server.stop()
        future = self.worker.submit(self.service.close_all())

        def finish(_done: Future[Any]) -> None:
            self.worker.stop()
            self.root.destroy()

        future.add_done_callback(lambda done: self.root.after(0, finish, done))
