# CloakBrowser Profile Manager

Ứng dụng desktop Python/Tkinter quản lý các persistent CloakBrowser profile.

> Chromium đã patch không nằm trong source hoặc file release. Ứng dụng tải nó
> trực tiếp từ kênh chính thức của CloakHQ và xác minh chữ ký/checksum theo
> CloakBrowser Binary License.

## Bản Windows portable

1. Tải `CloakBrowser-Profile-Manager-v*-win-x64.zip` từ GitHub Releases.
2. Giải nén ZIP vào thư mục có quyền ghi.
3. Chạy `Install-Browser.cmd` một lần để tải browser từ CloakHQ.
4. Chạy `CloakBrowser-Profile-Manager.exe`.

`binaries`, `profiles`, `.profile-manager` và `.env` được đọc/ghi cạnh EXE. Không
di chuyển riêng EXE ra khỏi thư mục portable nếu muốn giữ nguyên dữ liệu.

## Chạy ứng dụng

```powershell
& "C:/Program Files/Python311/python.exe" .\main.py
```

Ứng dụng đọc `.env` ở thư mục project. Binary hiện được tìm qua `CLOAKBROWSER_CACHE_DIR` và phải nằm trong cấu trúc cache phiên bản của CloakBrowser.

Để cài binary chính thức khi chạy từ source:

```powershell
& "C:/Program Files/Python311/python.exe" .\main.py --install-browser
```

## Cài đặt development

Dependency CloakBrowser được pin vào commit bất biến trong `requirements.txt`:

```powershell
& "C:/Program Files/Python311/python.exe" -m pip install -r requirements.txt
```

## Chức năng

- Tạo profile với UUID và fingerprint seed ngẫu nhiên, cố định theo profile.
- Tự động đồng bộ timezone, locale và WebRTC theo IP thoát; profile cũ cũng được migration sang mặc định này.
- Cho phép override timezone/locale, chọn `stable`/`preview`, pin phiên bản browser và bật humanization nội bộ.
- Sửa tên và proxy HTTP/HTTPS/SOCKS5.
- Xóa toàn bộ metadata, cookie, cache và history sau khi xác nhận.
- Open/Close nhiều profile độc lập với lock theo profile, launch queue và giới hạn tài nguyên.
- Chọn thư mục mặc định cho profile tạo mới trong Settings.
- Tự cập nhật trạng thái khi cửa sổ Chromium được đóng thủ công.
- SQLite/WAL cho metadata, tự migration một lần từ `profiles.json` cũ.
- Local REST API bất đồng bộ để CRUD/Open/Close và cấp CDP endpoint cho automation.

## API v1

API mặc định chạy tại `http://127.0.0.1:8765`. URL, port và API key được hiển thị và cấu hình trong cửa sổ **Settings**. API chỉ bind tại localhost để không công khai quyền điều khiển browser ra mạng.

### OpenAPI và Swagger UI

- Swagger UI: `http://127.0.0.1:8765/docs`
- OpenAPI 3.1 JSON: `http://127.0.0.1:8765/openapi.json`

API key mạnh được tạo tự động ở lần chạy đầu. Endpoint tài liệu cũng yêu cầu API
key. Trong
Swagger UI, bấm **Authorize** rồi nhập API key bằng Bearer token hoặc
`X-API-Key`.

OpenAPI mô tả đầy đủ các endpoint hiện có: health/readiness, runtime status,
profile CRUD, operation Open/Close bất đồng bộ và polling operation.

### Xác thực

Gửi một trong hai header:

```http
Authorization: Bearer <api-key>
X-API-Key: <api-key>
```

`Authorization: Bearer` được khuyến nghị. API và CDP luôn bind tại `127.0.0.1`; không proxy chúng trực tiếp ra Internet.

### Lifecycle bất đồng bộ

Mở browser không giữ HTTP connection trong lúc Chromium khởi động:

```http
POST /api/v1/profiles/{profile_id}/operations/open
```

Có thể truyền vị trí, kích thước cửa sổ native và mức page zoom theo từng lần mở:

```json
{
	"pos_x": 8,
	"pos_y": 8,
	"width": 470,
	"height": 349,
	"page_zoom": 75,
	"start_url": "https://www.facebook.com"
}
```

`width`/`height` chỉ điều khiển kích thước cửa sổ native và không bật viewport
emulation; `page_zoom` là phần trăm native Chromium zoom trong khoảng `25–100`
(ví dụ `75` là 75%), được áp dụng trước khi browser khởi động và không dùng CSS
zoom. `pos_x` phải đi cùng `pos_y`;
`width` phải đi cùng `height`. Các tùy chọn chỉ
áp dụng runtime, không thay đổi fingerprint hoặc metadata profile. Chromium và
Windows có thể tự nâng kích thước quá nhỏ lên kích thước cửa sổ tối thiểu theo
DPI/theme hiện tại.

