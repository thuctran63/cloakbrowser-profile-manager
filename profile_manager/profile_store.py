"""Durable local storage for profile metadata and application settings."""

from __future__ import annotations

import json
import secrets
import shutil
import sqlite3
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import AppSettings, ProfileConfig, ProfileSettings
from .proxy import normalize_proxy


class ProfileStore:
    _PROFILE_COLUMNS = (
        "id, name, proxy, fingerprint_seed, data_dir, created_at, updated_at, "
        "geoip, timezone, locale, release_channel, browser_version, humanize, human_preset"
    )
    def __init__(self, app_data_dir: Path, default_profiles_dir: Path) -> None:
        self.app_data_dir = app_data_dir.resolve()
        self.default_profiles_dir = default_profiles_dir.resolve()
        self.index_path = self.app_data_dir / "profiles.json"
        self.database_path = self.app_data_dir / "profiles.db"
        self.settings_path = self.app_data_dir / "settings.json"
        self._migration_lock = threading.RLock()
        self._settings_lock = threading.RLock()
        self.app_data_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Không thể đọc dữ liệu: {path.name}") from exc

    def _atomic_write(self, path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
            ) as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                temp_name = handle.name
            Path(temp_name).replace(path)
        finally:
            if temp_name:
                Path(temp_name).unlink(missing_ok=True)

    def load_settings(self) -> AppSettings:
        with self._settings_lock:
            data = self._read_json(self.settings_path, {})
            settings = AppSettings.from_dict(data, self.default_profiles_dir)
            if not settings.api_key:
                settings.api_key = secrets.token_urlsafe(32)
                self.save_settings(settings)
            return settings

    def save_settings(self, settings: AppSettings) -> None:
        with self._settings_lock:
            target = Path(settings.default_profiles_dir).expanduser().resolve()
            target.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target, prefix=".write-test-", delete=True):
                pass
            settings.default_profiles_dir = str(target)
            if settings.api_host != "127.0.0.1":
                raise ValueError("API hiện chỉ cho phép bind tại 127.0.0.1")
            if not 1 <= settings.api_port <= 65535:
                raise ValueError("API port phải nằm trong khoảng 1–65535")
            if not 1 <= settings.max_concurrent_launches <= 20:
                raise ValueError("Concurrent launches phải nằm trong khoảng 1–20")
            self._atomic_write(self.settings_path, settings.to_dict())

    def list_profiles(self) -> list[ProfileConfig]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {self._PROFILE_COLUMNS} "
                "FROM profiles ORDER BY name COLLATE NOCASE, id"
            ).fetchall()
        return [self._profile_from_row(row) for row in rows]

    def _save_profiles(self, profiles: list[ProfileConfig]) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM profiles")
            connection.executemany(
                f"INSERT INTO profiles ({self._PROFILE_COLUMNS}) VALUES ({','.join('?' for _ in range(14))})",
                [self._profile_values(profile) for profile in profiles],
            )

    def create_profile(
        self, name: str, proxy: str = "", settings: ProfileSettings | None = None
    ) -> ProfileConfig:
        clean_name = self._validate_name(name)
        normalized_proxy = normalize_proxy(proxy)
        app_settings = self.load_settings()
        profile_id = str(uuid.uuid4())
        profile_dir = (Path(app_settings.default_profiles_dir) / profile_id).resolve()
        profile_dir.mkdir(parents=True, exist_ok=False)
        (profile_dir / "user-data").mkdir()
        now = datetime.now(timezone.utc).isoformat()
        identity = settings or ProfileSettings()
        profile = ProfileConfig(
            id=profile_id,
            name=clean_name,
            proxy=normalized_proxy,
            fingerprint_seed=secrets.randbelow(90_000) + 10_000,
            data_dir=str(profile_dir),
            created_at=now,
            updated_at=now,
            geoip=identity.geoip,
            timezone=identity.timezone,
            locale=identity.locale,
            release_channel=identity.release_channel,
            browser_version=identity.browser_version,
            humanize=identity.humanize,
            human_preset=identity.human_preset,
        )
        try:
            self._atomic_write(profile_dir / "profile.json", profile.to_dict())
            with self._connect() as connection:
                connection.execute(
                    f"INSERT INTO profiles ({self._PROFILE_COLUMNS}) VALUES ({','.join('?' for _ in range(14))})",
                    self._profile_values(profile),
                )
                connection.execute(
                    "INSERT INTO profile_extensions (profile_id, extension_id, assigned_at) "
                    "SELECT ?, id, ? FROM extensions WHERE assign_to_new_profiles = 1",
                    (profile.id, now),
                )
        except Exception:
            shutil.rmtree(profile_dir, ignore_errors=True)
            raise
        return profile

    def update_profile(
        self, profile_id: str, name: str, proxy: str = "",
        settings: ProfileSettings | None = None,
    ) -> ProfileConfig:
        clean_name = self._validate_name(name)
        normalized_proxy = normalize_proxy(proxy)
        profile = self.get_profile(profile_id)
        profile.name = clean_name
        profile.proxy = normalized_proxy
        if settings is not None:
            for field in ("geoip", "timezone", "locale", "release_channel", "browser_version", "humanize", "human_preset"):
                setattr(profile, field, getattr(settings, field))
        profile.updated_at = datetime.now(timezone.utc).isoformat()
        self._atomic_write(Path(profile.data_dir) / "profile.json", profile.to_dict())
        with self._connect() as connection:
            connection.execute(
                "UPDATE profiles SET name=?, proxy=?, updated_at=?, geoip=?, timezone=?, locale=?, "
                "release_channel=?, browser_version=?, humanize=?, human_preset=? WHERE id=?",
                (profile.name, profile.proxy, profile.updated_at, int(profile.geoip), profile.timezone,
                 profile.locale, profile.release_channel, profile.browser_version, int(profile.humanize),
                 profile.human_preset, profile.id),
            )
        return profile

    def delete_profile(self, profile_id: str) -> None:
        profile = self.get_profile(profile_id)
        profile_dir = Path(profile.data_dir).resolve()
        if profile_dir == profile_dir.anchor or len(profile_dir.parts) < 3:
            raise RuntimeError("Từ chối xóa đường dẫn profile không an toàn")
        tombstone = profile_dir.with_name(f".{profile_dir.name}.deleting")
        profile_dir.replace(tombstone)
        try:
            with self._connect() as connection:
                connection.execute("DELETE FROM profiles WHERE id = ?", (profile.id,))
            shutil.rmtree(tombstone)
        except Exception:
            if tombstone.exists() and not profile_dir.exists():
                tombstone.replace(profile_dir)
            raise

    def get_profile(self, profile_id: str) -> ProfileConfig:
        try:
            expected = str(uuid.UUID(profile_id))
        except ValueError as exc:
            raise KeyError("Profile ID không hợp lệ") from exc
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {self._PROFILE_COLUMNS} "
                "FROM profiles WHERE id = ?", (expected,)
            ).fetchone()
        if row is None:
            raise KeyError("Không tìm thấy profile")
        return self._profile_from_row(row)

    def ping(self) -> bool:
        with self._connect() as connection:
            return connection.execute("SELECT 1").fetchone()[0] == 1

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with self._migration_lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL").fetchone()
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS profiles ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, proxy TEXT, "
                "fingerprint_seed INTEGER NOT NULL CHECK(fingerprint_seed BETWEEN 10000 AND 99999), "
                "data_dir TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 3:
                raise RuntimeError(f"Database version {version} chưa được hỗ trợ")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(profiles)")}
            migrations = {
                "geoip": "INTEGER NOT NULL DEFAULT 1 CHECK(geoip IN (0,1))",
                "timezone": "TEXT",
                "locale": "TEXT",
                "release_channel": "TEXT NOT NULL DEFAULT 'stable'",
                "browser_version": "TEXT",
                "humanize": "INTEGER NOT NULL DEFAULT 0 CHECK(humanize IN (0,1))",
                "human_preset": "TEXT NOT NULL DEFAULT 'default'",
            }
            for name, definition in migrations.items():
                if name not in columns:
                    connection.execute(f"ALTER TABLE profiles ADD COLUMN {name} {definition}")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS extensions ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL, "
                "description TEXT NOT NULL DEFAULT '', manifest_version INTEGER NOT NULL, "
                "directory TEXT NOT NULL UNIQUE, imported_at TEXT NOT NULL, "
                "source_name TEXT NOT NULL DEFAULT '', size_bytes INTEGER NOT NULL DEFAULT 0, "
                "assign_to_new_profiles INTEGER NOT NULL DEFAULT 0)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS profile_extensions ("
                "profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, "
                "extension_id TEXT NOT NULL REFERENCES extensions(id) ON DELETE RESTRICT, "
                "assigned_at TEXT NOT NULL, PRIMARY KEY(profile_id, extension_id))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS profile_extensions_extension_idx "
                "ON profile_extensions(extension_id)"
            )
            count = connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
            if count == 0 and self.index_path.exists():
                items = self._read_json(self.index_path, [])
                if not isinstance(items, list):
                    raise RuntimeError("Danh sách profile không hợp lệ")
                profiles = [ProfileConfig.from_dict(item) for item in items]
                connection.executemany(
                    f"INSERT INTO profiles ({self._PROFILE_COLUMNS}) VALUES ({','.join('?' for _ in range(14))})",
                    [self._profile_values(profile) for profile in profiles],
                )
                backup = self.index_path.with_suffix(".json.migrated")
                if not backup.exists():
                    shutil.copy2(self.index_path, backup)
            connection.execute("PRAGMA user_version=3")

    @staticmethod
    def _profile_from_row(row: sqlite3.Row) -> ProfileConfig:
        data = dict(row)
        data["geoip"] = bool(data["geoip"])
        data["humanize"] = bool(data["humanize"])
        return ProfileConfig(**data)

    @staticmethod
    def _profile_values(profile: ProfileConfig) -> tuple[Any, ...]:
        return (
            profile.id, profile.name, profile.proxy, profile.fingerprint_seed,
            profile.data_dir, profile.created_at, profile.updated_at, int(profile.geoip),
            profile.timezone, profile.locale, profile.release_channel,
            profile.browser_version, int(profile.humanize), profile.human_preset,
        )

    @staticmethod
    def _find(profiles: list[ProfileConfig], profile_id: str) -> ProfileConfig:
        try:
            expected = str(uuid.UUID(profile_id))
        except ValueError as exc:
            raise KeyError("Profile ID không hợp lệ") from exc
        for profile in profiles:
            if profile.id == expected:
                return profile
        raise KeyError("Không tìm thấy profile")

    @staticmethod
    def _validate_name(name: str) -> str:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Tên profile không được để trống")
        if len(clean_name) > 80:
            raise ValueError("Tên profile tối đa 80 ký tự")
        return clean_name
