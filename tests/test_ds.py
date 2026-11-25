import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import ds
import support
from support import LINUX, WINDOWS

# A stand-in for the DS emulator (a real child process, not a mock of Popen)
# that checks what it is given: one argument, the staged ROM. Linux runs
# DeSmuME with $XDG_CONFIG_HOME at the save folder; Windows (DeSmuME) and
# macOS (melonDS) run the game's own linked copy of the emulator from a
# folder beside the ROM.
CHECK = r'''
import os, sys
from pathlib import Path
assert len(sys.argv) == 2, sys.argv
rom = Path(sys.argv[1])
assert rom.is_absolute() and rom.is_file(), rom
if os.name == 'nt' or sys.platform == 'darwin':
    here = Path(sys.argv[0]).resolve().parent
    assert Path.cwd().resolve() == here, (Path.cwd(), here)
    assert here.name in ('desmume', 'melonds') and rom == here.parent / 'test-game.nds', (here, rom)
else:
    assert str(rom) == os.environ['XDG_CONFIG_HOME'] + '/test-game.nds', rom
'''
OVERRIDE = ds.OVERRIDE_ENV  # RETRO_POCKET_DESMUME, or RETRO_POCKET_MELONDS on macOS


class DSLaunchTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.executable = support.program(self.root / 'SDL emulator', CHECK)
        self.save_dir = self.root / 'saves with spaces;literal'

    def test_launch_stages_exact_bytes_and_returns_process(self):
        from ds import launch

        rom = b'\x00verified\xff\n'
        staged = self.save_dir / 'test-game.nds'
        self.save_dir.mkdir()
        staged.write_bytes(b'stale bytes')
        relative_save_dir = Path(os.path.relpath(self.save_dir))
        with patch.dict(os.environ, {OVERRIDE: str(self.executable)}):
            proc = launch(rom, 'test-game', relative_save_dir)
            self.assertIsInstance(proc, subprocess.Popen)
            self.assertEqual(proc.wait(timeout=10), 0)
        self.assertEqual(staged.read_bytes(), rom)

    def test_existing_rom_symlink_is_replaced_without_writing_to_target(self):
        from ds import launch

        self.save_dir.mkdir()
        target = self.root / 'unrelated-file'
        target.write_bytes(b'keep me')
        staged = self.save_dir / 'test-game.nds'
        support.symlink(self, staged, target)
        with patch.dict(os.environ, {OVERRIDE: str(self.executable)}):
            self.assertEqual(launch(b'verified', 'test-game', self.save_dir).wait(10), 0)
        self.assertEqual(target.read_bytes(), b'keep me')
        self.assertFalse(staged.is_symlink())
        self.assertEqual(staged.read_bytes(), b'verified')

    def test_catalog_id_cannot_escape_staging_directory(self):
        from ds import launch

        with patch.dict(os.environ, {OVERRIDE: str(self.executable)}):
            for game_id in ('../escape', '/absolute', 'bad/name', '-option', '', 'foo|bar', 'a\\b', 'C:x'):
                with self.subTest(game_id=game_id), self.assertRaisesRegex(ValueError, 'game ID'):
                    launch(b'verified', game_id, self.save_dir)
        self.assertFalse(self.save_dir.exists())

    def test_invalid_explicit_override_does_not_fall_back(self):
        from ds import launch

        not_a_program = support.no_executable(self.root / 'desmume.bat')
        for override in ('desmume-cli', str(self.root / 'missing'), str(self.root), str(not_a_program)):
            with self.subTest(override=override), patch.dict(os.environ, {OVERRIDE: override}):
                with self.assertRaisesRegex(OSError, OVERRIDE):
                    launch(b'verified', 'test-game', self.save_dir)
        self.assertFalse(self.save_dir.exists())

    def test_autodetection_uses_fixed_installed_paths_not_path(self):
        from ds import launch

        support.program(self.root / 'desmume-cli', 'raise SystemExit(42)\n')
        support.program(self.root / 'DeSmuME', 'raise SystemExit(42)\n')
        with patch.dict(os.environ, support.minimal_env(PATH=self.root), clear=True), patch(
            'ds._INSTALLED_EXECUTABLES', (self.root / 'missing', self.executable)
        ):
            self.assertEqual(launch(b'verified', 'test-game', self.save_dir).wait(10), 0)

    def test_missing_emulator_reports_package_and_override(self):
        from ds import launch

        with patch.dict(os.environ, support.minimal_env(), clear=True), patch('ds._INSTALLED_EXECUTABLES', ()):
            package = 'melonds' if support.MACOS else 'desmume'
            with self.assertRaisesRegex(FileNotFoundError, f'install.*{package}.*{OVERRIDE}'):
                launch(b'verified', 'test-game', self.save_dir)
        self.assertFalse(self.save_dir.exists())

    @unittest.skipUnless(LINUX, 'the keyboard shim works around a Linux desmume-cli bug')
    def test_launch_preloads_keyboard_shim_and_runs_in_save_dir(self):
        save_dir = self.root / 'plain-saves' / 'test-game'
        support.program(self.executable, (
            'import fnmatch, os, sys\n'
            'assert os.getcwd() == os.environ["XDG_CONFIG_HOME"]\n'
            'if not fnmatch.fnmatchcase(os.environ.get("LD_PRELOAD", ""), "*/.ds-input/ds-input-*.so"):\n'
            '    sys.exit(3)\n'
            f'assert os.environ["RETRO_POCKET_DS_KEYMAP"] == {ds.keymap()!r}\n'))
        if not any(c.is_file() for c in ds._COMPILERS):
            self.skipTest('no C compiler')
        with patch.dict(os.environ, {OVERRIDE: str(self.executable)}):
            self.assertEqual(ds.launch(b'rom', 'test-game', save_dir).wait(timeout=60), 0)

    @unittest.skipUnless(WINDOWS, 'Windows DeSmuME keeps its settings beside its program')
    def test_windows_game_runs_its_own_linked_desmume_with_saves_beside_it(self):
        import ds

        (self.root / 'desmume.ddb').write_bytes(b'save-type database')
        profile = self.save_dir / 'desmume'
        with patch.dict(os.environ, {OVERRIDE: str(self.executable)}):
            self.assertEqual(ds.launch(b'rom', 'test-game', self.save_dir).wait(timeout=10), 0)
            copy = profile / self.executable.name
            self.assertTrue(os.path.samefile(copy, self.executable))  # A hard link, not a copy.
            self.assertEqual((profile / 'desmume.ddb').read_bytes(), b'save-type database')
            ini = profile / 'desmume.ini'
            self.assertEqual(ini.read_bytes(), b'[PathSettings]\r\nBattery=.\\\r\n[Video]\r\nWindow Size=2\r\n')
            ini.write_text('[PathSettings]\nBattery=elsewhere\n')  # Changed in DeSmuME: kept.
            self.assertEqual(ds.launch(b'rom', 'test-game', self.save_dir).wait(timeout=10), 0)
        self.assertIn('elsewhere', ini.read_text())
        self.assertEqual(sorted(p.name for p in self.save_dir.iterdir()), ['desmume', 'test-game.nds'])

    @unittest.skipUnless(WINDOWS, 'Windows DeSmuME keeps its settings beside its program')
    def test_windows_refuses_a_linked_profile_folder(self):
        from ds import launch

        outside = self.root / 'outside'
        outside.mkdir()
        self.save_dir.mkdir()
        support.directory_link(self.save_dir / 'desmume', outside)
        with patch.dict(os.environ, {OVERRIDE: str(self.executable)}):
            with self.assertRaisesRegex(ValueError, 'symlink'):
                launch(b'rom', 'test-game', self.save_dir)
        self.assertEqual(list(outside.iterdir()), [])


