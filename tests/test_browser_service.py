from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from profile_manager.browser_service import BrowserService
from profile_manager.models import ProfileConfig, RuntimeState


class FakeContext:
    def __init__(self) -> None:
        self.pages = [object()]
        self.handlers = {}
        self.closed = False

    def on(self, event, handler) -> None:
        self.handlers[event] = handler

    async def close(self) -> None:
        self.closed = True


class BrowserServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.profile = ProfileConfig(
            id="00000000-0000-0000-0000-000000000001",
            name="Test",
            proxy="http://user:secret@localhost:8080",
            fingerprint_seed=54321,
            data_dir=str(Path(self.temp.name) / "profile"),
            created_at="now",
            updated_at="now",
        )
        self.events = []
        self.service = BrowserService(lambda *event: self.events.append(event))

    async def asyncTearDown(self) -> None:
        self.temp.cleanup()

    async def test_open_passes_stable_seed_and_close_cleans_up(self) -> None:
        context = FakeContext()

        async def launch(*args, **kwargs):
            self.assertEqual(args[0], self.profile.user_data_dir)
            self.assertEqual(
                kwargs["args"][:2],
                ["--fingerprint=54321", "--fingerprint-platform=windows"],
            )
            self.assertRegex(kwargs["args"][2], r"^--remote-debugging-port=\d+$")
            self.assertEqual(kwargs["args"][3], "--remote-debugging-address=127.0.0.1")
            self.assertEqual(kwargs["proxy"], self.profile.proxy)
            self.assertFalse(kwargs["stealth_args"])
            self.assertTrue(kwargs["chromium_sandbox"])
            return context

        with patch("profile_manager.browser_service.launch_persistent_context_async", launch), patch(
            "profile_manager.browser_service.discover_cdp_url",
            return_value="http://127.0.0.1:9222",
        ):
            cdp_url = await self.service.open(self.profile)
            self.assertRegex(cdp_url, r"^http://127\.0\.0\.1:\d+$")
            self.assertEqual(self.service.cdp_url(self.profile.id), cdp_url)
            self.assertEqual(self.service.state(self.profile.id), RuntimeState.RUNNING)
            await self.service.close(self.profile.id)

        self.assertTrue(context.closed)
        self.assertIsNone(self.service.cdp_url(self.profile.id))
        self.assertEqual(self.service.state(self.profile.id), RuntimeState.STOPPED)

    async def test_manual_close_event_updates_state(self) -> None:
        context = FakeContext()

        async def launch(*_args, **_kwargs):
            return context

        with patch("profile_manager.browser_service.launch_persistent_context_async", launch), patch(
            "profile_manager.browser_service.discover_cdp_url",
            return_value="http://127.0.0.1:9222",
        ):
            await self.service.open(self.profile)
            context.handlers["close"](context)
            await asyncio.sleep(0)

        self.assertEqual(self.service.state(self.profile.id), RuntimeState.STOPPED)

    async def test_open_is_idempotent(self) -> None:
        context = FakeContext()
        launches = 0

        async def launch(*_args, **_kwargs):
            nonlocal launches
            launches += 1
            return context

        with patch("profile_manager.browser_service.launch_persistent_context_async", launch), patch(
            "profile_manager.browser_service.discover_cdp_url", return_value="http://127.0.0.1:9222"
        ):
            first, second = await asyncio.gather(
                self.service.open(self.profile), self.service.open(self.profile)
            )
        self.assertEqual(first, second)
        self.assertEqual(launches, 1)

    async def test_rejects_open_while_draining(self) -> None:
        self.service.begin_draining()
        with self.assertRaisesRegex(RuntimeError, "shutdown"):
            await self.service.open(self.profile)


if __name__ == "__main__":
    unittest.main()