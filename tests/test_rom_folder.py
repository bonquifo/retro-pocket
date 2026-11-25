import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import ds
import library
from library import Library
import support


def entry(game_id, data, platform='GB', **extra):
    return dict(id=game_id, title=game_id, platform=platform, year=2000,
                variants=[dict(label='Test', size=len(data), sha1=hashlib.sha1(data).hexdigest())], **extra)


class RomFolderTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.red, self.blue = b'R' * 4096, b'B' * 4096  # Same size: only the digest tells them apart.
        self.games = [entry('red', self.red), entry('blue', self.blue)]
        self.catalog = self.base / 'catalog.json'
        self.catalog.write_text(json.dumps(self.games))
        self.roms = self.base / 'roms'
        (self.roms / 'nested').mkdir(parents=True)

    def library(self):
        return Library(self.base / 'data', self.catalog, rom_dir=self.roms)

    def test_matches_by_content_not_filename_including_subfolders(self):
        (self.roms / 'nested' / 'Pokemon Red.gb').write_bytes(self.blue)
        (self.roms / 'unrelated.gb').write_bytes(b'x' * 4096)
        (self.roms / 'notes.txt').write_bytes(self.red)  # Wrong suffix is ignored.
        lib = self.library()
        self.assertEqual(lib.scan(), {'blue': self.roms / 'nested' / 'Pokemon Red.gb'})
        self.assertIsNone(lib.found(self.games[0]))
        self.assertEqual(lib.load(self.games[1]), self.blue)
        with self.assertRaises(FileNotFoundError):  # Red is neither found nor imported.
            lib.load(self.games[0])

    def test_digest_cache_avoids_rehashing_unchanged_files(self):
        rom = self.roms / 'red.gb'
        rom.write_bytes(self.red)
        self.library().scan()
        with patch('library._file_digests', side_effect=AssertionError('rehashed')):
            self.assertEqual(self.library().scan(), {'red': rom})
        rom.write_bytes(self.blue)  # A changed file is hashed again.
        os.utime(rom, ns=(1, 1))
        self.assertEqual(self.library().scan(), {'blue': rom})

    def test_imported_copy_takes_precedence_and_import_never_writes_rom_folder(self):
        rom = self.roms / 'red.gb'
        rom.write_bytes(self.red)
        lib = self.library()
        lib.scan()
        self.assertEqual(lib.source(self.games[0]), rom)
        other = self.base / 'dump.gb'
        other.write_bytes(self.red)
        imported = lib.import_rom(self.games[0], other)
        self.assertEqual(imported.parent, self.base / 'data')
        self.assertEqual(lib.source(self.games[0]), imported)
        self.assertEqual(rom.read_bytes(), self.red)

    def test_stage_reads_the_rom_folder_copy_and_rechecks_it(self):
        rom = self.roms / 'red.gb'
        rom.write_bytes(self.red)
        lib = self.library()
        lib.scan()
        stage = lib.stage(self.games[0], self.base / 'stage' / lib.staged_name(self.games[0]))
        self.assertEqual((stage.name, stage.read_bytes()), ('red.gb', self.red))
        rom.write_bytes(self.blue)  # Swapped after the scan: launch must refuse it.
        with self.assertRaisesRegex(ValueError, 'digest'):
            lib.stage(self.games[0], self.base / 'stage2.gb')

    def test_missing_folder_and_symlinks_are_ignored(self):
        outside = self.base / 'outside.gb'
        outside.write_bytes(self.red)
        elsewhere = self.base / 'elsewhere'
        elsewhere.mkdir()
        (elsewhere / 'blue.gb').write_bytes(self.blue)
        if support.can_symlink(self.roms):
            (self.roms / 'link.gb').symlink_to(outside)
        support.directory_link(self.roms / 'linked folder', elsewhere)  # A junction on Windows
        self.assertEqual(self.library().scan(), {})
        self.assertEqual(Library(self.base / 'data', self.catalog, rom_dir=self.base / 'none').scan(), {})

    def test_parallel_scan_is_deterministic_and_sequential_on_spinning_disks(self):
        for name in ('c.gb', 'a.gb', 'b.gb'):
            (self.roms / name).write_bytes(self.red)
        (self.roms / 'nested' / 'z.gb').write_bytes(self.blue)
        import concurrent.futures
        seen = []
        real = concurrent.futures.ThreadPoolExecutor

        def pool(workers):
            seen.append(workers)
            return real(workers)
        for rotational in (False, True):
            with self.subTest(rotational=rotational):
                (self.base / 'data' / 'rom-index.json').unlink(missing_ok=True)
                with patch('library._rotational', return_value=rotational), \
                        patch('library.ThreadPoolExecutor', side_effect=pool):
                    found = self.library().scan()
                self.assertEqual(found, {'red': self.roms / 'a.gb', 'blue': self.roms / 'nested' / 'z.gb'})
                self.assertEqual(seen[-1] == 1, rotational or (os.cpu_count() or 1) == 1)

    def test_scan_only_limits_work_to_one_game(self):
        (self.roms / 'a.gb').write_bytes(self.red)
        (self.roms / 'b.gb').write_bytes(self.blue)
        lib = self.library()
        self.assertEqual(lib.scan(only='blue'), {'blue': self.roms / 'b.gb'})

    def test_default_rom_dir_honours_environment(self):
        with patch.dict(os.environ, {'RETRO_POCKET_ROMS': str(self.roms)}):
            self.assertEqual(library.default_rom_dir(), self.roms)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(library.default_rom_dir(), Path(library.__file__).resolve().with_name('roms'))


class ZeroCopyLaunchTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.data = b'N' * (3 * 1024 * 1024 + 7)
        self.game = entry('nds-test', self.data, platform='NDS')
        catalog = self.base / 'catalog.json'
        catalog.write_text(json.dumps([self.game]))
        self.roms = self.base / 'roms'
        self.roms.mkdir()
        self.rom = self.roms / 'Game (USA).nds'
        self.rom.write_bytes(self.data)
        self.lib = Library(self.base / 'data', catalog, rom_dir=self.roms)
        self.lib.scan()

    def test_verify_checks_in_place_without_writing(self):
        self.assertEqual(self.lib.verify(self.game), self.rom)
        self.assertEqual([p.name for p in (self.base / 'data').iterdir()], ['rom-index.json'])
        self.rom.write_bytes(b'X' + self.data[1:])
        with self.assertRaisesRegex(ValueError, 'digest'):
            self.lib.verify(self.game)

    def test_place_hard_links_and_replaces_stale_files(self):
        target = self.base / 'saves' / 'nds-test.nds'
        target.parent.mkdir()
        outside = self.base / 'outside'
        outside.write_bytes(b'keep')
        if support.can_symlink(self.base):
            target.symlink_to(outside)
        else:
            target.write_bytes(b'stale')  # Windows without symlink rights: a stale file instead.
        self.assertEqual(self.lib.place(self.game, target), target)
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.stat().st_ino, self.rom.stat().st_ino)
        self.assertEqual(outside.read_bytes(), b'keep')
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ['nds-test.nds'])

    def test_place_falls_back_to_a_verified_copy_when_linking_fails(self):
        target = self.base / 'saves' / 'nds-test.nds'
        with patch('library.os.link', side_effect=OSError(18, 'Invalid cross-device link')):
            self.lib.place(self.game, target)
        self.assertNotEqual(target.stat().st_ino, self.rom.stat().st_ino)
        self.assertEqual(target.read_bytes(), self.data)

    def test_place_refuses_a_mismatched_source(self):
        self.rom.write_bytes(b'X' + self.data[1:])
        target = self.base / 'saves' / 'nds-test.nds'
        with self.assertRaisesRegex(ValueError, 'digest'):
            self.lib.place(self.game, target)
        self.assertFalse(target.exists())

    def test_ds_worker_links_rom_under_stable_name_without_loading_it(self):
        import emulator_worker

        exe = support.program(self.base / 'desmume',
                              'import os, sys\nprint(os.stat(sys.argv[1]).st_ino, sys.argv[1])\n')
        with patch.dict(os.environ, {ds.OVERRIDE_ENV: str(exe)}), \
                patch.object(Library, 'load', side_effect=AssertionError('ROM loaded into memory')):
            self.assertEqual(emulator_worker.run_game(self.lib, 'nds-test'), 0)
        placed = (self.base / 'data' / 'saves' / 'nds-test' / 'nds-test.nds').resolve()
        self.assertEqual(placed.stat().st_ino, self.rom.stat().st_ino)

    def test_worker_explains_a_rom_damaged_after_the_scan(self):
        import emulator_worker

        self.rom.write_bytes(b'X' + self.data[1:])
        os.utime(self.rom, ns=(1, 1))  # Changed after the app's scan: the worker re-checks it.
        # The worker is a separate process with a fresh Library.
        fresh = Library(self.base / 'data', self.base / 'catalog.json', rom_dir=self.roms)
        with self.assertRaisesRegex(ValueError, 'missing.*digest'):
            emulator_worker.run_game(fresh, 'nds-test')

    def test_launchers_reject_a_path_not_at_the_stable_name(self):
        from ds import launch

        with patch.dict(os.environ, {ds.OVERRIDE_ENV: sys.executable}):
            with self.assertRaisesRegex(ValueError, 'placed'):
                launch(self.rom, 'nds-test', self.base / 'saves')


class RomFolderWorkerTests(unittest.TestCase):
    def test_session_passes_rom_folder_to_worker(self):
        from session import EmulatorSession

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            catalog = d / 'catalog.json'
            catalog.write_text(json.dumps([entry('red', b'r')]))
            lib = Library(d / 'data', catalog, rom_dir=d / 'roms')
            with patch.object(EmulatorSession, 'start', side_effect=lambda argv, log: argv):
                argv = EmulatorSession.for_game(lib, lib.games[0])
            self.assertEqual(argv[argv.index('--rom-dir') + 1], str(d / 'roms'))
            self.assertEqual(argv[-2:], ['--', 'red'])

    def test_worker_launches_a_game_found_only_in_the_rom_folder(self):
        import emulator_worker

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            data = b'3ds image bytes'
            catalog = d / 'catalog.json'
            catalog.write_text(json.dumps([entry('3ds-test', data, platform='3DS')]))
            roms = d / 'roms'
            roms.mkdir()
            (roms / 'Some Game (USA).3ds').write_bytes(data)
            exe = support.program(d / 'azahar', 'import sys\nfrom pathlib import Path\n'
                                  'rom = Path(sys.argv[1])\n'
                                  'Path("seen.txt").write_text(f"{rom.name} {rom.read_bytes().decode()}")\n')
            lib = Library(d / 'data', catalog, rom_dir=roms)  # Fresh process: no prior scan.
            with patch.dict(os.environ, {'RETRO_POCKET_AZAHAR': str(exe)}):
                self.assertEqual(emulator_worker.run_game(lib, '3ds-test'), 0)
            seen = d / 'data' / 'saves' / '3ds-test' / 'azahar' / '3ds-test' / 'seen.txt'
            self.assertEqual(seen.read_text(), '3ds-test.3ds 3ds image bytes')
            self.assertFalse((d / 'data' / '3ds-test.3ds').exists())  # Nothing imported.


if __name__ == '__main__':
    unittest.main()
