from __future__ import annotations

import json
import tempfile
import unittest
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from profile_manager.api_server import ProfileApiServer
from profile_manager.browser_service import BrowserService
from profile_manager.profile_store import ProfileStore
from profile_manager.worker import AsyncWorker


class ProfileApiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = ProfileStore(root / "app", root / "profiles")
        self.worker = AsyncWorker()
        self.service = BrowserService(lambda *_args: None)
        self.server = ProfileApiServer(
            self.store, self.worker, self.service, port=0, api_key="test-key"
        )
        self.server.start()

    def tearDown(self) -> None:
        self.server.stop()
        self.worker.submit(self.service.close_all()).result(timeout=5)
        self.worker.stop()
        self.temp.cleanup()

    def request(self, method: str, path: str, body=None, authenticated=True):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["X-API-Key"] = "test-key"
        request = Request(self.server.address + path, data=data, headers=headers, method=method)
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    def test_profile_crud(self) -> None:
        status, created = self.request("POST", "/api/profiles", {"name": "API profile"})
        self.assertEqual(status, 201)
        self.assertNotIn("fingerprint_seed", created)

        status, listed = self.request("GET", "/api/profiles")
        self.assertEqual(status, 200)
        self.assertEqual(listed["profiles"][0]["id"], created["id"])

        status, updated = self.request(
            "PATCH", f"/api/profiles/{created['id']}", {"name": "Updated"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["name"], "Updated")

        status, deleted = self.request("DELETE", f"/api/profiles/{created['id']}")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])

    def test_requires_api_key(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            self.request("GET", "/api/profiles", authenticated=False)
        self.assertEqual(raised.exception.code, 401)

    def test_v1_open_returns_pollable_operation(self) -> None:
        _, profile = self.request("POST", "/api/profiles", {"name": "Operation"})

        async def open_profile(_profile):
            return "http://127.0.0.1:9222"

        self.service.open = open_profile
        status, accepted = self.request(
            "POST", f"/api/v1/profiles/{profile['id']}/operations/open"
        )
        self.assertEqual(status, 202)
        operation_id = accepted["data"]["id"]
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            _, polled = self.request("GET", f"/api/v1/operations/{operation_id}")
            if polled["data"]["status"] == "succeeded":
                break
            time.sleep(0.01)
        self.assertEqual(polled["data"]["result"]["cdp_url"], "http://127.0.0.1:9222")

    def test_health_and_status(self) -> None:
        self.assertEqual(self.request("GET", "/health/live")[0], 200)
        self.assertEqual(self.request("GET", "/health/ready")[0], 200)
        status, body = self.request("GET", "/api/v1/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["data"]["worker_alive"])