# Plan triển khai: Đơn giản hoá CloakBrowser Local API sang mô hình đồng bộ

**Mục tiêu:** Thay mô hình `open`/`close` bất đồng bộ (202 Accepted + operation polling) bằng API đồng bộ kiểu MostLogin/Multilogin (gọi `open`, chờ, nhận thẳng CDP URL). Giữ nguyên toàn bộ cơ chế correctness ở tầng dưới (lock, generation, reconciliation, timeout) — chỉ thay đổi cách **API server** giao tiếp với `AsyncWorker`, không viết lại `BrowserService`.

**Không làm trong plan này:** không đổi execution model (vẫn 1 asyncio loop trong `browser-worker` thread), không đổi Playwright pool logic, không đổi persistence layer.

---

## 0. Điều kiện tiên quyết trước khi bắt đầu

1. Đọc kỹ 3 file sau trước khi sửa gì:
   - `profile_manager/api_server.py`
   - `profile_manager/operations.py`
   - `profile_manager/worker.py`
2. Xác nhận `AsyncWorker` hiện có API dạng `submit(coro) -> concurrent.futures.Future` (chạy trên thread khác, không phải asyncio.Future). Nếu tên method khác, đổi tên tương ứng trong các đoạn code dưới đây.
3. Tạo branch riêng: `refactor/sync-open-close-api`. Không sửa trực tiếp trên main.
4. Chạy toàn bộ 39 release test hiện có trước khi bắt đầu, ghi lại kết quả baseline (pass/fail count) để so sánh sau khi xong.

---

## 1. Thiết kế API mới (chốt trước khi code)

### 1.1 Endpoint contract

| Method | Path | Mô tả | Request body | Response 200 |
|---|---|---|---|---|
| POST | `/profiles/{id}/open` | Mở (hoặc reuse) profile, chờ tới khi có CDP sẵn sàng | `{}` hoặc options override (geometry, headless...) | `{profileId, status:"running", ws, http, pid}` |
| POST | `/profiles/{id}/close` | Đóng profile, chờ tới khi đóng xong | `{}` | `{profileId, status:"stopped"}` |
| POST | `/profiles/close-all` | Đóng toàn bộ profile đang chạy | `{}` | `{closed: [ids], failed: [{id, error}]}` |
| GET | `/profiles/{id}/status` | Đọc state cache hiện tại, **không** probe CDP, không launch | — | `{profileId, status}` |
| GET | `/health` | Health check server | — | `{ok: true}` |

Response lỗi (áp dụng cho `open`/`close`):

| HTTP code | Khi nào |
|---|---|
| 404 | profile_id không tồn tại trong `ProfileStore` |
| 408 | vượt `LAUNCH_TIMEOUT` (open) hoặc `CLOSE_TIMEOUT` (close) |
| 409 | profile đang ở state không hợp lệ để thao tác (vd close khi đã STOPPED — trả 200 idempotent thay vì lỗi, xem 1.3) |
| 500 | launch/close thất bại vì lý do khác (kèm `error` field mô tả nguyên nhân, đã redact credential) |
| 401 | thiếu/sai API key |

### 1.2 Body response chi tiết cho `open`

```json
{
  "profileId": "abc123",
  "status": "running",
  "ws": "ws://127.0.0.1:9222/devtools/browser/xxxx",
  "http": "http://127.0.0.1:9222",
  "pid": 18234
}
```

`pid` lấy từ Playwright launch nếu hiện có expose; nếu chưa có, field này để `null` ở giai đoạn 1 và ghi TODO — **không** block plan vì thiếu pid (xem mục 6, item optional).

### 1.3 Idempotency rules (chốt để tránh tranh cãi khi code)

