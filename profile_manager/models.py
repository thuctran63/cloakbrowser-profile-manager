"""Application data models for persistent browser profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class RuntimeState(str, Enum):
    STOPPED = "Stopped"
    STARTING = "Starting"
    RUNNING = "Running"
    STOPPING = "Stopping"
    ERROR = "Error"


@dataclass(slots=True)
class ProfileConfig:
    id: str
    name: str
    proxy: str | None
    fingerprint_seed: int
    data_dir: str
    created_at: str
    updated_at: str

    @property
    def user_data_dir(self) -> Path:
        return Path(self.data_dir) / "user-data"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProfileConfig":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            proxy=str(data["proxy"]) if data.get("proxy") else None,
            fingerprint_seed=int(data["fingerprint_seed"]),
            data_dir=str(data["data_dir"]),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
        )


@dataclass(frozen=True, slots=True)
class OpenOptions:
    pos_x: int | None = None
    pos_y: int | None = None
    width: int | None = None
    height: int | None = None
    page_zoom: float | None = None
    start_url: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OpenOptions":
        allowed = {"pos_x", "pos_y", "width", "height", "page_zoom", "start_url"}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Open options không hợp lệ: {', '.join(sorted(unknown))}")

        def integer(name: str) -> int | None:
            value = data.get(name)
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} phải là số nguyên")
            return value

        pos_x, pos_y = integer("pos_x"), integer("pos_y")
        width, height = integer("width"), integer("height")
        if (pos_x is None) != (pos_y is None):
            raise ValueError("pos_x và pos_y phải được truyền cùng nhau")
        if (width is None) != (height is None):
            raise ValueError("width và height phải được truyền cùng nhau")
        if pos_x is not None and not -100_000 <= pos_x <= 100_000:
            raise ValueError("pos_x phải nằm trong khoảng -100000–100000")
        if pos_y is not None and not -100_000 <= pos_y <= 100_000:
            raise ValueError("pos_y phải nằm trong khoảng -100000–100000")
        if width is not None and not 100 <= width <= 10_000:
            raise ValueError("width phải nằm trong khoảng 100–10000")
        if height is not None and not 100 <= height <= 10_000:
            raise ValueError("height phải nằm trong khoảng 100–10000")
        raw_zoom = data.get("page_zoom")
        if raw_zoom is not None and (
            isinstance(raw_zoom, bool) or not isinstance(raw_zoom, (int, float))
        ):
            raise ValueError("page_zoom phải là một số")
        page_zoom = float(raw_zoom) if raw_zoom is not None else None
        if page_zoom is not None and not 25 <= page_zoom <= 100:
            raise ValueError("page_zoom phải nằm trong khoảng 25–100 phần trăm")

        raw_start_url = data.get("start_url")
        if raw_start_url is not None and not isinstance(raw_start_url, str):
            raise ValueError("start_url phải là chuỗi")
        start_url = raw_start_url.strip() if raw_start_url is not None else None
        if start_url == "":
            start_url = None
        if start_url is not None:
            if len(start_url) > 2048:
                raise ValueError("start_url không được dài quá 2048 ký tự")
            parsed_url = urlsplit(start_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
                raise ValueError("start_url phải là URL http hoặc https hợp lệ")
        return cls(pos_x, pos_y, width, height, page_zoom, start_url)


@dataclass(slots=True)
class AppSettings:
    default_profiles_dir: str
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    api_key: str = ""
    max_concurrent_launches: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any], fallback: Path) -> "AppSettings":
        value = data.get("default_profiles_dir")
        return cls(
            default_profiles_dir=str(value or fallback),
            api_host=str(data.get("api_host") or "127.0.0.1"),
            api_port=int(data.get("api_port") or 8765),
            api_key=str(data.get("api_key") or ""),
            max_concurrent_launches=int(data.get("max_concurrent_launches") or 2),
        )
