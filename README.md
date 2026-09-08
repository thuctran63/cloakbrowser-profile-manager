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

Dependency CloakBrowser được pin vào commit bất biến của custom fork trong
`requirements.txt`:

```powershell
& "C:/Program Files/Python311/python.exe" -m pip install -r requirements.txt
```

## Chức năng

- Tạo profile với UUID và fingerprint seed ngẫu nhiên, cố định theo profile.
- Sửa tên và proxy HTTP/HTTPS/SOCKS5.
- Xóa toàn bộ metadata, cookie, cache và history sau khi xác nhận.
- Open/Close nhiều profile độc lập với lock theo profile, launch queue và giới hạn tài nguyên.
- Chọn thư mục mặc định cho profile tạo mới trong Settings.
- Tự cập nhật trạng thái khi cửa sổ Chromium được đóng thủ công.
- SQLite/WAL cho metadata, tự migration một lần từ `profiles.json` cũ.
- Local REST API bất đồng bộ để CRUD/Open/Close và cấp CDP endpoint cho automation.

## API v1

API mặc định chạy tại `http://127.0.0.1:8765`. URL, port và API key được hiển thị và cấu hình trong cửa sổ **Settings**. API chỉ bind tại localhost để không công khai quyền điều khiển browser ra mạng.

### Xác thực

Nếu API key trong Settings không rỗng, gửi một trong hai header:

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

### CRUD tương thích

Các endpoint CRUD hiện tại được giữ để client cũ tiếp tục hoạt động:

- `GET/POST /api/profiles`
- `GET/PATCH/DELETE /api/profiles/{id}`
- `POST /api/profiles/{id}/open`
- `POST /api/profiles/{id}/close`

Hai endpoint Open/Close legacy vẫn chờ kết quả đồng bộ. Client mới nên dùng operation API v1.

Profile response không trả `fingerprint_seed`. Không thể sửa hoặc xóa profile khi browser không ở trạng thái `Stopped`.

### Health và capacity

- `GET /health` — tương thích cũ.
- `GET /health/live` — HTTP server đang sống.
- `GET /health/ready` — database, worker sẵn sàng và service chưa draining.
- `GET /api/v1/status` — số profile `starting`, `running`, limit, active operations và trạng thái worker/draining.

### Status code và lỗi

- `200` thành công; `201` đã tạo profile; `202` đã nhận lifecycle operation.
- `400` body/tham số không hợp lệ; `401` API key sai/thiếu; `404` resource không tồn tại.
- `413` body vượt 64 KiB; `429` vượt requests/phút; `500` lỗi nội bộ đã ẩn chi tiết; `503` readiness thất bại.

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

Settings cho phép cấu hình launch đồng thời (`1–20`), tổng browser (`launch–100`) và rate limit (`10–10000` request/phút). Giới hạn session thực tế vẫn phụ thuộc license/tier CloakBrowser.

## Dữ liệu

Mặc định metadata nằm trong `.profile-manager/profiles.db` (SQLite/WAL); browser data nằm trong `profiles/<uuid>/user-data/`. Mỗi profile lưu đường dẫn tuyệt đối, vì vậy đổi Settings không di chuyển profile cũ. Lần đầu nâng cấp, `profiles.json` được import transactionally và sao lưu thành `profiles.json.migrated`.

Proxy có thể nhập dưới dạng `http://user:pass@host:port` hoặc `socks5://host:port`. Proxy vẫn được lưu local dạng plain text trong SQLite; không commit `.profile-manager`, không dùng API/CDP trên máy dùng chung và không log credential.

Chromium nhận `--remote-debugging-port=0`; ứng dụng đọc file `DevToolsActivePort` mới và xác thực `/json/version` trước khi công bố CDP URL. Cách này tránh race do chọn trước một free port.

## Tests

```powershell
& "C:/Program Files/Python311/python.exe" -m unittest discover -s tests -v
```