- Gọi `open` cho profile đã `RUNNING` với CDP còn sống → trả `200` ngay với thông tin hiện tại, không relaunch (giữ nguyên hành vi cũ).
- Gọi `close` cho profile đã `STOPPED` → trả `200` ngay, không lỗi.
- Gọi `open` hai lần đồng thời cho cùng id → cả hai request đều chờ chung một launch task (canonical launch task đã có sẵn), cả hai nhận cùng kết quả khi xong.

---

## 2. Thay đổi ở `profile_manager/api_server.py`

### 2.1 Xoá bỏ

- Toàn bộ handler trả `202 Accepted` cho open/close.
- Toàn bộ route `GET /operations/{operation_id}` và bất kỳ route liệt kê operation.
- Import và mọi tham chiếu tới `OperationRegistry` trong file này.

### 2.2 Thêm mới — pseudocode cho handler `open`

```python
def handle_open_profile(self, profile_id: str, body: dict) -> None:
    if not self.store.profile_exists(profile_id):
        self._respond(404, {"error": "profile_not_found", "profileId": profile_id})
        return

    coro = self.browser_service.open(profile_id, options=body)
    future = self.worker.submit(coro)  # concurrent.futures.Future

    try:
        # timeout hơi lớn hơn LAUNCH_TIMEOUT nội bộ để tránh race giữa
        # timeout của asyncio.wait_for bên trong service và timeout ở đây
        result = future.result(timeout=LAUNCH_TIMEOUT_S + 5)
    except FutureTimeoutError:
        self._respond(408, {"error": "launch_timeout", "profileId": profile_id})
        return
    except WorkerUnavailableError:
        self._respond(503, {"error": "worker_unavailable", "profileId": profile_id})
        return
    except BrowserLaunchError as e:
        self._respond(500, {"error": "launch_failed", "detail": redact(str(e))})
        return

    self._respond(200, {
        "profileId": profile_id,
        "status": "running",
        "ws": result.cdp_ws_url,
        "http": result.cdp_http_url,
        "pid": getattr(result, "pid", None),
    })
```

Áp dụng pattern tương tự cho `handle_close_profile` (dùng `CLOSE_TIMEOUT_S`, trạng thái trả về `"stopped"`), và `handle_close_all` (lặp qua danh sách profile đang biết là RUNNING, gọi song song bằng nhiều future, chờ `concurrent.futures.wait(..., timeout=...)`, gom kết quả thành `closed`/`failed`).

### 2.3 HTTP server timeout

Trong khởi tạo `ThreadingHTTPServer` (hoặc handler class), đặt:

```python
class Handler(BaseHTTPRequestHandler):
    timeout = LAUNCH_TIMEOUT_S + 10  # đủ lớn hơn mọi timeout nội bộ
```

Xác nhận `ThreadingHTTPServer` không tự đóng connection sớm hơn giá trị này — nếu framework HTTP hiện dùng (http.server thuần hay Flask/FastAPI wrapper) có config timeout riêng, đặt đồng bộ ở đó.

### 2.4 GET /profiles/{id}/status

Không được gọi `service.open()` hay bất kỳ probe CDP nào. Chỉ đọc snapshot cache hiện có (dùng lại cơ chế `_snapshot_lock` sẵn có trong `BrowserService`, expose thêm 1 method đọc-only nếu chưa có, vd `service.peek_state(profile_id)`).

---

## 3. Thay đổi ở `profile_manager/worker.py`

Không cần đổi asyncio loop hay `_state_lock`. Chỉ cần đảm bảo:

1. `submit(coro)` khi worker đang ở trạng thái `stopping`/`stopped` phải raise ngay một exception rõ ràng (`WorkerUnavailableError`), không im lặng trả `None` — để handler ở bước 2.2 catch đúng.
2. Nếu `submit` hiện tại trả `concurrent.futures.Future` bằng `asyncio.run_coroutine_threadsafe(coro, loop)`, giữ nguyên — đây chính là cơ chế cần cho `future.result(timeout=...)` ở API layer.

---

## 4. Xoá bỏ `profile_manager/operations.py`

