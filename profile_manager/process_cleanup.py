"""OS process and Chromium profile-lock reconciliation helpers."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROFILE_LOCK_FILES = (
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
    "lockfile",
    "DevToolsActivePort",
)


def find_profile_pids(user_data_dir: Path) -> list[int]:
    """Return PIDs of Chromium processes whose command line references user_data_dir."""
    target = str(user_data_dir.resolve())
    if sys.platform == "win32":
        return _find_windows_profile_pids(target)
    return _find_posix_profile_pids(target)


def _find_windows_profile_pids(target_dir: str) -> list[int]:
    escaped = target_dir.replace("'", "''")
    script = (
        "$t = [regex]::Escape('" + escaped + "'); "
        "$pattern = '(?:^|[\"=\\s])' + $t + '(?=[\"\\s]|$)'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -and ($_.CommandLine -imatch $pattern) "
        "-and ($_.Name -match 'chrom|cloak|electron') } | "
        "Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress"
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        creationflags=creationflags,
    )
    raw = result.stdout.strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    if isinstance(parsed, int):
        return [parsed]
    if isinstance(parsed, list):
        return [int(pid) for pid in parsed]
    return []


def _find_posix_profile_pids(target_dir: str) -> list[int]:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return []
    pids: list[int] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="ignore")
        except OSError:
            continue
        if target_dir in cmdline and any(name in cmdline.casefold() for name in ("chrom", "cloak")):
            pids.append(int(entry.name))
    return pids


def kill_process_tree(pid: int) -> None:
    """Forcefully terminate a browser process and its children."""
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=creationflags,
        )
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def remove_stale_locks(user_data_dir: Path) -> None:
    """Remove Chromium lock and DevTools marker files from user_data_dir."""
    for name in PROFILE_LOCK_FILES:
        path = user_data_dir / name
        if path.exists() or path.is_symlink():
            path.unlink(missing_ok=True)


def ensure_profile_unlocked(
    user_data_dir: Path,
    *,
    wait_seconds: float = 2.0,
    force_process_scan: bool = False,
) -> None:
    """Ensure no Chromium process holds user_data_dir and no stale lock files remain."""
    if not user_data_dir.exists():
        return
    has_lock_files = any(
        (user_data_dir / name).exists() or (user_data_dir / name).is_symlink()
        for name in PROFILE_LOCK_FILES
    )
    if not force_process_scan and not has_lock_files:
        return

    pids = find_profile_pids(user_data_dir)
    for pid in pids:
        kill_process_tree(pid)

    deadline = time.monotonic() + wait_seconds
    last_error: str | None = None
    while True:
        remaining_pids = find_profile_pids(user_data_dir)
        if not remaining_pids:
            try:
                remove_stale_locks(user_data_dir)
                return
            except OSError as exc:
                last_error = f"Lock file is still held: {exc}"
        else:
            for pid in remaining_pids:
                kill_process_tree(pid)
            last_error = f"Chromium process still running for profile (pids={remaining_pids})"

        if time.monotonic() >= deadline:
            raise RuntimeError(last_error or "Profile directory is still locked")
        time.sleep(0.05)