@unittest.skipUnless(LINUX and any(Path(c).is_file() for c in ('/usr/bin/cc', '/usr/bin/gcc')),
                     'the shim fixes Linux desmume-cli and needs a C compiler')
class DSInputShimTests(unittest.TestCase):
    """Drive the compiled shim's translation with raw SDL2 event bytes."""

    @classmethod
    def setUpClass(cls):
        import ctypes
        import ds

        cls.tmp = tempfile.TemporaryDirectory()
        os.environ['RETRO_POCKET_DS_KEYMAP'] = ds.keymap()
        cls.lib = ctypes.CDLL(str(ds.input_shim(Path(cls.tmp.name))))

    @classmethod
    def tearDownClass(cls):
        os.environ.pop('RETRO_POCKET_DS_KEYMAP', None)
        cls.tmp.cleanup()

    def send(self, key, down=True):
        import ctypes
        import struct
        from controls import sdl_keycode

        event = ctypes.create_string_buffer(56)
        struct.pack_into('<IIIBBxxii', event, 0, 0x300 if down else 0x301, 7, 1, down, 0, 0, sdl_keycode(key))
        changed = self.lib.rp_ds_translate(event)
        return changed, event.raw

    def test_every_layout_key_becomes_the_matching_joystick_input(self):
        import struct
        from controls import LAYOUT

        buttons = {'a': 1, 'b': 0, 'x': 4, 'y': 3, 'l': 6, 'r': 7, 'start': 8, 'select': 5}
        for button, index in buttons.items():
            for down in (True, False):
                changed, raw = self.send(LAYOUT[button], down)
                self.assertEqual(changed, 1)
                self.assertEqual(struct.unpack_from('<IIiBB', raw), (0x603 if down else 0x604, 7, 0, index, down))
        for button, (axis, value) in {'right': (0, 32767), 'left': (0, -32767),
                                      'up': (1, -32767), 'down': (1, 32767)}.items():
            changed, raw = self.send(LAYOUT[button])
            self.assertEqual((struct.unpack_from('<IiB', raw, 0)[0], raw[12], struct.unpack_from('<h', raw, 16)[0]),
                             (0x600, axis, value), button)
            changed, raw = self.send(LAYOUT[button], down=False)
            self.assertEqual(struct.unpack_from('<h', raw, 16)[0], 0)

    def test_opposite_direction_survives_release_and_other_keys_pass_through(self):
        import struct

        self.send('left')
        self.send('right')
        _, raw = self.send('right', down=False)
        self.assertEqual(struct.unpack_from('<h', raw, 16)[0], -32767)  # Left is still held.
        self.send('left', down=False)
        changed, raw = self.send('p')
        self.assertEqual(changed, 0)
        self.assertEqual(struct.unpack_from('<I', raw)[0], 0x300)