1. Xoá import của module này ở `app.py` và `api_server.py`.
2. Xoá khởi tạo `OperationRegistry()` trong composition root (`app.py`).
3. Grep toàn repo cho `OperationRegistry`, `operation_id`, `"running"` (chuỗi liên quan operation state) để đảm bảo không còn tham chiếu chết.
4. Nếu có UI (Tkinter) nào hiển thị operation history, xoá luôn phần đó hoặc thay bằng đọc trực tiếp `status` hiện tại của các profile.

---

## 5. Thay đổi ở `profile_manager/browser_service.py`

**Không cần sửa logic**, nhưng cần kiểm tra 2 điểm để tương thích với API đồng bộ:

1. `open()` phải propagate exception rõ ràng khi timeout/fail (không nuốt lỗi thành trạng thái ERROR âm thầm) — để handler ở bước 2.2 bắt được đúng loại exception và map ra HTTP status code.
2. Nếu chưa có, thêm field `pid` vào object trả về từ `open()` (lấy từ `browser_process.pid` nếu Playwright/CloakBrowser launcher expose được; nếu launch qua `launch_persistent_context` không expose pid trực tiếp, kiểm tra `context.browser.process` hoặc tương đương trong `cloakbrowser/cloakbrowser/browser.py`). Nếu không khả thi trong scope này, để `pid=None` và ghi rõ trong response — **không được block toàn bộ plan vì thiếu pid**.

---

## 6. Thay đổi cấu hình (`_launch_slots`)

Tách riêng thành 1 commit độc lập, sau khi phần API đồng bộ đã chạy ổn:

1. Đổi `_launch_slots = asyncio.Semaphore(1)` thành giá trị lấy từ settings, mặc định bằng `min(playwright_instances, 4)` thay vì cứng `1`.
2. Thêm field `max_concurrent_launches` vào `settings.json` schema, có migration default nếu field chưa tồn tại (dùng pattern temp-file + atomic replace đã có sẵn cho settings).
3. Test: mở đồng thời N > 1 profile, xác nhận không có race trên cùng `user-data-dir` (mỗi profile dùng dir riêng nên đây chủ yếu là test load, không phải test correctness).

---

## 7. Danh sách test bắt buộc (viết mới hoặc sửa test cũ)

Với mỗi test, ghi rõ **input**, **hành vi mong đợi**, **cách assert**:

1. **Open profile chưa từng mở** → gọi `POST /profiles/{id}/open`, assert response 200 trong thời gian < `LAUNCH_TIMEOUT`, `ws`/`http` không rỗng, thực sự connect được tới CDP endpoint trả về (dùng `websockets` hoặc `requests.get(http + "/json/version")`).
2. **Open profile đã RUNNING** → gọi open 2 lần liên tiếp, lần 2 phải trả cùng `ws` (không relaunch), thời gian phản hồi lần 2 phải nhanh (< 1s, không đợi launch timeout).
3. **Open đồng thời 2 request cho cùng id** (dùng `threading.Thread` hoặc `concurrent.futures`) → cả hai response phải giống nhau về `ws`, chỉ có 1 tiến trình Chromium được spawn (assert bằng đếm process con hoặc mock launch call count = 1).
4. **Close profile đang RUNNING** → assert 200, sau đó `GET /status` trả `stopped`.
5. **Close profile đã STOPPED** → assert vẫn 200 (idempotent), không lỗi.
6. **Open với profile_id không tồn tại** → assert 404.
7. **Timeout giả lập**: mock launch bị treo (sleep dài hơn `LAUNCH_TIMEOUT`), assert response 408 đúng thời điểm timeout, và profile chuyển sang state `ERROR` phía sau (kiểm bằng `GET /status` sau đó).
8. **Worker đang shutdown**: gọi open trong lúc `AsyncWorker.stop()` đang chạy, assert response 503 kèm `error: worker_unavailable`.
9. **Close-all** với 3 profile đang chạy, 1 profile bị mock lỗi khi close → assert response liệt kê đúng 2 trong `closed`, 1 trong `failed`.
10. **Regression toàn bộ 39 test release cũ** phải pass, trừ các test liên quan trực tiếp tới `OperationRegistry`/polling (các test đó xoá hoặc viết lại theo mô hình mới).
11. **Proxy credential redaction**: giả lập launch fail vì proxy sai, assert response 500 không chứa proxy password trong `detail`.

