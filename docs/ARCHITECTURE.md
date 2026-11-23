# Kiến trúc CloakBrowser Profile Manager

> Tài liệu này mô tả **source hiện tại** của ứng dụng desktop và bản release `v0.3.11`. Đây không phải kiến trúc mục tiêu trong tương lai.

## 1. Bức tranh tổng thể

Ứng dụng là một **desktop local-agent** chạy trên Windows:

- Tkinter cung cấp giao diện quản lý profile.
- `ThreadingHTTPServer` cung cấp API loopback cho automation bên ngoài.
- Một thread riêng sở hữu một asyncio event loop và toàn bộ Playwright async objects.
- Mỗi profile mở thành một Chromium persistent context với thư mục dữ liệu riêng.
- Metadata được lưu trong SQLite; cookie, cache và browser state nằm trong Chromium user-data directory.

```mermaid
flowchart LR
    User[Người dùng] --> UI[Tkinter UI]
    Client[Automation client] -->|HTTP + API key| API[Local API<br/>127.0.0.1]

    UI --> App[ProfileManagerApp]
    API --> Store
    API --> Worker[AsyncWorker<br/>1 asyncio loop]
    App --> Store[ProfileStore]
    App --> Worker

    Worker --> Service[BrowserService]
    Service --> Ext[ExtensionLibrary]
    Service --> Launcher[CloakBrowser launcher]
    Service --> CDP[CDP discovery / validation]

    Launcher --> PW[Playwright driver pool]
    PW --> B1[Chromium profile A]
    PW --> B2[Chromium profile B]
    PW --> BN[Chromium profile N]

    Store --> DB[(profiles.db)]
    Store --> Settings[(settings.json)]
    Store --> ProfileData[("profiles/&lt;id&gt;/user-data")]
    Ext --> Payloads[(managed extension payloads)]
    B1 --> ProfileData
    B2 --> ProfileData
```

## 2. Thành phần và trách nhiệm

| Thành phần | Trách nhiệm |
|---|---|
| `main.py` | Bootstrap source/frozen mode, nạp `.env`, cấu hình binary cache, xử lý `--install-browser`, khởi động Tk main loop. |
| `profile_manager/app.py` | Composition root: tạo store, worker, browser service, API và UI; điều phối thao tác và shutdown. |
| `profile_manager/ui.py`, `profile_manager/views/` | Widget, dialog, page và phản hồi giao diện. Không trực tiếp sở hữu browser. |
| `profile_manager/profile_store.py` | Profile metadata trong SQLite, settings JSON, migration và profile directories. |
| `profile_manager/worker.py` | Một daemon thread tên `browser-worker` sở hữu một asyncio event loop. |
| `profile_manager/browser_service.py` | Nguồn sự thật runtime cho context, state, CDP URL, generation, Playwright pool và lifecycle. |
| `profile_manager/devtools.py` | Khám phá `DevToolsActivePort`; kiểm tra `/json/version` và cached CDP endpoint. |
| `profile_manager/api_server.py` | HTTP API local, authentication, CRUD, health, diagnostics, preflight và lifecycle operations. |
| `profile_manager/extensions.py` | Import, content-addressed storage và assignment extension theo profile. |
| `profile_manager/proxy.py` | Validate/normalize proxy và che credential trong UI/lỗi. |
| `cloakbrowser/cloakbrowser/browser.py` | Chuẩn bị binary/proxy/GeoIP/license/Widevine/flags và gọi Playwright launch. |

## 3. Execution model và ownership

### 3.1 Các thread/process

| Execution owner | Công việc |
|---|---|
| Tk main thread | Toàn bộ widget và UI state. |
| `browser-worker` | Asyncio loop, `BrowserService`, Playwright async API và context callbacks. |
| API server thread | Chạy `serve_forever()`. |
| HTTP request threads | Mỗi request của `ThreadingHTTPServer`; đọc store/operation hoặc submit coroutine. |
| Default executor threads | Blocking preparation qua `asyncio.to_thread()`: binary, GeoIP, filesystem, diagnostics và extension operations. |
| Playwright driver processes | Điều khiển Chromium; được chia sẻ theo pool cấu hình. |
| Chromium processes | Browser persistent riêng cho từng profile đang mở. |

