from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from profile_manager.extensions import ExtensionLibrary
from profile_manager.profile_store import ProfileStore


class ExtensionLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ProfileStore(self.root / "app", self.root / "profiles")
        self.library = ExtensionLibrary(self.store.database_path, self.store.app_data_dir / "extensions")
        self.first_profile = self.store.create_profile("First")
        self.second_profile = self.store.create_profile("Second")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_extension(self, parent: Path, folder: str, name: str, version: str = "1.0") -> Path:
        extension = parent / folder
        extension.mkdir(parents=True)
        (extension / "manifest.json").write_text(json.dumps({"manifest_version": 3, "name": name, "version": version}), encoding="utf-8")
        (extension / "background.js").write_text("console.log('loaded')", encoding="utf-8")
        return extension

    def test_imports_once_and_assigns_to_many_profiles(self) -> None:
        source = self.root / "source"
        self.create_extension(source, "one", "First Extension")
        self.create_extension(source, "two", "Second Extension")
        result = self.library.import_from_folder(source)
        self.assertEqual(len(result.imported), 2)
        duplicate = self.library.import_from_folder(source)
        self.assertEqual(len(duplicate.skipped), 2)
        ids = [item.id for item in result.imported]

        self.library.assign([self.first_profile.id, self.second_profile.id], ids)
        assignments = self.library.assignment_map(ids)
        self.assertEqual(assignments[ids[0]], {self.first_profile.id, self.second_profile.id})
        self.assertEqual(len(self.library.launch_paths(self.first_profile.id)), 2)
        self.assertEqual(len(list((self.store.app_data_dir / "extensions" / "payloads").iterdir())), 2)

    def test_default_extensions_are_assigned_to_new_profiles(self) -> None:
        source = self.create_extension(self.root, "default", "Default Extension")
        extension = self.library.import_from_folder(source).imported[0]
        self.library.set_default_assignment([extension.id], True)
        new_profile = self.store.create_profile("New")
        self.assertEqual(self.library.assignment_map([extension.id])[extension.id], {new_profile.id})
        self.assertEqual(self.library.launch_paths(new_profile.id)[0].name, extension.id)

    def test_unassigns_in_bulk_and_rejects_deleting_used_extension(self) -> None:
        source = self.create_extension(self.root, "used", "Used Extension")
        extension = self.library.import_from_folder(source).imported[0]
        profiles = [self.first_profile.id, self.second_profile.id]
        self.library.assign(profiles, [extension.id])
        with self.assertRaisesRegex(RuntimeError, "bỏ gán"):
            self.library.delete_extensions([extension.id])
        self.library.unassign(profiles, [extension.id])
        removed = self.library.delete_extensions([extension.id])
        self.assertEqual(removed[0].id, extension.id)
        self.assertEqual(self.library.list_extensions(), [])

    def test_invalid_manifest_is_reported_without_catalog_entry(self) -> None:
        invalid = self.root / "invalid"
        invalid.mkdir()
        (invalid / "manifest.json").write_text(json.dumps({"name": "Bad", "version": "1", "manifest_version": 9}), encoding="utf-8")
        result = self.library.import_from_folder(invalid)
        self.assertEqual(result.imported, ())
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(self.library.list_extensions(), [])


if __name__ == "__main__":
    unittest.main()
