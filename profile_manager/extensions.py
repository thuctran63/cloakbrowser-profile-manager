"""Central extension library and profile assignment persistence."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Iterable


@dataclass(frozen=True, slots=True)
class ExtensionInfo:
    id: str
    name: str
    version: str
    description: str
    manifest_version: int
    directory: str
    imported_at: str
    source_name: str
    size_bytes: int
    assign_to_new_profiles: bool = False
    assigned_profile_count: int = 0


@dataclass(frozen=True, slots=True)
class ImportResult:
    imported: tuple[ExtensionInfo, ...]
    skipped: tuple[ExtensionInfo, ...]
    errors: tuple[str, ...]


class ExtensionLibrary:
    """Stores each payload once and assigns it to any number of profiles."""

    def __init__(self, database_path: str | Path, library_root: str | Path) -> None:
        self.database_path = Path(database_path).resolve()
        self.library_root = Path(library_root).resolve()
        self.payload_root = self.library_root / "payloads"
        self._operation_lock = threading.RLock()
        if "," in str(self.payload_root):
            raise ValueError("Đường dẫn thư viện extension không được chứa dấu phẩy")
        self.payload_root.mkdir(parents=True, exist_ok=True)

    def list_extensions(self) -> list[ExtensionInfo]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT e.*, COUNT(pe.profile_id) AS assigned_profile_count "
                "FROM extensions e LEFT JOIN profile_extensions pe ON pe.extension_id = e.id "
                "GROUP BY e.id ORDER BY e.name COLLATE NOCASE, e.id"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def assignment_map(self, extension_ids: Iterable[str] | None = None) -> dict[str, set[str]]:
        ids = tuple(dict.fromkeys(extension_ids or ()))
        with self._connect() as connection:
            if ids:
                placeholders = ",".join("?" for _ in ids)
                rows = connection.execute(
                    f"SELECT extension_id, profile_id FROM profile_extensions WHERE extension_id IN ({placeholders})",
                    ids,
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT extension_id, profile_id FROM profile_extensions"
                ).fetchall()
        result: dict[str, set[str]] = {extension_id: set() for extension_id in ids}
        for row in rows:
            result.setdefault(str(row["extension_id"]), set()).add(str(row["profile_id"]))
        return result

    def launch_paths(self, profile_id: str) -> list[Path]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT e.directory, e.name FROM extensions e "
                "JOIN profile_extensions pe ON pe.extension_id = e.id "
                "WHERE pe.profile_id = ? ORDER BY e.name COLLATE NOCASE, e.id",
                (profile_id,),
            ).fetchall()
        paths: list[Path] = []
        for row in rows:
            path = self._managed_path(str(row["directory"]))
            if not (path / "manifest.json").is_file():
                raise RuntimeError(f"Extension “{row['name']}” bị thiếu dữ liệu: {path}")
            paths.append(path)
        return paths

    def import_from_folder(self, selected_folder: str | Path) -> ImportResult:
        source_root = Path(selected_folder).expanduser().resolve()
        if not source_root.is_dir():
            raise ValueError("Thư mục extension không tồn tại")
        candidates = self.discover(source_root)
        if not candidates:
            raise ValueError("Không tìm thấy manifest.json trong thư mục đã chọn")
        imported: list[ExtensionInfo] = []
        skipped: list[ExtensionInfo] = []
        errors: list[str] = []
        with self._operation_lock:
            for source in candidates:
                try:
                    imported_item, duplicate = self._import_one(source)
                    (skipped if duplicate else imported).append(imported_item)
                except Exception as exc:
                    errors.append(f"{source.name}: {exc}")
        return ImportResult(tuple(imported), tuple(skipped), tuple(errors))

    def assign(self, profile_ids: Iterable[str], extension_ids: Iterable[str]) -> None:
        profiles = tuple(dict.fromkeys(profile_ids))
        extensions = tuple(dict.fromkeys(extension_ids))
        if not profiles or not extensions:
            return
        now = datetime.now(timezone.utc).isoformat()
        with self._operation_lock, self._connect() as connection:
            self._validate_ids(connection, "profiles", profiles)
            self._validate_ids(connection, "extensions", extensions)
            connection.executemany(
                "INSERT OR IGNORE INTO profile_extensions(profile_id, extension_id, assigned_at) VALUES (?, ?, ?)",
                [(profile_id, extension_id, now) for profile_id in profiles for extension_id in extensions],
            )

    def unassign(self, profile_ids: Iterable[str], extension_ids: Iterable[str]) -> None:
        profiles = tuple(dict.fromkeys(profile_ids))
        extensions = tuple(dict.fromkeys(extension_ids))
        if not profiles or not extensions:
            return
        profile_placeholders = ",".join("?" for _ in profiles)
        extension_placeholders = ",".join("?" for _ in extensions)
        with self._operation_lock, self._connect() as connection:
            connection.execute(
                f"DELETE FROM profile_extensions WHERE profile_id IN ({profile_placeholders}) "
                f"AND extension_id IN ({extension_placeholders})",
                profiles + extensions,
            )

    def set_default_assignment(self, extension_ids: Iterable[str], enabled: bool) -> None:
        extensions = tuple(dict.fromkeys(extension_ids))
        if not extensions:
            return
        placeholders = ",".join("?" for _ in extensions)
        with self._operation_lock, self._connect() as connection:
            self._validate_ids(connection, "extensions", extensions)
            connection.execute(
                f"UPDATE extensions SET assign_to_new_profiles = ? WHERE id IN ({placeholders})",
                (int(enabled), *extensions),
            )

    def delete_extensions(self, extension_ids: Iterable[str]) -> list[ExtensionInfo]:
        ids = tuple(dict.fromkeys(extension_ids))
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        trash = self.library_root / ".trash"
        trash.mkdir(parents=True, exist_ok=True)
        moved: list[tuple[Path, Path]] = []
        with self._operation_lock:
            try:
                with self._connect() as connection:
                    self._validate_ids(connection, "extensions", ids)
                    rows = connection.execute(
                        f"SELECT e.*, COUNT(pe.profile_id) AS assigned_profile_count FROM extensions e "
                        "LEFT JOIN profile_extensions pe ON pe.extension_id = e.id "
                        f"WHERE e.id IN ({placeholders}) GROUP BY e.id",
                        ids,
                    ).fetchall()
                    items = [self._from_row(row) for row in rows]
                    used = [item.name for item in items if item.assigned_profile_count]
                    if used:
                        raise RuntimeError("Hãy bỏ gán khỏi tất cả profile trước: " + ", ".join(used))
                    for item in items:
                        source = self._managed_path(item.directory)
                        target = trash / item.directory
                        if source.exists():
                            source.replace(target)
                            moved.append((source, target))
                    connection.execute(f"DELETE FROM extensions WHERE id IN ({placeholders})", ids)
            except Exception:
                for source, target in reversed(moved):
                    if target.exists() and not source.exists():
                        target.replace(source)
                raise
        shutil.rmtree(trash, ignore_errors=True)
        return items

    def _import_one(self, source: Path) -> tuple[ExtensionInfo, bool]:
        manifest = self._read_manifest(source)
        digest = self._directory_digest(source)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT e.*, COUNT(pe.profile_id) AS assigned_profile_count FROM extensions e "
                "LEFT JOIN profile_extensions pe ON pe.extension_id = e.id WHERE e.id = ? GROUP BY e.id",
                (digest,),
            ).fetchone()
        if row:
            return self._from_row(row), True
        destination = self._managed_path(digest)
        staging_root = self.library_root / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = staging_root / f"{digest}-{uuid.uuid4().hex}"
        try:
            shutil.copytree(source, staging, symlinks=False)
            self._read_manifest(staging)
            if destination.exists():
                shutil.rmtree(destination)
            staging.replace(destination)
            now = datetime.now(timezone.utc).isoformat()
            item = ExtensionInfo(
                id=digest,
                name=str(manifest["name"]).strip(),
                version=str(manifest["version"]).strip(),
                description=str(manifest.get("description") or ""),
                manifest_version=int(manifest["manifest_version"]),
                directory=digest,
                imported_at=now,
                source_name=source.name,
                size_bytes=self._directory_size(destination),
            )
            try:
                with self._connect() as connection:
                    connection.execute(
                        "INSERT INTO extensions(id, name, version, description, manifest_version, directory, "
                        "imported_at, source_name, size_bytes, assign_to_new_profiles) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (item.id, item.name, item.version, item.description, item.manifest_version,
                         item.directory, item.imported_at, item.source_name, item.size_bytes, 0),
                    )
            except Exception:
                shutil.rmtree(destination, ignore_errors=True)
                raise
            return item, False
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            if staging_root.exists() and not any(staging_root.iterdir()):
                staging_root.rmdir()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.database_path, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate_ids(connection: sqlite3.Connection, table: str, ids: tuple[str, ...]) -> None:
        placeholders = ",".join("?" for _ in ids)
        count = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE id IN ({placeholders})", ids
        ).fetchone()[0]
        if count != len(ids):
            raise KeyError("Profile hoặc extension không còn tồn tại")

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ExtensionInfo:
        return ExtensionInfo(
            id=str(row["id"]), name=str(row["name"]), version=str(row["version"]),
            description=str(row["description"]), manifest_version=int(row["manifest_version"]),
            directory=str(row["directory"]), imported_at=str(row["imported_at"]),
            source_name=str(row["source_name"]), size_bytes=int(row["size_bytes"]),
            assign_to_new_profiles=bool(row["assign_to_new_profiles"]),
            assigned_profile_count=int(row["assigned_profile_count"]) if "assigned_profile_count" in row.keys() else 0,
        )

    def _managed_path(self, directory: str) -> Path:
        if not directory or directory != Path(directory).name:
            raise RuntimeError("Đường dẫn extension đã lưu không an toàn")
        path = (self.payload_root / directory).resolve()
        if path.parent != self.payload_root:
            raise RuntimeError("Đường dẫn extension đã lưu không an toàn")
        return path

    @staticmethod
    def discover(selected_folder: Path) -> list[Path]:
        if (selected_folder / "manifest.json").is_file():
            return [selected_folder]
        direct = sorted(
            (path for path in selected_folder.iterdir() if path.is_dir() and (path / "manifest.json").is_file()),
            key=lambda path: path.name.casefold(),
        )
        if direct:
            return direct
        nested: list[Path] = []
        for parent in sorted((path for path in selected_folder.iterdir() if path.is_dir()), key=lambda path: path.name.casefold()):
            versions = [path for path in parent.iterdir() if path.is_dir() and (path / "manifest.json").is_file()]
            if versions:
                nested.append(max(versions, key=lambda path: path.name.casefold()))
        return nested

    @staticmethod
    def _read_manifest(directory: Path) -> dict[str, Any]:
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("manifest.json không đọc được hoặc sai định dạng") from exc
        if not isinstance(manifest, dict):
            raise ValueError("manifest.json phải là JSON object")
        for field in ("name", "version"):
            if not isinstance(manifest.get(field), str) or not manifest[field].strip():
                raise ValueError(f"manifest.json thiếu {field}")
        if manifest.get("manifest_version") not in {2, 3}:
            raise ValueError("chỉ hỗ trợ manifest_version 2 hoặc 3")
        return manifest

    @staticmethod
    def _directory_digest(directory: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted((item for item in directory.rglob("*") if item.is_file()), key=lambda item: item.relative_to(directory).as_posix()):
            digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        return digest.hexdigest()[:32]

    @staticmethod
    def _directory_size(directory: Path) -> int:
        return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())
