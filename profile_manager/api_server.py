"""Local HTTP API for profile management and CDP automation access."""

from __future__ import annotations

import json
import secrets
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .browser_service import BrowserService
from .models import ProfileConfig
from .openapi import SWAGGER_UI_HTML, build_openapi
from .operations import OperationRegistry
from .profile_store import ProfileStore
from .worker import AsyncWorker


class PayloadTooLargeError(ValueError):
    pass


class ProfileApiServer:
    def __init__(
        self,
        store: ProfileStore,
        worker: AsyncWorker,
        browser_service: BrowserService,
        host: str = "127.0.0.1",
        port: int = 8765,
        api_key: str | None = None,
        max_body_bytes: int = 65_536,
        requests_per_minute: int = 120,
    ) -> None:
        self.store = store
        self.worker = worker
        self.browser_service = browser_service
        self.api_key = api_key
        self.max_body_bytes = max_body_bytes
        self.requests_per_minute = requests_per_minute
        self.operations = OperationRegistry()
        self._rate_lock = threading.Lock()
        self._requests: list[float] = []
        self._server = ThreadingHTTPServer((host, port), self._handler_class())
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="profile-api", daemon=True
        )

    @property
    def address(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive():
            self._thread.join(timeout=5)

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._dispatch("GET")

            def do_POST(self) -> None:
                self._dispatch("POST")

            def do_PATCH(self) -> None:
                self._dispatch("PATCH")

            def do_DELETE(self) -> None:
                self._dispatch("DELETE")

            def _dispatch(self, method: str) -> None:
                request_id = str(uuid.uuid4())
                try:
                    path = urlparse(self.path).path.rstrip("/") or "/"
                    if path == "/openapi.json" and method == "GET":
                        self._json(HTTPStatus.OK, build_openapi(api.address))
                        return
                    if path == "/docs" and method == "GET":
                        self._html(HTTPStatus.OK, SWAGGER_UI_HTML)
                        return
                    supplied_key = self.headers.get("Authorization", "").removeprefix("Bearer ") or self.headers.get("X-API-Key", "")
                    if api.api_key and not secrets.compare_digest(supplied_key, api.api_key):
                        self._error(HTTPStatus.UNAUTHORIZED, "invalid_api_key", "API key không hợp lệ", request_id)
                        return
                    if not api._allow_request():
                        self._error(HTTPStatus.TOO_MANY_REQUESTS, "rate_limit_exceeded", "Vượt giới hạn request", request_id)
                        return
                    parts = path.split("/")
                    if path == "/health" and method == "GET":
                        self._json(HTTPStatus.OK, {"status": "ok"})
                    elif path == "/health/live" and method == "GET":
                        self._json(HTTPStatus.OK, {"status": "alive"})
                    elif path == "/health/ready" and method == "GET":
                        ready = api.store.ping() and api.worker.is_alive and not api.browser_service.draining
                        self._json(HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE, {"status": "ready" if ready else "not_ready"})
                    elif path == "/api/v1/status" and method == "GET":
                        self._json(HTTPStatus.OK, {"data": {**api.browser_service.counts(), "active_operations": api.operations.active_count(), "worker_alive": api.worker.is_alive, "draining": api.browser_service.draining}})
                    elif len(parts) == 5 and parts[1:4] == ["api", "v1", "operations"] and method == "GET":
                        self._json(HTTPStatus.OK, {"data": api.operations.get(parts[4]).to_dict()})
                    elif len(parts) == 7 and parts[1:4] == ["api", "v1", "profiles"] and parts[5] == "operations":
                        self._operation_route(method, parts[4], parts[6])
                    elif path == "/api/profiles" and method == "GET":
                        self._json(HTTPStatus.OK, {"profiles": [self._profile(item) for item in api.store.list_profiles()]})
                    elif path == "/api/profiles" and method == "POST":
                        body = self._body()
                        profile = api.store.create_profile(str(body.get("name", "")), str(body.get("proxy", "")))
                        self._json(HTTPStatus.CREATED, self._profile(profile))
                    elif len(parts) == 4 and parts[1:3] == ["api", "profiles"]:
                        self._profile_route(method, parts[3])
                    elif len(parts) == 5 and parts[1:3] == ["api", "profiles"]:
                        self._action_route(method, parts[3], parts[4])
                    else:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "Endpoint không tồn tại"})
                except KeyError as exc:
                    self._error(HTTPStatus.NOT_FOUND, "not_found", str(exc), request_id)
                except PayloadTooLargeError as exc:
                    self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "payload_too_large", str(exc), request_id)
                except (ValueError, json.JSONDecodeError) as exc:
                    self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc), request_id)
                except Exception:
                    self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "Lỗi nội bộ", request_id)

            def _profile_route(self, method: str, profile_id: str) -> None:
                profile = self._find_profile(profile_id)
                if method == "GET":
                    self._json(HTTPStatus.OK, self._profile(profile))
                elif method == "PATCH":
                    body = self._body()
                    updated = api.store.update_profile(
                        profile_id,
                        str(body.get("name", profile.name)),
                        str(body.get("proxy", profile.proxy or "")),
                    )
                    self._json(HTTPStatus.OK, self._profile(updated))
                elif method == "DELETE":
                    if api.browser_service.state(profile_id).value != "Stopped":
                        raise ValueError("Phải đóng profile trước khi xóa")
                    api.store.delete_profile(profile_id)
                    self._json(HTTPStatus.OK, {"deleted": True})
                else:
                    self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Method không hợp lệ"})

            def _action_route(self, method: str, profile_id: str, action: str) -> None:
                if method != "POST":
                    self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Method không hợp lệ"})
                    return
                profile = self._find_profile(profile_id)
                if action == "open":
                    cdp_url = api.worker.submit(api.browser_service.open(profile)).result(timeout=60)
                    self._json(HTTPStatus.OK, {"profile_id": profile_id, "status": "Running", "cdp_url": cdp_url})
                elif action == "close":
                    api.worker.submit(api.browser_service.close(profile_id)).result(timeout=30)
                    self._json(HTTPStatus.OK, {"profile_id": profile_id, "status": "Stopped"})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Action không tồn tại"})

            def _operation_route(self, method: str, profile_id: str, action: str) -> None:
                if method != "POST" or action not in {"open", "close"}:
                    raise KeyError("Endpoint không tồn tại")
                profile = self._find_profile(profile_id)
                operation, created = api.operations.create(profile_id, action)
                if created:
                    api.operations.start(operation.id)
                    coroutine = api.browser_service.open(profile) if action == "open" else api.browser_service.close(profile_id)
                    api.operations.observe(operation.id, api.worker.submit(coroutine))
                payload = {"data": operation.to_dict()}
                self.send_response(HTTPStatus.ACCEPTED)
                self.send_header("Location", f"/api/v1/operations/{operation.id}")
                self.send_header("Retry-After", "1")
                self._send_json_headers(payload)

            def _find_profile(self, profile_id: str) -> ProfileConfig:
                for profile in api.store.list_profiles():
                    if profile.id == profile_id:
                        return profile
                raise KeyError("Không tìm thấy profile")

            def _body(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > api.max_body_bytes:
                    raise PayloadTooLargeError("Request body quá lớn")
                if length == 0:
                    return {}
                data = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("JSON body phải là object")
                return data

            def _profile(self, profile: ProfileConfig) -> dict[str, Any]:
                data = profile.to_dict()
                data.pop("fingerprint_seed", None)
                data["status"] = api.browser_service.state(profile.id).value
                data["cdp_url"] = api.browser_service.cdp_url(profile.id)
                return data

            def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
                self.send_response(status)
                self._send_json_headers(payload)

            def _send_json_headers(self, payload: dict[str, Any]) -> None:
                content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def _html(self, status: HTTPStatus, content: str) -> None:
                encoded = content.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _error(self, status: HTTPStatus, code: str, message: str, request_id: str) -> None:
                self._json(status, {"error": {"code": code, "message": message, "request_id": request_id}})

            def log_message(self, format: str, *args: Any) -> None:
                return

        return Handler

    def _allow_request(self) -> bool:
        now = time.monotonic()
        with self._rate_lock:
            self._requests = [item for item in self._requests if now - item < 60]
            if len(self._requests) >= self.requests_per_minute:
                return False
            self._requests.append(now)
            return True