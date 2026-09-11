"""Central extension library and bulk profile assignment dialog."""

from __future__ import annotations

import tkinter as tk
from concurrent.futures import Future
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from ..browser_service import BrowserService
from ..extensions import ExtensionInfo, ImportResult
from ..models import ProfileConfig, RuntimeState
from ..ui import BaseDialog, Theme
from ..worker import AsyncWorker


class ExtensionManagerPage(ttk.Frame):
    """Reusable extension library page with asynchronous operation safeguards."""

    def __init__(self, parent: tk.Misc, profiles: list[ProfileConfig], states: dict[str, RuntimeState],
                 service: BrowserService, worker: AsyncWorker,
                 on_status: Callable[[str], None] | None = None, selected_profile_id: str | None = None,
                 on_close: Callable[[], None] | None = None) -> None:
        super().__init__(parent, style="App.TFrame")
        self.profiles = profiles
        self.states = states
        self.service = service
        self.worker = worker
        self.on_status = on_status
        self.selected_profile_id = selected_profile_id
        self.on_close = on_close
        self.extensions: dict[str, ExtensionInfo] = {}
        self.assignments: dict[str, set[str]] = {}
        self.busy = False
        self.disabled = False
        self.count_var = tk.StringVar(value="Đang tải…")
        self.status_var = tk.StringVar(value="")
        self.default_var = tk.BooleanVar(value=False)
        self._build()

    def _build(self) -> None:
        container = ttk.Frame(self, padding=24, style="App.TFrame")
        container.pack(fill="both", expand=True)
        header = ttk.Frame(container)
        header.pack(fill="x", pady=(0, 14))
        title = ttk.Frame(header)
        title.pack(side="left", fill="x", expand=True)
        ttk.Label(title, text="Thư viện extension", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title, text="Import một lần, quản lý tập trung và phân bổ cho nhiều profile.", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))
        ttk.Label(header, textvariable=self.count_var, style="Subtitle.TLabel").pack(side="right", anchor="n")

        toolbar = ttk.Frame(container)
        toolbar.pack(fill="x", pady=(0, 12))
        self.import_button = ttk.Button(toolbar, text="Import thư mục…", style="Primary.TButton", command=self._import_folder)
        self.delete_button = ttk.Button(toolbar, text="Xóa khỏi thư viện", command=self._delete_selected, style="Danger.TButton")
        self.refresh_button = ttk.Button(toolbar, text="Làm mới", command=self.refresh)
        self.import_button.pack(side="left", padx=(0, 8))
        self.delete_button.pack(side="left", padx=(0, 8))
        self.refresh_button.pack(side="left")

        panes = ttk.Panedwindow(container, orient="horizontal")
        panes.pack(fill="both", expand=True)
        library = ttk.LabelFrame(panes, text="  Thư viện extensions  ", padding=12, style="Card.TLabelframe")
        assignments = ttk.LabelFrame(panes, text="  Phân bổ profiles  ", padding=12, style="Card.TLabelframe")
        panes.add(library, weight=3)
        panes.add(assignments, weight=2)

        columns = ("name", "version", "uses", "default")
        self.tree = ttk.Treeview(library, columns=columns, show="headings", selectmode="extended")
        for column, heading in (("name", "Tên extension"), ("version", "Phiên bản"), ("uses", "Profiles"), ("default", "Profile mới")):
            self.tree.heading(column, text=heading)
        self.tree.column("name", width=260, minwidth=160)
        self.tree.column("version", width=85, minwidth=70, anchor="center")
        self.tree.column("uses", width=70, minwidth=60, anchor="center")
        self.tree.column("default", width=90, minwidth=80, anchor="center")
        tree_scroll = ttk.Scrollbar(library, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._extension_selection_changed())

        ttk.Label(assignments, text="Khi chọn nhiều extension, danh sách đánh dấu chỉ hiển thị giao của các profile: profile đã được gán cho toàn bộ extension đang chọn.", style="SurfaceSubtitle.TLabel", wraplength=360).pack(fill="x", pady=(0, 10))
        profile_frame = ttk.Frame(assignments)
        profile_frame.pack(fill="both", expand=True)
        self.profile_list = tk.Listbox(profile_frame, selectmode="extended", exportselection=False, activestyle="dotbox", font=(Theme.FONT, 10), relief="solid", borderwidth=1, background=Theme.SURFACE, foreground=Theme.TEXT, selectbackground=Theme.INDIGO_SOFT, selectforeground=Theme.TEXT, highlightcolor=Theme.INDIGO, highlightbackground=Theme.BORDER)
        profile_scroll = ttk.Scrollbar(profile_frame, orient="vertical", command=self.profile_list.yview)
        self.profile_list.configure(yscrollcommand=profile_scroll.set)
        self.profile_list.pack(side="left", fill="both", expand=True)
        profile_scroll.pack(side="right", fill="y")
        self.profile_ids: list[str] = []
        for index, profile in enumerate(self.profiles):
            state = self.states.get(profile.id, RuntimeState.STOPPED)
            self.profile_ids.append(profile.id)
            self.profile_list.insert("end", f"{profile.name}  ·  {self._localized_state(state)}")
            if profile.id == self.selected_profile_id:
                self.profile_list.selection_set(index)
        actions = ttk.Frame(assignments)
        actions.pack(fill="x", pady=(10, 0))
        self.assign_button = ttk.Button(actions, text="Gán đã chọn", style="Primary.TButton", command=self._assign)
        self.unassign_button = ttk.Button(actions, text="Bỏ gán", command=self._unassign)
        self.select_all_button = ttk.Button(actions, text="Chọn tất cả", command=self._select_all_profiles)
        self.assign_button.pack(side="left", padx=(0, 7))
        self.unassign_button.pack(side="left", padx=(0, 7))
        self.select_all_button.pack(side="left")
        self.default_check = ttk.Checkbutton(assignments, text="Tự động gán cho profile tạo mới", variable=self.default_var, command=self._set_default)
        self.default_check.pack(anchor="w", pady=(12, 0))

        footer = ttk.Frame(container)
        footer.pack(fill="x", pady=(12, 0))
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=120)
        self.progress.pack(side="left", padx=(0, 10))
        self.progress.pack_forget()
        ttk.Label(footer, textvariable=self.status_var, style="Subtitle.TLabel").pack(side="left", fill="x", expand=True)
        if self.on_close:
            ttk.Button(footer, text="Đóng", command=self._close).pack(side="right")
        self.profile_list.bind("<<ListboxSelect>>", lambda _event: self._update_actions())
        self._update_actions()

    def refresh(self) -> None:
        if self.busy or self.disabled:
            return
        self._set_busy(True, "Đang tải thư viện…")
        self._observe(self.worker.submit(self.service.list_extensions()), self._extensions_loaded, "Không thể tải thư viện")

    def on_show(self, profiles: list[ProfileConfig] | None = None,
                states: dict[str, RuntimeState] | None = None,
                selected_profile_id: str | None = None) -> None:
        """Refresh profile/state context and library data whenever the page is shown."""
        if profiles is not None:
            self.profiles = profiles
        if states is not None:
            self.states = states
        self.selected_profile_id = selected_profile_id
        self.profile_ids.clear()
        self.profile_list.delete(0, "end")
        for index, profile in enumerate(self.profiles):
            state = self.states.get(profile.id, RuntimeState.STOPPED)
            self.profile_ids.append(profile.id)
            self.profile_list.insert("end", f"{profile.name}  ·  {self._localized_state(state)}")
            if profile.id == selected_profile_id:
                self.profile_list.selection_set(index)
        self.refresh()

    def _extensions_loaded(self, extensions: list[ExtensionInfo]) -> None:
        previous = set(self.tree.selection())
        self.extensions = {item.id: item for item in extensions}
        self.tree.delete(*self.tree.get_children())
        for item in extensions:
            self.tree.insert("", "end", iid=item.id, values=(item.name, item.version, item.assigned_profile_count, "Có" if item.assign_to_new_profiles else "Không"))
        for item_id in previous:
            if self.tree.exists(item_id):
                self.tree.selection_add(item_id)
        self.count_var.set(f"{len(extensions)} extension · {len(self.profiles)} profile")
        self.status_var.set("Chưa có extension" if not extensions else "Chọn extension để xem và thay đổi phân bổ.")
        self._set_busy(False)
        self._extension_selection_changed()

    def _extension_selection_changed(self) -> None:
        if self.busy or self.disabled:
            return
        ids = list(self.tree.selection())
        if not ids:
            self.assignments = {}
            self.default_var.set(False)
            self._update_actions()
            return
        defaults = {self.extensions[item_id].assign_to_new_profiles for item_id in ids}
        self.default_var.set(defaults == {True})
        self._set_busy(True, "Đang tải phân bổ profile…")
        self._observe(self.worker.submit(self.service.extension_assignments(ids)), self._assignments_loaded, "Không thể tải phân bổ")

    def _assignments_loaded(self, assignments: dict[str, set[str]]) -> None:
        self.assignments = assignments
        selected_extensions = list(self.tree.selection())
        self.profile_list.selection_clear(0, "end")
        if selected_extensions:
            common = set.intersection(*(assignments.get(item_id, set()) for item_id in selected_extensions))
            for index, profile_id in enumerate(self.profile_ids):
                if profile_id in common:
                    self.profile_list.selection_set(index)
        self.status_var.set("Các profile đang chọn đã được gán cho toàn bộ extension được chọn.")

    def _selected_profiles(self) -> list[str]:
        return [self.profile_ids[index] for index in self.profile_list.curselection()]

    def _select_all_profiles(self) -> None:
        self.profile_list.selection_set(0, "end")
        self._update_actions()

    def _assign(self) -> None:
        self._mutate_assignment(True)

    def _unassign(self) -> None:
        self._mutate_assignment(False)

    def _mutate_assignment(self, assign: bool) -> None:
        extension_ids = list(self.tree.selection())
        profile_ids = self._selected_profiles()
        if not extension_ids or not profile_ids:
            return
        active = [self.profiles[self.profile_ids.index(profile_id)].name for profile_id in profile_ids if self.states.get(profile_id, RuntimeState.STOPPED) != RuntimeState.STOPPED]
        if active:
            messagebox.showwarning("Profile đang chạy", "Hãy đóng các profile sau trước:\n\n" + "\n".join(active), parent=self.winfo_toplevel())
            return
        operation = self.service.assign_extensions if assign else self.service.unassign_extensions
        label = "Đang gán extensions…" if assign else "Đang bỏ gán extensions…"
        self._set_busy(True, label)
        self._observe(self.worker.submit(operation(profile_ids, extension_ids)), lambda _result: self._mutation_complete("Đã cập nhật phân bổ extension"), "Không thể cập nhật phân bổ")

    def _set_default(self) -> None:
        ids = list(self.tree.selection())
        if self.busy or not ids:
            return
        enabled = self.default_var.get()
        self._set_busy(True, "Đang cập nhật mặc định…")
        self._observe(self.worker.submit(self.service.set_default_extensions(ids, enabled)), lambda _result: self._mutation_complete("Đã cập nhật mặc định cho profile mới"), "Không thể cập nhật mặc định")

    def _import_folder(self) -> None:
        selected = filedialog.askdirectory(parent=self.winfo_toplevel(), title="Chọn extension hoặc thư mục chứa nhiều extension", initialdir=str(Path.home()))
        if not selected:
            return
        self._set_busy(True, "Đang copy extensions vào thư viện…")
        self._observe(self.worker.submit(self.service.import_extensions(selected)), self._import_complete, "Không thể import extensions")

    def _import_complete(self, result: ImportResult) -> None:
        parts = []
        if result.imported: parts.append(f"đã import {len(result.imported)}")
        if result.skipped: parts.append(f"bỏ qua {len(result.skipped)} bản trùng")
        if result.errors: parts.append(f"lỗi {len(result.errors)}")
        summary = " · ".join(parts) or "Không có thay đổi"
        if result.errors:
            messagebox.showwarning("Import chưa hoàn tất", summary.capitalize() + "\n\n" + "\n".join(result.errors[:12]), parent=self.winfo_toplevel())
        self._mutation_complete(summary.capitalize())

    def _delete_selected(self) -> None:
        ids = list(self.tree.selection())
        if not ids:
            return
        used = [self.extensions[item_id].name for item_id in ids if self.extensions[item_id].assigned_profile_count]
        if used:
            messagebox.showwarning("Extension đang được sử dụng", "Hãy bỏ gán khỏi tất cả profile trước:\n\n" + "\n".join(used), parent=self.winfo_toplevel())
            return
        names = "\n".join(f"• {self.extensions[item_id].name}" for item_id in ids[:8])
        if not messagebox.askyesno("Xóa khỏi thư viện", f"Xóa vĩnh viễn {len(ids)} extension?\n\n{names}", icon="warning", parent=self.winfo_toplevel()):
            return
        self._set_busy(True, "Đang xóa khỏi thư viện…")
        self._observe(self.worker.submit(self.service.delete_extensions(ids)), lambda result: self._mutation_complete(f"Đã xóa {len(result)} extension"), "Không thể xóa extensions")

    def _mutation_complete(self, status: str) -> None:
        if self.on_status:
            self.on_status(status)
        self._set_busy(False, status)
        self.refresh()

    def _observe(self, future: Future[Any], on_success: Callable[[Any], None], error_title: str) -> None:
        def complete(done: Future[Any]) -> None:
            if not self.winfo_exists() or self.disabled:
                return
            try:
                result = done.result()
            except Exception as exc:
                self._set_busy(False, str(exc))
                messagebox.showerror(error_title, str(exc), parent=self.winfo_toplevel())
            else:
                on_success(result)
                if self.busy:
                    self._set_busy(False)
        future.add_done_callback(lambda done: self.after(0, complete, done))

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        if message:
            self.status_var.set(message)
        self.configure(cursor="wait" if busy else "")
        if busy:
            self.progress.pack(side="left", padx=(0, 10), before=self.progress.master.winfo_children()[1])
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()
        self._update_actions()

    @staticmethod
    def _localized_state(state: RuntimeState) -> str:
        return {RuntimeState.STOPPED: "Đã dừng", RuntimeState.STARTING: "Đang mở", RuntimeState.RUNNING: "Đang chạy", RuntimeState.STOPPING: "Đang đóng", RuntimeState.ERROR: "Lỗi"}[state]

    def _update_actions(self) -> None:
        extensions_selected = bool(self.tree.selection())
        profiles_selected = bool(self.profile_list.curselection())
        normal = not self.busy and not self.disabled
        self.import_button.configure(state="normal" if normal else "disabled")
        self.refresh_button.configure(state="normal" if normal else "disabled")
        self.delete_button.configure(state="normal" if normal and extensions_selected else "disabled")
        state = "normal" if normal and extensions_selected and profiles_selected else "disabled"
        self.assign_button.configure(state=state)
        self.unassign_button.configure(state=state)
        self.select_all_button.configure(state="normal" if normal and self.profiles else "disabled")
        self.default_check.configure(state="normal" if normal and extensions_selected else "disabled")

    def _close(self) -> None:
        if not self.busy and self.on_close:
            self.on_close()

    def set_enabled(self, enabled: bool) -> None:
        self.disabled = not enabled
        if self.disabled:
            self.status_var.set("Ứng dụng đang đóng…")
        self._update_actions()


class ExtensionManagerDialog(BaseDialog):
    """Backward-compatible modal wrapper around :class:`ExtensionManagerPage`."""

    def __init__(self, parent: tk.Tk | tk.Toplevel, profiles: list[ProfileConfig], states: dict[str, RuntimeState],
                 service: BrowserService, worker: AsyncWorker,
                 on_status: Callable[[str], None] | None = None, selected_profile_id: str | None = None) -> None:
        super().__init__(parent, "Extension Library", "1080x680", resizable=True)
        self.minsize(820, 500)
        self.page = ExtensionManagerPage(self, profiles, states, service, worker, on_status, selected_profile_id, self._close)
        self.page.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _event: self._close())
        self.page.on_show(profiles, states, selected_profile_id)

    def _close(self) -> None:
        if not self.page.busy:
            self.grab_release()
            self.destroy()

