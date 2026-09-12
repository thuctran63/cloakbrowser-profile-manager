from __future__ import annotations

import asyncio
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from profile_manager.browser_service import BrowserService
from profile_manager.models import OpenOptions, ProfileConfig, RuntimeState


class FakeContext:
    def __init__(self) -> None:
        self.pages = [FakePage()]
        self.handlers = {}
        self.closed = False

    def on(self, event, handler) -> None:
        self.handlers[event] = handler

    async def close(self) -> None:
        self.closed = True
        handler = self.handlers.get("close")
        if handler:
            handler(self)

    async def new_cdp_session(self, page):
        return FakeCdpSession()

    async def add_init_script(self, script):
        self.init_script = script


class FakeCdpSession:
    calls = []

    async def send(self, method, params=None):
        self.calls.append((method, params))
        if method == "Browser.getWindowForTarget":
            return {"windowId": 42}
        return {}

    async def detach(self):
        return None


class FakePage:
    def __init__(self) -> None:
        self.main_frame = object()
        self.handlers = {}
        self.goto_urls = []

    def on(self, event, handler) -> None:
        self.handlers[event] = handler

    async def evaluate(self, script):
        self.evaluated_script = script

    async def goto(self, url):
        self.goto_urls.append(url)

    def is_closed(self) -> bool:
        return False


class FakePlaywright:
    def __init__(self) -> None:
        self.stop_calls = 0

    async def stop(self) -> None:
        self.stop_calls += 1