### 3.2 Quy tắc ownership quan trọng

1. **Playwright async objects chỉ được dùng trên worker loop.** Không chuyển context/page/session sang HTTP hoặc Tk threads.
2. Blocking preparation được đưa qua `asyncio.to_thread()`; không khóa event loop chung.
3. UI callback từ worker được chuyển về Tk thread bằng `root.after(...)`.
4. API request không chạy browser trực tiếp; nó submit coroutine qua `AsyncWorker`.

### 3.3 Synchronization

- `BrowserService._locks[profile_id]`: serialize lifecycle của cùng profile. Nhiều caller mở cùng profile xếp hàng trên lock này.
- `BrowserService._pending_opens` với `MAX_PENDING_OPENS = 24`: chặn số launch đang chờ, vượt ngưỡng thì raise `LaunchBusyError`.
- `_launch_slots = asyncio.Semaphore(2)`: giới hạn số launch Chromium chạy song song toàn cục. Đây là hàng đợi hữu hạn thật sự cho tài nguyên nặng.
- `_playwright_locks[slot]`: bảo vệ lazy start/stop từng Playwright instance.
- `_generation`: ngăn callback context cũ xóa runtime của browser vừa mở lại.
- `_close_tasks[profile_id]`: giữ close task đang chạy để lần `close()` sau chờ chung một task thay vì đóng hai lần.
- `AsyncWorker._state_lock`: serialize submit với shutdown; coroutine bị từ chối được đóng.
- SQLite mở connection theo operation, dùng WAL, foreign keys và busy timeout.

## 4. Luồng mở browser

```mermaid
sequenceDiagram
    participant Caller as UI hoặc API
    participant Worker as AsyncWorker
    participant Service as BrowserService
    participant Prep as Executor thread
    participant PW as Playwright
    participant Chrome as Chromium

    Caller->>Worker: submit service.open(profile, options)
    Worker->>Service: open()
    Service->>Service: reconcile cached RUNNING/CDP
    Service->>Service: lấy per-profile lock
    Service->>Service: xếp hàng vào launch slot, publish state = STARTING
    Service->>Prep: mkdir, Preferences, xóa stale DevToolsActivePort
    Prep-->>Service: prepared
    Service->>Prep: binary + GeoIP + proxy + license + Widevine
    Prep-->>Service: immutable launch parameters
    Service->>PW: launch_persistent_context
    PW->>Chrome: spawn persistent browser
    Chrome-->>PW: BrowserContext
    Service->>Service: discover/validate CDP
    Service->>PW: page/window options
    Service->>Service: atomic publish context + CDP
    Service->>Service: state = RUNNING
    Service-->>Caller: CDP URL
```

### Các bước chính

1. `open()` gọi reconciliation nếu runtime đang cho rằng profile là `RUNNING`.
2. Cached CDP được kiểm tra off-loop. Nếu chết, state cũ chỉ bị xóa khi generation, context và URL vẫn khớp snapshot.
3. Nếu browser vẫn khỏe, service áp lại geometry cần thiết và trả URL hiện tại.
4. Nếu cần launch, service lấy per-profile lock và giành một slot trong `_launch_slots`, nên hai caller cùng profile không launch song song và tổng số launch đồng thời bị chặn ở 2. Blocking preparation chạy trong executor thread nên không bị cancellation của caller hủy giữa chừng.
5. Filesystem preparation và CloakBrowser synchronous preparation chạy trong executor thread.
6. Playwright protocol call chạy trên worker loop, có tổng timeout `LAUNCH_TIMEOUT = 60s`.
7. `DevToolsActivePort` phải mới hơn thời điểm launch; `/json/version` phải trả WebSocket endpoint đúng port.
8. Context và CDP URL chỉ được publish khi toàn bộ launch thành công.

### Browser identity

Mỗi profile có:

- fingerprint seed bền vững;
- user-data directory riêng;
- proxy/GeoIP/timezone/locale riêng;
- optional extensions và humanization;
- dynamic CDP port chỉ bind `127.0.0.1`.

