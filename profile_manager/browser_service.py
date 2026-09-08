"""CloakBrowser lifecycle and runtime state management."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from cloakbrowser import launch_persistent_context_async

from .models import ProfileConfig, RuntimeState
from .devtools import discover_cdp_url
from .proxy import redact_proxy_in_text

StateCallback = Callable[[str, RuntimeState, str | None], None]


class BrowserService:
    def __init__(
        self,
        state_callback: StateCallback,
        max_concurrent_launches: int = 2,
        max_running_profiles: int = 10,
    ) -> None:
        self._contexts: dict[str, Any] = {}
        self._cdp_urls: dict[str, str] = {}
        self._states: dict[str, RuntimeState] = {}
        self._state_callback = state_callback
        self._closing: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._generation: dict[str, int] = {}
        self._launch_slots = asyncio.Semaphore(max_concurrent_launches)
        self._max_running_profiles = max_running_profiles
        self._draining = False

    def state(self, profile_id: str) -> RuntimeState:
        return self._states.get(profile_id, RuntimeState.STOPPED)

    def _set_state(
        self, profile_id: str, state: RuntimeState, message: str | None = None
    ) -> None:
        self._states[profile_id] = state
        self._state_callback(profile_id, state, message)

    def cdp_url(self, profile_id: str) -> str | None:
        return self._cdp_urls.get(profile_id)

    async def open(self, profile: ProfileConfig) -> str:
        async with self._lock(profile.id):
            existing = self.cdp_url(profile.id)
            if self.state(profile.id) == RuntimeState.RUNNING and existing:
                return existing
            if self._draining:
                raise RuntimeError("Dịch vụ đang shutdown")
            active = sum(
                state in {RuntimeState.STARTING, RuntimeState.RUNNING}
                for state in self._states.values()
            )
            if active >= self._max_running_profiles:
                raise RuntimeError("Đã đạt giới hạn profile đang chạy")
            return await self._open_locked(profile)

    async def _open_locked(self, profile: ProfileConfig) -> str:
        context: Any | None = None
        generation = self._generation.get(profile.id, 0) + 1
        self._generation[profile.id] = generation

        self._set_state(profile.id, RuntimeState.STARTING)
        try:
            profile.user_data_dir.mkdir(parents=True, exist_ok=True)
            active_port = profile.user_data_dir / "DevToolsActivePort"
            active_port.unlink(missing_ok=True)
            started_at = time.time()
            async with self._launch_slots:
                context = await launch_persistent_context_async(
                    profile.user_data_dir,
                    headless=False,
                    proxy=profile.proxy,
                    stealth_args=False,
                    args=[
                        f"--fingerprint={profile.fingerprint_seed}",
                        "--fingerprint-platform=windows",
                        "--remote-debugging-port=0",
                        "--remote-debugging-address=127.0.0.1",
                    ],
                    chromium_sandbox=True,
                )
            self._contexts[profile.id] = context
            cdp_url = await discover_cdp_url(profile.user_data_dir, started_at)
            self._cdp_urls[profile.id] = cdp_url
            context.on(
                "close",
                lambda *_args: asyncio.get_running_loop().create_task(
                    self._handle_context_closed(profile.id, generation)
                ),
            )
            if not context.pages:
                await context.new_page()
            self._set_state(profile.id, RuntimeState.RUNNING)
            return cdp_url
        except Exception as exc:
            self._contexts.pop(profile.id, None)
            self._cdp_urls.pop(profile.id, None)
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            message = redact_proxy_in_text(str(exc), profile.proxy)
            self._set_state(profile.id, RuntimeState.ERROR, message)
            raise RuntimeError(message) from exc

    async def close(self, profile_id: str) -> None:
        async with self._lock(profile_id):
            await self._close_locked(profile_id)

    async def _close_locked(self, profile_id: str) -> None:
        state = self.state(profile_id)
        context = self._contexts.get(profile_id)
        if context is None:
            self._set_state(profile_id, RuntimeState.STOPPED)
            return
        if profile_id in self._closing or state == RuntimeState.STOPPING:
            return

        self._closing.add(profile_id)
        self._set_state(profile_id, RuntimeState.STOPPING)
        try:
            await context.close()
        finally:
            self._contexts.pop(profile_id, None)
            self._cdp_urls.pop(profile_id, None)
            self._closing.discard(profile_id)
            self._set_state(profile_id, RuntimeState.STOPPED)

    async def _handle_context_closed(self, profile_id: str, generation: int) -> None:
        if self._generation.get(profile_id) != generation:
            return
        self._contexts.pop(profile_id, None)
        self._cdp_urls.pop(profile_id, None)
        self._closing.discard(profile_id)
        self._set_state(profile_id, RuntimeState.STOPPED)

    async def close_all(self) -> None:
        self._draining = True
        profile_ids = list(self._contexts)
        if profile_ids:
            await asyncio.gather(
                *(self.close(profile_id) for profile_id in profile_ids),
                return_exceptions=True,
            )

    def begin_draining(self) -> None:
        self._draining = True

    def configure_limits(self, max_concurrent_launches: int, max_running_profiles: int) -> None:
        if any(state == RuntimeState.STARTING for state in self._states.values()):
            raise RuntimeError("Không thể đổi giới hạn khi profile đang khởi động")
        self._launch_slots = asyncio.Semaphore(max_concurrent_launches)
        self._max_running_profiles = max_running_profiles

    @property
    def draining(self) -> bool:
        return self._draining

    def counts(self) -> dict[str, int]:
        return {
            "running": sum(state == RuntimeState.RUNNING for state in self._states.values()),
            "starting": sum(state == RuntimeState.STARTING for state in self._states.values()),
            "limit": self._max_running_profiles,
        }

    def _lock(self, profile_id: str) -> asyncio.Lock:
        return self._locks.setdefault(profile_id, asyncio.Lock())