class FakePlaywrightManager:
    def __init__(self, playwright) -> None:
        self.playwright = playwright

    async def start(self):
        return self.playwright


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
        self.playwright = FakePlaywright()
        self.playwright_patch = patch(
            "profile_manager.browser_service.async_playwright",
            return_value=FakePlaywrightManager(self.playwright),
        )
        self.playwright_patch.start()
        self.service = BrowserService(lambda *event: self.events.append(event))

    async def asyncTearDown(self) -> None:
        await self.service.close_all()
        self.playwright_patch.stop()
        self.temp.cleanup()

    async def test_open_passes_stable_seed_and_close_cleans_up(self) -> None:
        context = FakeContext()

        async def launch(*args, **kwargs):
            self.assertEqual(args[0], self.profile.user_data_dir)
            self.assertEqual(
                kwargs["args"][:4],
                [
                    "--fingerprint=54321",
                    "--fingerprint-platform=windows",
                    "--disable-notifications",
                    "--mute-audio",
                ],
            )
            self.assertRegex(kwargs["args"][4], r"^--remote-debugging-port=\d+$")
            self.assertEqual(kwargs["args"][5], "--remote-debugging-address=127.0.0.1")
            self.assertIsNone(kwargs["extension_paths"])
            self.assertEqual(kwargs["proxy"], self.profile.proxy)
            self.assertFalse(kwargs["stealth_args"])
            self.assertTrue(kwargs["geoip"])
            self.assertEqual(kwargs["release_channel"], "stable")
            self.assertFalse(kwargs["humanize"])
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

    async def test_open_loads_managed_extensions(self) -> None:
        context = FakeContext()
        extension_library = MagicMock()
        paths = [Path(self.temp.name) / "extensions" / "one"]
        extension_library.launch_paths.return_value = paths
        service = BrowserService(
            lambda *event: self.events.append(event),
            extension_library=extension_library,
        )

        async def launch(*_args, **kwargs):
            self.assertEqual(kwargs["extension_paths"], [str(paths[0])])
            return context

        with patch("profile_manager.browser_service.launch_persistent_context_async", launch), patch(
            "profile_manager.browser_service.discover_cdp_url",
            return_value="http://127.0.0.1:9222",
        ):
            await service.open(self.profile)

        extension_library.launch_paths.assert_called_once_with(self.profile.id)

    async def test_extension_changes_require_stopped_profile(self) -> None:
        extension_library = MagicMock()
        service = BrowserService(lambda *_event: None, extension_library=extension_library)
        service._states[self.profile.id] = RuntimeState.RUNNING

        with self.assertRaisesRegex(RuntimeError, "đóng tất cả profile"):
            await service.assign_extensions([self.profile.id], ["extension-id"])
        with self.assertRaisesRegex(RuntimeError, "đóng tất cả profile"):
            await service.unassign_extensions([self.profile.id], ["extension-id"])

        extension_library.assign.assert_not_called()
        extension_library.unassign.assert_not_called()

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
        self.assertEqual(self.playwright.stop_calls, 0)

    async def test_profiles_share_one_playwright_until_shutdown(self) -> None:
        second_profile = ProfileConfig(
            id="00000000-0000-0000-0000-000000000002",
            name="Second",
            proxy=None,
            fingerprint_seed=54322,
            data_dir=str(Path(self.temp.name) / "second"),
            created_at="now",
            updated_at="now",
        )
        contexts = [FakeContext(), FakeContext()]
        playwrights = []

        async def launch(*_args, **kwargs):
            playwrights.append(kwargs["playwright"])
            return contexts[len(playwrights) - 1]

        with patch("profile_manager.browser_service.launch_persistent_context_async", launch), patch(
            "profile_manager.browser_service.discover_cdp_url",
            side_effect=["http://127.0.0.1:9222", "http://127.0.0.1:9223"],
        ):
            await asyncio.gather(
                self.service.open(self.profile), self.service.open(second_profile)
            )
            await self.service.close_all()

        self.assertIs(playwrights[0], playwrights[1])
        self.assertTrue(all(context.closed for context in contexts))
        self.assertEqual(self.playwright.stop_calls, 1)

    async def test_stale_close_event_cannot_stop_reopened_profile(self) -> None:
        old_context, new_context = FakeContext(), FakeContext()
        contexts = iter([old_context, new_context])

        async def launch(*_args, **_kwargs):
            return next(contexts)

        with patch("profile_manager.browser_service.launch_persistent_context_async", launch), patch(
            "profile_manager.browser_service.discover_cdp_url",
            side_effect=["http://127.0.0.1:9222", "http://127.0.0.1:9223"],
        ):
            await self.service.open(self.profile)
            old_handler = old_context.handlers["close"]
            await self.service.close(self.profile.id)
            await self.service.open(self.profile)
            old_handler(old_context)
            await asyncio.sleep(0)

        self.assertEqual(self.service.state(self.profile.id), RuntimeState.RUNNING)
        self.assertIs(self.service._contexts[self.profile.id], new_context)

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

    async def test_open_applies_window_geometry_and_page_zoom(self) -> None:
        context = FakeContext()
        FakeCdpSession.calls = []

        async def launch(*_args, **kwargs):
            self.assertIn("--window-position=8,365", kwargs["args"])
            self.assertIn("--window-size=470,349", kwargs["args"])
            self.assertIn("--app=https://www.facebook.com", kwargs["args"])
            self.assertNotIn("--app=about:blank", kwargs["args"])
            return context

        options = OpenOptions(
            pos_x=8,
            pos_y=365,
            width=470,
            height=349,
            page_zoom=75,
            start_url="https://www.facebook.com",
        )
        with patch("profile_manager.browser_service.launch_persistent_context_async", launch), patch(
            "profile_manager.browser_service.discover_cdp_url", return_value="http://127.0.0.1:9222"
        ):
            await self.service.open(self.profile, options)

        preferences = json.loads(
            (self.profile.user_data_dir / "Default" / "Preferences").read_text(
                encoding="utf-8"
            )
        )
        expected_level = math.log(0.75) / math.log(1.2)
        self.assertAlmostEqual(
            preferences["partition"]["default_zoom_level"]["x"], expected_level
        )
        self.assertFalse(hasattr(context, "init_script"))
        self.assertEqual(
            context.pages[0].goto_urls,
            [],
        )
        self.assertIn(
            (
                "Browser.setWindowBounds",
                {
                    "windowId": 42,
                    "bounds": {
                        "windowState": "normal",
                        "left": 8,
                        "top": 365,
                        "width": 470,
                        "height": 349,
                    },
                },
            ),
            FakeCdpSession.calls,
        )


if __name__ == "__main__":
    unittest.main()