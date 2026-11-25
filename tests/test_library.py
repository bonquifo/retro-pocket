import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile


def variant(data, algorithm="sha256"):
    return {"label": "Original", "size": len(data),
            algorithm: hashlib.new(algorithm, data).hexdigest()}


class LibraryTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.base = Path(scratch.name)
        self.catalog = self.base / "catalog.json"
        self.data = b"homebrew test ROM"
        self.entry = {"id": "demo", "title": "Demo", "platform": "GB",
                      "year": 2025, "variants": [variant(self.data)]}

    def library(self):
        from library import Library

        self.catalog.write_text(json.dumps([self.entry]), encoding="utf-8")
        return Library(self.base / "cache", self.catalog)

    def test_imports_catalogued_raw_rom_and_loads_verified_bytes(self):
        library = self.library()
        self.assertEqual(library.games, [self.entry])
        source = self.base / "arbitrary-name.bin"
        source.write_bytes(self.data)
        library.import_rom(self.entry, source)
        self.assertEqual(library.path(self.entry).read_bytes(), self.data)
        self.assertEqual(library.load(self.entry), self.data)

    def test_invalid_import_does_not_replace_cache(self):
        library = self.library()
        source = self.base / "rom.gb"
        source.write_bytes(self.data)
        library.import_rom(self.entry, source)
        source.write_bytes(b"x" * len(self.data))
        with self.assertRaises(ValueError):
            library.import_rom(self.entry, source)
        self.assertEqual(library.load(self.entry), self.data)
        self.assertEqual(list(library.path(self.entry).parent.iterdir()),
                         [library.path(self.entry)])

    def test_load_rejects_same_size_cache_tampering(self):
        library = self.library()
        cached = library.path(self.entry)
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"x" * len(self.data))
        with self.assertRaises(ValueError):
            library.load(self.entry)

    def test_import_accepts_sha1_alternate_variant(self):
        alternate = b"ROM revision"
        self.entry["variants"].append(variant(alternate, "sha1"))
        library = self.library()
        source = self.base / "rom.gb"
        source.write_bytes(alternate)
        library.import_rom(self.entry, source)
        self.assertEqual(library.load(self.entry), alternate)

    def test_default_root_uses_xdg_data_home(self):
        from library import Library

        self.library()
        with patch.dict("os.environ", {"XDG_DATA_HOME": str(self.base / "xdg")}):
            library = Library(catalog=self.catalog)
            self.assertEqual(library.path(self.entry).parent,
                             self.base / "xdg" / "retro-pocket")
            explicit = Library(root=self.base / "cache", catalog=self.catalog)
            self.assertEqual(explicit.path(self.entry).parent, self.base / "cache")

    def test_relative_xdg_data_home_falls_back_to_user_data_dir(self):
        from library import Library
        import compat

        self.library()
        if compat.WINDOWS:
            environment = {"XDG_DATA_HOME": "relative", "LOCALAPPDATA": str(self.base)}
            expected = self.base / "RetroPocket"
        elif compat.MACOS:
            environment = {"XDG_DATA_HOME": "relative", "HOME": str(self.base)}
            expected = self.base / "Library" / "Application Support" / "RetroPocket"
        else:
            environment = {"XDG_DATA_HOME": "relative", "HOME": str(self.base)}
            expected = self.base / ".local" / "share" / "retro-pocket"
        with patch.dict("os.environ", environment):
            library = Library(catalog=self.catalog)
        self.assertEqual(library.path(self.entry).parent, expected)

    def test_windows_default_is_local_app_data(self):
        from library import Library
        import compat

        if not compat.WINDOWS:
            self.skipTest("Windows keeps app data in %LOCALAPPDATA%")
        self.library()
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.base / "Local")}):
            os.environ.pop("XDG_DATA_HOME", None)
            library = Library(catalog=self.catalog)
        self.assertEqual(library.path(self.entry).parent, self.base / "Local" / "RetroPocket")

    def test_rejects_malformed_catalog_variants(self):
        for fields in ({"size": 0}, {"size": True}, {"size": 32 * 1024**2 + 1},
                       {"sha256": "a" * 63}, {"sha256": "g" * 64},
                       {"sha256": None}, {"sha256": "a" * 64 + "\n"}):
            with self.subTest(fields=fields):
                self.entry["variants"] = [variant(self.data) | fields]
                with self.assertRaises(ValueError):
                    self.library()
        self.entry["variants"] = [{"size": len(self.data), "label": "Bad", "md5": "0" * 32}]
        with self.assertRaises(ValueError):
            self.library()

    def test_rejects_unsafe_catalog_path_fields(self):
        for fields in ({"id": "../demo"}, {"id": "/tmp/demo"}, {"platform": "NES"}):
            with self.subTest(fields=fields), patch.dict(self.entry, fields):
                with self.assertRaises(ValueError):
                    self.library()

    def test_series_is_optional_but_must_be_a_name(self):
        self.library()  # No series: the default category.
        with patch.dict(self.entry, {"series": "Mario"}):
            self.library()
        for series in ("", "  ", 7, None):
            with self.subTest(series=series), patch.dict(self.entry, {"series": series}):
                with self.assertRaises(ValueError):
                    self.library()

    def test_catalog_entries_cannot_name_a_rom_download(self):
        # Games come only from the ROM folder; the app never fetches ROMs.
        with patch.dict(self.entry, {"download": "https://roms.example/demo.gb"}):
            with self.assertRaisesRegex(ValueError, "ROM folder"):
                self.library()
        from library import Library
        self.assertFalse(any("download" in game for game in Library(root=self.base / "packaged").games))

    def test_mutable_game_dict_does_not_replace_catalog_allowlist(self):
        library = self.library()
        unlisted = b"not in the catalog"
        library.games[0]["variants"] = [variant(unlisted)]
        source = self.base / "unlisted.gb"
        source.write_bytes(unlisted)
        with self.assertRaises(ValueError):
            library.import_rom(library.games[0], source)

    def test_rejects_catalogued_zip_bytes_without_extracting(self):
        source = self.base / "archive.gb"
        with ZipFile(source, "w") as archive:
            archive.writestr("demo.gb", self.data)
        self.entry["variants"] = [variant(source.read_bytes())]
        library = self.library()
        with self.assertRaises(ValueError):
            library.import_rom(self.entry, source)
        self.assertFalse(library.path(self.entry).exists())

    def test_load_rejects_corrupted_cache_and_preserves_file(self):
        library = self.library()
        cached = library.path(self.entry)
        cached.parent.mkdir(parents=True)
        cached.write_bytes(self.data)
        # Corrupt the cached file in place
        corrupted = bytes([self.data[0] ^ 1]) + self.data[1:]
        cached.write_bytes(corrupted)
        with self.assertRaises(ValueError):
            library.load(self.entry)
        # The corrupted file remains (library doesn't auto-delete on mismatch)
        self.assertEqual(cached.read_bytes(), corrupted)

    def test_import_rejects_corrupted_source_and_preserves_existing_cache(self):
        library = self.library()
        source = self.base / "rom.gb"
        source.write_bytes(self.data)
        library.import_rom(self.entry, source)
        # Corrupt the source file
        corrupted = bytes([self.data[0] ^ 1]) + self.data[1:]
        source.write_bytes(corrupted)
        with self.assertRaises(ValueError):
            library.import_rom(self.entry, source)
        # Original cache is preserved
        self.assertEqual(library.load(self.entry), self.data)
