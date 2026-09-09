from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from profile_manager.api_server import ProfileApiServer
from profile_manager.browser_service import BrowserService
from profile_manager.profile_store import ProfileStore
from profile_manager.worker import AsyncWorker


class TestPageHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"<!doctype html><meta charset=utf-8><title>API E2E</title><h1>Zoom test</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def request(base: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    with urlopen(req, timeout=90) as response:
        return response.status, json.load(response)


def poll(base: str, operation_id: str) -> dict:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        _, payload = request(base, "GET", f"/api/v1/operations/{operation_id}")
        operation = payload["data"]
        if operation["status"] in {"succeeded", "failed"}:
            return operation
        time.sleep(0.25)
    raise TimeoutError("Operation did not finish")


def main() -> None:
    web_server = ThreadingHTTPServer(("127.0.0.1", 0), TestPageHandler)
    web_thread = threading.Thread(target=web_server.serve_forever, daemon=True)
    web_thread.start()
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        store = ProfileStore(root / "app", root / "profiles")
        profile = store.create_profile("Real API geometry test")
        worker = AsyncWorker()
        service = BrowserService(lambda *_args: None)
        server = ProfileApiServer(store, worker, service, port=0)
        server.start()
        try:
            status, accepted = request(
                server.address,
                "POST",
                f"/api/v1/profiles/{profile.id}/operations/open",
                {
                    "pos_x": 8,
                    "pos_y": 8,
                    "width": 600,
                    "height": 400,
                    "page_zoom": 75,
                    "start_url": f"http://127.0.0.1:{web_server.server_port}/",
                },
            )
            assert status == 202
            opened = poll(server.address, accepted["data"]["id"])
            assert opened["status"] == "succeeded", opened
            cdp_url = opened["result"]["cdp_url"]

            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(cdp_url)
                context = browser.contexts[0]
                page = context.pages[0]
                page.wait_for_url(f"http://127.0.0.1:{web_server.server_port}/")
                page.wait_for_timeout(500)
                metrics = page.evaluate("""({
                    innerWidth,
                    outerWidth,
                    dpr: devicePixelRatio,
                    visualScale: visualViewport.scale,
                    rootZoom: getComputedStyle(document.documentElement).zoom,
                })""")
                session = context.new_cdp_session(page)
                window = session.send("Browser.getWindowForTarget")
                session.detach()
                browser.close()

            assert metrics["rootZoom"] in {"1", "normal"}, metrics
            assert metrics["visualScale"] == 1, metrics
            assert metrics["innerWidth"] > 700, metrics
            bounds = window["bounds"]
            assert bounds["left"] == 8 and bounds["top"] == 8, bounds
            assert bounds["width"] == 600 and bounds["height"] == 400, bounds
            print(json.dumps({"open_status": opened["status"], "cdp_url": cdp_url, "metrics": metrics, "window_bounds": bounds}, ensure_ascii=False))

            _, close_accepted = request(
                server.address,
                "POST",
                f"/api/v1/profiles/{profile.id}/operations/close",
            )
            closed = poll(server.address, close_accepted["data"]["id"])
            assert closed["status"] == "succeeded", closed
            print("close_status=succeeded")
        finally:
            worker.submit(service.close_all()).result(timeout=15)
            server.stop()
            worker.stop()
            web_server.shutdown()
            web_server.server_close()


if __name__ == "__main__":
    main()
