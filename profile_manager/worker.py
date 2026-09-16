"""A dedicated asyncio event loop for all Playwright operations."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any


class WorkerUnavailableError(RuntimeError):
    pass


class AsyncWorker:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._state_lock = threading.Lock()
        self._stopping = False
        self._thread = threading.Thread(target=self._run, name="browser-worker", daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()

    def submit(self, coroutine: Coroutine[Any, Any, Any]) -> Future[Any]:
        with self._state_lock:
            if self._stopping or not self._thread.is_alive() or not self._loop.is_running():
                coroutine.close()
                raise WorkerUnavailableError("Browser worker đã dừng")
            try:
                return asyncio.run_coroutine_threadsafe(coroutine, self._loop)
            except Exception:
                coroutine.close()
                raise

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive() and self._loop.is_running()

    def stop(self, timeout: float = 5.0) -> None:
        with self._state_lock:
            if self._stopping:
                should_stop = False
            else:
                self._stopping = True
                should_stop = self._thread.is_alive()
        if should_stop:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            raise TimeoutError("Browser worker không dừng đúng hạn")
