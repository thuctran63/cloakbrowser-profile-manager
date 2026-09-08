"""Discover and validate Chromium's loopback DevTools endpoint."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from urllib.request import urlopen


async def discover_cdp_url(
    user_data_dir: Path, started_at: float, timeout: float = 15.0
) -> str:
    active_port = user_data_dir / "DevToolsActivePort"
    deadline = time.monotonic() + timeout
    last_error = "DevToolsActivePort chưa sẵn sàng"
    while time.monotonic() < deadline:
        try:
            if active_port.stat().st_mtime + 1 < started_at:
                raise ValueError("DevToolsActivePort đã cũ")
            lines = active_port.read_text(encoding="utf-8").splitlines()
            if len(lines) < 2 or not lines[1].startswith("/devtools/browser/"):
                raise ValueError("DevToolsActivePort chưa hoàn chỉnh")
            port = int(lines[0])
            if not 1 <= port <= 65535:
                raise ValueError("DevTools port không hợp lệ")
            url = f"http://127.0.0.1:{port}"
            await asyncio.to_thread(_validate_cdp, url, port)
            return url
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Không thể xác thực CDP endpoint: {last_error}")


def _validate_cdp(url: str, port: int) -> None:
    with urlopen(f"{url}/json/version", timeout=1) as response:
        data = json.load(response)
    websocket_url = str(data.get("webSocketDebuggerUrl", ""))
    if f":{port}/devtools/browser/" not in websocket_url:
        raise ValueError("CDP endpoint không khớp browser vừa mở")