## 5. Luồng đóng và crash

### Close chủ động

1. `close(profile_id)` lấy per-profile lock.
2. Nếu launch đang chạy, lấy per-profile lock và chờ launch nhả lock đó.
3. Chờ launch cleanup hoàn tất.
4. Gọi `context.close()` với `CLOSE_TIMEOUT = 15s`.
5. Dọn context, CDP URL, Playwright slot assignment và chuyển `STOPPED`.
6. Nếu close timeout, profile chuyển `ERROR` và caller nhận lỗi.

### Browser đóng/crash ngoài ứng dụng

Khi context phát event `close`, `_handle_context_closed()`:

- lấy per-profile lock;
- so sánh generation và object identity;
- bỏ qua callback stale;
- dọn runtime và chuyển `STOPPED`.

Nếu event chưa đến nhưng cached CDP đã chết, lần `open()` kế tiếp sẽ reconcile rồi relaunch.

## 6. Playwright pool

`playwright_instances` trong settings nằm trong khoảng `1–20`.

- Profile mới được gán vào slot có ít assignment nhất.
- Nhiều browser contexts có thể dùng chung một Playwright driver.
- Pool giảm overhead so với một driver cho mỗi profile.
- Đây **không phải** hard limit số browser.
- Launch được chặn ở `asyncio.Semaphore(2)` để giới hạn contention lúc startup, không phải để tuần tự hóa hoàn toàn.

```mermaid
flowchart TD
    Profiles[Profiles cần chạy] --> Balance[Least-loaded slot assignment]
    Balance --> PW1[Playwright slot 0]
    Balance --> PW2[Playwright slot 1]
    PW1 --> A[Chromium A]
    PW1 --> B[Chromium B]
    PW2 --> C[Chromium C]
    PW2 --> D[Chromium D]
```

## 7. API và operation model

API chỉ bind `127.0.0.1` và dùng API key.

Open/close dùng response đồng bộ:

1. HTTP request thread submit coroutine vào worker.
2. Request thread chờ `concurrent.futures.Future` với deadline lớn hơn timeout nội bộ.
3. Worker thực hiện lifecycle trên asyncio loop duy nhất.
4. Open trả trực tiếp CDP HTTP/WebSocket endpoint; close trả trạng thái `stopped`.
5. Status chỉ đọc snapshot cache trên worker loop, không probe hoặc launch browser.

Mỗi HTTP request có thread riêng nên một launch không khóa API server. Timeout thực sự nằm trong `BrowserService`; timeout ở HTTP thread chỉ là safety margin.

## 8. Persistence

```text
.profile-manager/
├── profiles.db
├── settings.json
└── extensions/
    ├── payloads/{digest}/
    ├── .staging/
    └── .trash/

profiles/{profile-id}/
└── user-data/
    ├── Default/Preferences
    ├── DevToolsActivePort   # chỉ khi browser chạy
    └── ... Chromium state
```

### Durable

- SQLite: profile metadata và extension assignments.
- `settings.json`: API host/port/key, profile root và Playwright pool size.
- `user-data`: cookies, cache, local storage, history và Chromium preferences.
- Extension payloads: lưu content-addressed để tránh duplicate.

### Ephemeral

- Browser contexts, CDP URLs và runtime states.
- Launch tasks, locks, generation và slot assignments.
- API operation history.

Sau process restart, ứng dụng không attach lại browser cũ; runtime mặc định trở về `STOPPED`.

## 9. Reliability và failure boundaries hiện có

