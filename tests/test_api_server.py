from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
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
        if self.worker.is_alive:
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
        status, created = self.request("POST", "/api/v1/profiles", {"name": "API profile"})
        self.assertEqual(status, 201)
        self.assertNotIn("fingerprint_seed", created)

        status, listed = self.request("GET", "/api/v1/profiles")
        self.assertEqual(status, 200)
        self.assertEqual(listed["profiles"][0]["id"], created["id"])

        status, updated = self.request(
            "PATCH", f"/api/v1/profiles/{created['id']}", {"name": "Updated"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["name"], "Updated")

        status, deleted = self.request("DELETE", f"/api/v1/profiles/{created['id']}")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])

    def test_requires_api_key(self) -> None:
        with self.assertRaises(HTTPError) as raised:
            self.request("GET", "/api/v1/profiles", authenticated=False)
        self.assertEqual(raised.exception.code, 401)

    def test_api_does_not_rate_limit_requests(self) -> None:
        for _ in range(150):
            status, payload = self.request("GET", "/health")
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"status": "ok"})

    def test_openapi_documents_every_route(self) -> None:
        status, document = self.request("GET", "/openapi.json")
        self.assertEqual(status, 200)
        self.assertEqual(document["openapi"], "3.1.0")
        expected = {
            "/health",
            "/health/live",
            "/health/ready",
            "/api/v1/status",
            "/api/v1/diagnostics",
            "/api/v1/profiles/{profile_id}/open",
            "/api/v1/profiles/{profile_id}/close",
            "/api/v1/profiles/{profile_id}/status",
            "/api/v1/profiles/close-all",
            "/api/v1/profiles/{profile_id}/preflight",
            "/api/v1/profiles",
            "/api/v1/profiles/{profile_id}",
        }
        self.assertEqual(set(document["paths"]), expected)
        self.assertEqual(document["servers"][0]["url"], self.server.address)
        self.assertIn("bearerAuth", document["components"]["securitySchemes"])
        self.assertIn("apiKeyAuth", document["components"]["securitySchemes"])

    def test_swagger_ui_is_available_without_authentication(self) -> None:
        request = Request(self.server.address + "/docs", method="GET")
        with urlopen(request, timeout=5) as response:
            content = response.read().decode("utf-8")
        self.assertEqual(response.status, 200)
        self.assertIn("SwaggerUIBundle", content)
        self.assertIn("/openapi.json", content)

        status, document = self.request("GET", "/openapi.json", authenticated=False)
        self.assertEqual(status, 200)
        self.assertEqual(document["openapi"], "3.1.0")

    def test_v1_open_returns_runtime_directly(self) -> None:
        _, profile = self.request("POST", "/api/profiles", {"name": "Operation"})

        received_options = []

        async def open_profile(_profile, options):
            received_options.append(options)
            return "http://127.0.0.1:9222"

        self.service.open = open_profile
        with patch(
            "profile_manager.api_server.get_cdp_websocket_url",
            return_value="ws://127.0.0.1:9222/devtools/browser/test",
        ):
            status, opened = self.request(
            "POST",
            f"/api/v1/profiles/{profile['id']}/open",
            {
                "pos_x": 8,
                "pos_y": 8,
                "width": 470,
                "height": 349,
                "page_zoom": 75,
                "start_url": "https://www.facebook.com",
            },
            )
        self.assertEqual(status, 200)
        self.assertEqual(opened["http"], "http://127.0.0.1:9222")
        self.assertEqual(opened["ws"], "ws://127.0.0.1:9222/devtools/browser/test")
        self.assertIsNone(opened["pid"])
        self.assertEqual(received_options[0].pos_x, 8)
        self.assertEqual(received_options[0].width, 470)
        self.assertEqual(received_options[0].page_zoom, 75)
        self.assertEqual(received_options[0].start_url, "https://www.facebook.com")

    def test_open_rejects_incomplete_geometry(self) -> None:
        _, profile = self.request("POST", "/api/profiles", {"name": "Geometry"})
        with self.assertRaises(HTTPError) as raised:
            self.request(
                "POST",
                f"/api/v1/profiles/{profile['id']}/open",
                {"pos_x": 8},
            )
        self.assertEqual(raised.exception.code, 400)

    def test_open_rejects_invalid_start_url(self) -> None:
        _, profile = self.request("POST", "/api/profiles", {"name": "App mode"})
        with self.assertRaises(HTTPError) as raised:
            self.request(
                "POST",
                f"/api/v1/profiles/{profile['id']}/open",
                {"start_url": "file:///etc/passwd"},
            )
        self.assertEqual(raised.exception.code, 400)

    def test_health_and_status(self) -> None:
        self.assertEqual(self.request("GET", "/health/live")[0], 200)
        self.assertEqual(self.request("GET", "/health/ready")[0], 200)
        status, body = self.request("GET", "/api/v1/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["data"]["worker_alive"])

    def test_close_and_status_are_synchronous_and_idempotent(self) -> None:
        _, profile = self.request("POST", "/api/v1/profiles", {"name": "Close"})
        status, closed = self.request("POST", f"/api/v1/profiles/{profile['id']}/close")
        self.assertEqual(status, 200)
        self.assertEqual(closed, {"profileId": profile["id"], "status": "stopped"})
        status, snapshot = self.request("GET", f"/api/v1/profiles/{profile['id']}/status")
        self.assertEqual(status, 200)
        self.assertEqual(snapshot["status"], "stopped")

    def test_close_all_does_not_drain_service(self) -> None:
        _, profile = self.request("POST", "/api/v1/profiles", {"name": "Close all"})
        self.service._states[profile["id"]] = self.service.state(profile["id"])
        status, result = self.request("POST", "/api/v1/profiles/close-all")
        self.assertEqual(status, 200)
        self.assertEqual(result, {"closed": [], "failed": []})
        self.assertFalse(self.service.draining)

    def test_worker_unavailable_returns_503(self) -> None:
        _, profile = self.request("POST", "/api/v1/profiles", {"name": "Unavailable"})
        self.worker.stop()
        with self.assertRaises(HTTPError) as raised:
            self.request("POST", f"/api/v1/profiles/{profile['id']}/open")
        self.assertEqual(raised.exception.code, 503)