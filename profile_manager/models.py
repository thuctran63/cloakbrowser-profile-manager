"""Application data models for persistent browser profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


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


@dataclass(slots=True)
class AppSettings:
    default_profiles_dir: str
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    api_key: str = ""
    max_concurrent_launches: int = 2
    max_running_profiles: int = 10
    requests_per_minute: int = 120

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
            max_running_profiles=int(data.get("max_running_profiles") or 10),
            requests_per_minute=int(data.get("requests_per_minute") or 120),
        )