| Failure | Cơ chế hiện tại |
|---|---|
| Blocking binary/GeoIP/filesystem work | `asyncio.to_thread()`, không block worker loop. |
| Launch treo | Timeout 60 giây, cancellation-safe cleanup. |
| Close treo | Timeout 15 giây, state `ERROR`. |
| Playwright stop treo | Timeout 15 giây. |
| Nhiều open cùng profile | Per-profile `_locks[profile_id]`; caller sau chờ và tái dùng context đã có. |
| Quá nhiều launch cùng lúc | `_pending_opens` chặn ở `MAX_PENDING_OPENS = 24`, vượt ngưỡng raise `LaunchBusyError`; `_launch_slots` chặn ở 2 launch song song. |
| Close trong lúc launch | Close chờ per-profile lock, sau đó đóng context đã publish. |
| Crash giữa delete profile | `delete_profile` đổi tên thư mục sang tombstone trước khi xóa row; `_reclaim_abandoned_deletes()` lúc khởi động khôi phục tombstone còn row và dọn tombstone mồ côi. |
| Stale context callback | Generation + identity check. |
| Cached CDP chết | Probe off-loop và conditional reconciliation trước reuse. |
| Worker submit/shutdown race | Lock-protected stopping state; rejected coroutine được đóng. |
| Worker không dừng | `stop()` raise timeout thay vì báo thành công giả. |
| Proxy credential trong launch error | Redaction trước khi publish. |
| Partial settings/preferences write | Temp file + atomic replace. |
| Extension import/delete lỗi | Staging/trash và rollback. |
| SQLite contention | WAL + busy timeout. |

## 10. Startup và shutdown

### Startup

1. Xác định project root cạnh source hoặc EXE.
2. Nạp `.env` và đặt binary cache mặc định vào `binaries/`.
3. Khởi tạo store/migrations.
4. Khởi động worker thread.
5. Tạo extension library và browser service.
6. Bind/start local API.
7. Dựng UI và vào Tk main loop.

### Shutdown

1. UI chuyển sang shutting-down và service bắt đầu draining.
2. API server dừng nhận request.
3. `close_all()` cancel launch và đóng các profile đã biết.
4. Shared Playwright instances được stop có timeout.
5. Worker loop dừng và Tk root bị destroy.

## 11. Build và release

```mermaid
flowchart LR
    Source[Source workspace] --> Deps[requirements-build.txt]
    Deps --> Tests[57 release tests]
    Tests --> PI[PyInstaller one-file EXE]
    PI --> Check[Dependency warning checks]
    Check --> Stage[EXE + docs + empty binaries/profiles]
    Stage --> Zip[Windows x64 ZIP]
    Zip --> Hash[SHA256SUMS.txt]
```

- Entry point: `main.py`.
- PyInstaller tạo windowed one-file EXE.
- Local CloakBrowser source được dùng trong build hiện tại.
- `geoip2.database`, `maxminddb` và `socksio` được explicit hidden-import.
- Build dừng nếu production dependencies thiếu hoặc PyInstaller báo không bundle chúng.
- Chromium binary không nằm trong ZIP; `Install-Browser.cmd` gọi EXE với `--install-browser` để tải vào `binaries/`.

## 12. Những gì kiến trúc hiện tại chưa làm

Đây là các giới hạn có chủ ý hoặc chưa được triển khai:

1. Không có process-per-profile supervisor hoặc Windows Job Object.
2. Không persist PID/process handle và không attach lại Chromium sau app restart.
3. Không có periodic health polling; CDP reconciliation hiện chạy khi tái `open()`.
4. Close timeout chưa có fallback `terminate -> kill` bằng process handle.
5. `_invalidate_playwright_slot()` chỉ restart slot khi một lifecycle call phát hiện driver transport đã chết; chưa có detector chủ động. Không có periodic health polling, xem mục 3.
6. API chưa trả browser PID vì Playwright persistent context không expose process handle công khai.
7. Readiness hiện chưa chứng minh event-loop responsiveness bằng heartbeat có deadline.
8. Proxy credential và API key đang lưu plain text local.
9. Release chưa code-sign và không có installer/auto-update.

## 13. Định hướng nâng cấp khi có bằng chứng vận hành

Ưu tiên theo chi phí thấp đến cao:

1. Worker heartbeat cho readiness.
2. Theo dõi process handle để close timeout có terminate/kill fallback.
3. Chỉ chuyển sang process-per-profile khi telemetry chứng minh shared worker/driver vẫn tạo blast radius không chấp nhận được.

Không cần checkpointing, distributed queue hoặc orchestration service cho mô hình desktop local hiện tại.