Khi truyền `start_url` (`http://` hoặc `https://`), browser khởi động bằng Chromium
app mode: không có tab bar, thanh địa chỉ hoặc toolbar. Bỏ `start_url` để mở cửa
sổ Chromium bình thường. App mode chỉ được quyết định lúc khởi động profile.

Response `202 Accepted` có `Location` và `Retry-After: 1`:

```json
{
	"data": {
		"id": "operation-uuid",
		"profile_id": "profile-uuid",
		"kind": "open",
		"status": "running",
		"created_at": "2026-01-01T00:00:00+00:00",
		"started_at": "2026-01-01T00:00:00+00:00",
		"completed_at": null,
		"result": null,
		"error": null
	}
}
```

Poll URL trong `Location`:

```http
GET /api/v1/operations/{operation_id}
```

Khi thành công, `status` là `succeeded` và `result.cdp_url` chứa endpoint loopback. Khi thất bại, `status` là `failed` và `error` chứa code/message đã lọc. Gọi Open nhiều lần trong lúc operation đang chạy dùng chung operation; Open một profile đã chạy trả lại cùng CDP URL.

Đóng browser tương tự:

```http
POST /api/v1/profiles/{profile_id}/operations/close
```

### Kết nối Playwright

```python
from playwright.async_api import async_playwright

async with async_playwright() as playwright:
		browser = await playwright.chromium.connect_over_cdp(cdp_url)
		context = browser.contexts[0]
		page = context.pages[0] if context.pages else await context.new_page()
		await page.goto("https://example.com")
		await browser.close()  # Chỉ ngắt client CDP; dùng Close API để đóng profile.
```

### Profile CRUD

Các endpoint CRUD:

- `GET/POST /api/v1/profiles`
- `GET/PATCH/DELETE /api/v1/profiles/{id}`

Route `/api/profiles` cũ vẫn được giữ để tương thích. Payload hỗ trợ `geoip`,
`timezone`, `locale`, `release_channel`, `browser_version`, `humanize` và
`human_preset`; thuộc tính lạ bị từ chối.

Profile response không trả `fingerprint_seed`. Không thể sửa hoặc xóa profile khi browser không ở trạng thái `Stopped`.

### Health và runtime status

- `GET /health` — tương thích cũ.
- `GET /health/live` — HTTP server đang sống.
- `GET /health/ready` — database, worker sẵn sàng và service chưa draining.
- `GET /api/v1/status` — số profile `starting`, `running`, active operations và trạng thái worker/draining.
- `GET /api/v1/diagnostics` — wrapper, binary, tier, platform và runtime.
- `POST /api/v1/profiles/{id}/preflight` — kiểm tra IP thoát và tính nhất quán identity trước khi launch.

### Status code và lỗi

- `200` thành công; `201` đã tạo profile; `202` đã nhận lifecycle operation.
- `400` body/tham số không hợp lệ; `401` API key sai/thiếu; `404` resource không tồn tại.
- `413` body vượt 64 KiB; `500` lỗi nội bộ đã ẩn chi tiết; `503` readiness thất bại.

Error envelope:

```json
{
	"error": {
		"code": "invalid_request",
		"message": "Mô tả an toàn",
		"request_id": "uuid"
	}
}
```

Settings cho phép cấu hình launch đồng thời (`1–20`) và tổng browser
(`launch–100`). Local API không giới hạn số request/phút; giới hạn session thực
tế vẫn phụ thuộc license/tier CloakBrowser.

## Dữ liệu

Mặc định metadata nằm trong `.profile-manager/profiles.db` (SQLite/WAL); browser data nằm trong `profiles/<uuid>/user-data/`. Mỗi profile lưu đường dẫn tuyệt đối, vì vậy đổi Settings không di chuyển profile cũ. Lần đầu nâng cấp, `profiles.json` được import transactionally và sao lưu thành `profiles.json.migrated`.

Proxy có thể nhập dưới dạng `http://user:pass@host:port` hoặc `socks5://host:port`. Proxy vẫn được lưu local dạng plain text trong SQLite; không commit `.profile-manager`, không dùng API/CDP trên máy dùng chung và không log credential.

Chromium nhận `--remote-debugging-port=0`; ứng dụng đọc file `DevToolsActivePort` mới và xác thực `/json/version` trước khi công bố CDP URL. Cách này tránh race do chọn trước một free port.

Humanization chỉ bọc thao tác Playwright chạy trong process Profile Manager.
Client ngoài kết nối qua CDP phải tự humanize chuột, bàn phím và scroll ở phía
client; lớp này không tự truyền qua CDP.

## Tests

```powershell
& "C:/Program Files/Python311/python.exe" -m unittest discover -s tests -v
```
