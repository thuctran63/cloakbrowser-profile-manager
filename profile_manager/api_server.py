"""Local HTTP API for profile management and CDP automation access."""

from __future__ import annotations

import json
import logging
import secrets
import threading
import uuid
from concurrent.futures import TimeoutError as FutureTimeoutError
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .browser_service import (
    CLOSE_TIMEOUT,
    LAUNCH_TIMEOUT,
    BrowserOperationError,
    BrowserService,
    BrowserTimeoutError,
    LaunchBusyError,
)
from .devtools import get_cdp_websocket_url
from .models import OpenOptions, ProfileConfig, ProfileSettings
from .openapi import SWAGGER_UI_HTML, build_openapi
from .profile_store import ProfileStore
from .worker import AsyncWorker, WorkerUnavailableError

logger = logging.getLogger(__name__)


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
    ) -> None:
        self.store = store
        self.worker = worker
        self.browser_service = browser_service
        self.api_key = api_key
        self.max_body_bytes = max_body_bytes
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
            timeout = LAUNCH_TIMEOUT + 10

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
                    parts = path.split("/")
                    if path == "/health" and method == "GET":
                        self._json(HTTPStatus.OK, {"status": "ok"})
                    elif path == "/health/live" and method == "GET":
                        self._json(HTTPStatus.OK, {"status": "alive"})
                    elif path == "/health/ready" and method == "GET":
                        ready = api.store.ping() and api.worker.is_alive and not api.browser_service.draining
                        self._json(HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE, {"status": "ready" if ready else "not_ready"})
                    elif path == "/api/v1/status" and method == "GET":
                        self._json(HTTPStatus.OK, {"data": {**api.browser_service.counts(), "worker_alive": api.worker.is_alive, "draining": api.browser_service.draining}})
                    elif path == "/api/v1/diagnostics" and method == "GET":
                        result = api.worker.submit(api.browser_service.diagnostics()).result(timeout=30)
                        self._json(HTTPStatus.OK, {"data": result})
                    elif path == "/api/v1/profiles/close-all" and method == "POST":
                        profile_ids = [profile.id for profile in api.store.list_profiles()]
                        result = api.worker.submit(api.browser_service.close_active(profile_ids)).result(timeout=CLOSE_TIMEOUT + 5)
                        self._json(HTTPStatus.OK, result)
                    elif len(parts) == 6 and parts[1:4] == ["api", "v1", "profiles"] and parts[5] in {"open", "close", "status"}:
                        self._lifecycle_route(method, parts[4], parts[5])
                    elif len(parts) == 6 and parts[1:4] == ["api", "v1", "profiles"] and parts[5] == "preflight" and method == "POST":
                        profile = self._find_profile(parts[4])
                        result = api.worker.submit(api.browser_service.preflight(profile)).result(timeout=60)
                        self._json(HTTPStatus.OK if result["ok"] else HTTPStatus.BAD_GATEWAY, {"data": result})
                    elif path in {"/api/profiles", "/api/v1/profiles"} and method == "GET":
                        self._json(HTTPStatus.OK, {"profiles": [self._profile(item) for item in api.store.list_profiles()]})
                    elif path in {"/api/profiles", "/api/v1/profiles"} and method == "POST":
                        name, proxy, settings = self._profile_payload(self._body())
                        profile = api.store.create_profile(name, proxy, settings)
                        self._json(HTTPStatus.CREATED, self._profile(profile))
                    elif len(parts) == 4 and parts[1:3] == ["api", "profiles"]:
                        self._profile_route(method, parts[3], request_id)
                    elif len(parts) == 5 and parts[1:4] == ["api", "v1", "profiles"]:
                        self._profile_route(method, parts[4], request_id)
                    else:
                        self._error(HTTPStatus.NOT_FOUND, "not_found", "Endpoint không tồn tại", request_id)
                except KeyError as exc:
                    self._error(HTTPStatus.NOT_FOUND, "not_found", str(exc), request_id)
                except PayloadTooLargeError as exc:
                    self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "payload_too_large", str(exc), request_id)
                except (ValueError, json.JSONDecodeError) as exc:
                    self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc), request_id)
                except WorkerUnavailableError:
                    self._error(HTTPStatus.SERVICE_UNAVAILABLE, "worker_unavailable", "Browser worker không khả dụng", request_id)
                except LaunchBusyError as exc:
                    logger.warning("Launch busy [%s] phase=%s cause=%s", request_id, exc.phase, exc.cause)
                    self._error(
                        HTTPStatus.SERVICE_UNAVAILABLE,
                        "launch_busy",
                        str(exc),
                        request_id,
                        headers={"Retry-After": "2"},
                        phase=exc.phase,
                        cause=exc.cause,
                    )
                except BrowserTimeoutError as exc:
                    logger.warning("Browser timeout [%s] phase=%s cause=%s", request_id, exc.phase, exc.cause)
                    self._error(
                        HTTPStatus.REQUEST_TIMEOUT,
                        "browser_operation_timeout",
                        f"Browser operation quá thời hạn ({exc.phase}): {exc.cause}",
                        request_id,
                        phase=exc.phase,
                        cause=exc.cause,
                    )
                except BrowserOperationError as exc:
                    logger.error("Browser operation error [%s] phase=%s cause=%s", request_id, exc.phase, exc.cause)
                    self._error(
                        HTTPStatus(exc.status_code),
                        exc.code,
                        f"{exc} ({exc.phase})",
                        request_id,
                        phase=exc.phase,
                        cause=exc.cause,
                    )
                except FutureTimeoutError as exc:
                    logger.warning("Future timeout [%s] path=%s", request_id, self.path)
                    self._error(
                        HTTPStatus.REQUEST_TIMEOUT,
                        "browser_operation_timeout",
                        "Browser operation quá thời hạn (waiting_worker)",
                        request_id,
                        phase="waiting_worker",
                        cause=str(exc) or "Worker future timed out",
                    )
                except Exception as exc:
                    logger.exception("Unhandled API error [%s] path=%s", request_id, self.path)
                    self._error(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        "internal_error",
                        f"Lỗi nội bộ: {exc}",
                        request_id,
                        cause=str(exc),
                    )

            def _profile_route(self, method: str, profile_id: str, request_id: str) -> None:
                profile = self._find_profile(profile_id)
                if method == "GET":
                    self._json(HTTPStatus.OK, self._profile(profile))
                elif method == "PATCH":
                    body = self._body()
                    if not body:
                        raise ValueError("PATCH body không được để trống")
                    def update() -> ProfileConfig:
                        current = api.store.get_profile(profile_id)
                        name, proxy, settings = self._profile_payload(body, current=current)
                        return api.store.update_profile(profile_id, name, proxy, settings)

                    updated = api.worker.submit(api.browser_service.mutate_profile(profile_id, update)).result()
                    self._json(HTTPStatus.OK, self._profile(updated))
                elif method == "DELETE":
                    api.worker.submit(api.browser_service.mutate_profile(
                        profile_id, lambda: api.store.delete_profile(profile_id), stopped=True,
                    )).result()
                    self._json(HTTPStatus.OK, {"deleted": True})
                else:
                    self._error(
                        HTTPStatus.METHOD_NOT_ALLOWED,
                        "method_not_allowed",
                        "Method không hợp lệ",
                        request_id,
                        {"Allow": "GET, PATCH, DELETE"},
                    )

            def _lifecycle_route(self, method: str, profile_id: str, action: str) -> None:
                expected_method = "GET" if action == "status" else "POST"
                if method != expected_method:
                    raise KeyError("Endpoint không tồn tại")
                if action != "open":
                    profile = self._find_profile(profile_id)
                else:
                    profile = None
                if action == "status":
                    snapshot = api.worker.submit(api.browser_service.runtime_snapshot(profile_id)).result(timeout=5)
                    self._json(HTTPStatus.OK, snapshot)
                    return
                if action == "close":
                    user_data_dir = profile.user_data_dir if profile is not None else None
                    api.worker.submit(
                        api.browser_service.close(profile_id, user_data_dir=user_data_dir)
                    ).result(timeout=CLOSE_TIMEOUT + 5)
                    self._json(HTTPStatus.OK, {"profileId": profile_id, "status": "stopped"})
                    return
                options = OpenOptions.from_dict(self._body())
                future = api.worker.submit(api.browser_service.open_stored(api.store, profile_id, options))
                try:
                    http_url = future.result(timeout=LAUNCH_TIMEOUT + 5)
                except FutureTimeoutError:
                    future.cancel()
                    raise
                websocket_url = get_cdp_websocket_url(http_url)
                self._json(HTTPStatus.OK, {"profileId": profile_id, "status": "running", "ws": websocket_url, "http": http_url, "pid": None})

            def _find_profile(self, profile_id: str) -> ProfileConfig:
                return api.store.get_profile(profile_id)

            def _profile_payload(
                self, body: dict[str, Any], current: ProfileConfig | None = None
            ) -> tuple[str, str, ProfileSettings]:
                allowed = {"name", "proxy", "geoip", "timezone", "locale", "release_channel", "browser_version", "humanize", "human_preset"}
                unknown = set(body) - allowed
                if unknown:
                    raise ValueError(f"Thuộc tính profile không hợp lệ: {', '.join(sorted(unknown))}")
                name = body.get("name", current.name if current else "")
                proxy = body.get("proxy", current.proxy if current else "")
                if not isinstance(name, str):
                    raise ValueError("name phải là chuỗi")
                if proxy is not None and not isinstance(proxy, str):
                    raise ValueError("proxy phải là chuỗi hoặc null")
                base = current.settings if current else ProfileSettings()
                values = {
                    key: body.get(key, getattr(base, key))
                    for key in ("geoip", "timezone", "locale", "release_channel", "browser_version", "humanize", "human_preset")
                }
                return name, proxy or "", ProfileSettings.from_dict(values)

            def _body(self) -> dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as exc:
                    raise ValueError("Content-Length không hợp lệ") from exc
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

            def _error(
                self,
                status: HTTPStatus,
                code: str,
                message: str,
                request_id: str,
                headers: dict[str, str] | None = None,
                *,
                phase: str | None = None,
                cause: str | None = None,
            ) -> None:
                error_body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
                if phase is not None:
                    error_body["phase"] = phase
                if cause is not None:
                    error_body["cause"] = cause
                payload = {"error": error_body}
                self.send_response(status)
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self._send_json_headers(payload)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return Handler