---

## 8. Cập nhật tài liệu

1. `Kiến trúc CloakBrowser Profile Manager.md` mục 7 ("API và operation model") — viết lại hoàn toàn theo mô hình đồng bộ, xoá đoạn mô tả polling.
2. Mục 12 ("Những gì kiến trúc hiện tại chưa làm") — xoá dòng về operation history TTL (không còn áp dụng), thêm dòng mới nếu pid chưa expose được.
3. Cập nhật sequence diagram mục 4 nếu cần vẽ lại nhánh API call (không bắt buộc, chỉ nếu có thời gian).
4. Cập nhật mọi ví dụ client (Python/JS) trong README hoặc docs sang gọi đồng bộ, bỏ đoạn polling loop cũ.

---

## 9. Thứ tự thực hiện (sequencing) — làm đúng thứ tự để mỗi bước tự test được

1. Viết test cho hành vi mới trước (mục 7, item 1–6) — sẽ fail vì code chưa đổi (TDD).
2. Sửa `api_server.py` theo mục 2.
3. Sửa `worker.py` theo mục 3 (nếu cần).
4. Chạy lại test mục 7 item 1–6, phải pass.
5. Xoá `operations.py` và dọn tham chiếu (mục 4).
6. Chạy full test suite, xử lý mọi import lỗi còn sót.
7. Thêm test timeout/shutdown/close-all (mục 7, item 7–9, 11).
8. Cập nhật tài liệu (mục 8).
9. Commit riêng cho `_launch_slots` (mục 6) sau khi mọi thứ trên đã merge và ổn định — không gộp chung để dễ revert nếu có vấn đề.

---

## 10. Rollback plan

Nếu phát hiện vấn đề nghiêm trọng sau khi merge (vd HTTP thread bị block hàng loạt do client không set timeout phía họ, gây nghẽn `ThreadingHTTPServer`):

1. Revert commit ở bước 2 (api_server.py) về bản `202` cũ — giữ `operations.py` chưa xoá cho tới khi chắc chắn ổn định (khuyến nghị: **không xoá `operations.py` ở cùng PR với đổi api_server.py**; xoá ở PR riêng sau khi bản đồng bộ chạy ổn định tối thiểu vài ngày).
2. Vì `BrowserService`/`worker.py` không đổi logic, rollback tầng API không ảnh hưởng dữ liệu hay state runtime.

---

## 11. Checklist bàn giao cho ChatGPT khi implement

- [ ] Đọc 3 file tiên quyết ở mục 0.
- [ ] Tạo branch riêng.
- [ ] Viết OpenAPI yaml đầy đủ (dùng bảng mục 1.1 làm nguồn) làm file `openapi.yaml` trong repo, dùng để generate client/test.
- [ ] Implement theo đúng thứ tự mục 9.
- [ ] Mỗi bước có PR/commit riêng, message rõ ràng theo số mục trong plan này (vd `feat: sync open/close handlers (plan §2)`).
- [ ] Không sửa `browser_service.py` logic ngoài phạm vi mục 5.
- [ ] Không đổi `_launch_slots` cho tới khi phần đồng bộ đã pass toàn bộ test.
- [ ] Báo cáo lại: danh sách file đã đổi, số test pass/fail so với baseline, và bất kỳ điểm nào trong plan không khớp với code thực tế (vd tên method khác, chưa có `pid` expose).