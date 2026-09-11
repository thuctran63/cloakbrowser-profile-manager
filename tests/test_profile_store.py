from __future__ import annotations

import tempfile
import threading
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path

from profile_manager.models import AppSettings
from profile_manager.profile_store import ProfileStore


class ProfileStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = ProfileStore(root / "app", root / "profiles")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_create_update_and_delete_profile(self) -> None:
        profile = self.store.create_profile("Primary", "http://user:pass@localhost:8080")
        self.assertTrue(profile.user_data_dir.is_dir())
        self.assertGreaterEqual(profile.fingerprint_seed, 10_000)
        self.assertLessEqual(profile.fingerprint_seed, 99_999)
        self.assertTrue(profile.geoip)
        self.assertEqual(profile.release_channel, "stable")

        updated = self.store.update_profile(profile.id, "Updated", "")
        self.assertEqual(updated.name, "Updated")
        self.assertIsNone(updated.proxy)
        self.assertEqual(updated.fingerprint_seed, profile.fingerprint_seed)

        self.store.delete_profile(profile.id)
        self.assertEqual(self.store.list_profiles(), [])
        self.assertFalse(Path(profile.data_dir).exists())

    def test_storage_setting_only_affects_new_profiles(self) -> None:
        first = self.store.create_profile("First")
        new_root = Path(self.temp.name) / "other"
        self.store.save_settings(
            AppSettings(str(new_root), api_port=9123, api_key="secret-key")
        )
        settings = self.store.load_settings()
        self.assertEqual(settings.api_host, "127.0.0.1")
        self.assertEqual(settings.api_port, 9123)
        self.assertEqual(settings.api_key, "secret-key")
        second = self.store.create_profile("Second")
        self.assertEqual(Path(first.data_dir).parent, Path(self.temp.name) / "profiles")
        self.assertEqual(Path(second.data_dir).parent, new_root)

    def test_rejects_invalid_proxy(self) -> None:
        with self.assertRaises(ValueError):
            self.store.create_profile("Invalid", "localhost:8080")

    def test_rejects_unsafe_api_settings(self) -> None:
        with self.assertRaises(ValueError):
            self.store.save_settings(
                AppSettings(str(Path(self.temp.name) / "profiles"), api_host="0.0.0.0")
            )
        with self.assertRaises(ValueError):
            self.store.save_settings(
                AppSettings(str(Path(self.temp.name) / "profiles"), api_port=70_000)
            )

    def test_concurrent_creates_are_not_lost(self) -> None:
        threads = [
            threading.Thread(target=self.store.create_profile, args=(f"Profile {index}",))
            for index in range(12)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(self.store.list_profiles()), 12)
        self.assertTrue(self.store.ping())

    def test_migrates_legacy_json_once(self) -> None:
        profile = self.store.create_profile("Legacy")
        data = [profile.to_dict()]
        app_dir = Path(self.temp.name) / "legacy-app"
        app_dir.mkdir()
        (app_dir / "profiles.json").write_text(__import__("json").dumps(data), encoding="utf-8")
        migrated = ProfileStore(app_dir, Path(self.temp.name) / "legacy-profiles")
        self.assertEqual(migrated.list_profiles()[0].id, profile.id)
        self.assertTrue((app_dir / "profiles.json.migrated").exists())
        self.assertEqual(len(ProfileStore(app_dir, Path(self.temp.name) / "legacy-profiles").list_profiles()), 1)

    def test_migrates_v2_profiles_with_automatic_geoip(self) -> None:
        app_dir = Path(self.temp.name) / "v2-app"
        app_dir.mkdir()
        database = app_dir / "profiles.db"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL, proxy TEXT, fingerprint_seed INTEGER NOT NULL, data_dir TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            connection.execute("PRAGMA user_version=2")
            connection.commit()
        migrated = ProfileStore(app_dir, Path(self.temp.name) / "v2-profiles")
        with closing(sqlite3.connect(database)) as connection:
            cursor = connection.cursor()
            try:
                version = cursor.execute("PRAGMA user_version").fetchone()[0]
                rows = cursor.execute("PRAGMA table_info(profiles)").fetchall()
            finally:
                cursor.close()
            self.assertEqual(version, 3)
            columns = {row[1] for row in rows}
        self.assertIn("geoip", columns)


if __name__ == "__main__":
    unittest.main()
