import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import support

# A PokeMini stand-in: fixed options, then the EEPROM and ROM paths in its
# working directory. It writes the EEPROM, as the emulator does on exit.
STAND_IN = r'''
import sys
from pathlib import Path
args, here = sys.argv[1:], Path.cwd()
assert len(args) == 6, args
assert args[:4] == ['-freebios', '-nostate', '-eepromshare', '-eeprom'], args
assert Path(args[4]) == here / 'mini-test.eep', (args[4], here)
assert Path(args[5]) == here / 'mini-test.min' and Path(args[5]).is_file(), (args[5], here)
Path(args[4]).write_bytes(b'emulator-save')
'''


class MiniLaunchTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.save_dir = self.root / 'saves with spaces;literal'
        self.executable = support.program(self.root / 'PokeMini SDL2', STAND_IN)

    def test_launch_stages_exact_bytes_and_gives_emulator_a_save_path(self):
        from mini import launch

        rom = b'\x00verified\xff\n'
        self.save_dir.mkdir()
        staged = self.save_dir / 'mini-test.min'
        other_file = self.root / 'other-file'
        other_file.write_bytes(b'untouched')
        if support.can_symlink(self.root):
            staged.symlink_to(other_file)
        else:
            staged.write_bytes(b'stale')  # Windows without symlink rights: a stale copy instead.
        with patch.dict(os.environ, {'RETRO_POCKET_POKEMINI': str(self.executable)}):
            process = launch(rom, 'mini-test', Path(os.path.relpath(self.save_dir)))
            self.assertIsInstance(process, subprocess.Popen)
            self.assertEqual(process.wait(timeout=10), 0)
        self.assertFalse(staged.is_symlink())
        self.assertEqual(staged.read_bytes(), rom)
        self.assertEqual(other_file.read_bytes(), b'untouched')
        self.assertEqual((self.save_dir / 'mini-test.eep').read_bytes(), b'emulator-save')

    def test_invalid_ids_and_long_native_paths_are_rejected_before_staging(self):
        from mini import launch

        with patch.dict(os.environ, {'RETRO_POCKET_POKEMINI': str(self.executable)}):
            for game_id in ('', '-option', '../escape', 'bad/id', 'bad;id', 'bad\\id', 'x' * 150):
                with self.subTest(game_id=game_id), self.assertRaises(ValueError):
                    launch(b'verified', game_id, self.save_dir)
        self.assertFalse(self.save_dir.exists())

    def test_rejects_automatic_color_sidecar(self):
        from mini import launch

        self.save_dir.mkdir()
        (self.save_dir / 'mini-test.minc').write_bytes(b'unverified')
        with patch.dict(os.environ, {'RETRO_POCKET_POKEMINI': str(self.executable)}):
            with self.assertRaisesRegex(ValueError, 'color sidecar'):
                launch(b'verified', 'mini-test', self.save_dir)
        self.assertFalse((self.save_dir / 'mini-test.min').exists())

    def test_rejects_eeprom_symlink(self):
        from mini import launch

        self.save_dir.mkdir()
        support.symlink(self, self.save_dir / 'mini-test.eep', self.root / 'elsewhere')
        with patch.dict(os.environ, {'RETRO_POCKET_POKEMINI': str(self.executable)}):
            with self.assertRaisesRegex(ValueError, 'EEPROM'):
                launch(b'verified', 'mini-test', self.save_dir)
        self.assertFalse((self.root / 'elsewhere').exists())

    def test_relative_override_does_not_fall_back(self):
        from mini import launch

        no_execute = support.no_executable(self.root / 'non-executable')
        for override in ('PokeMini', '', str(self.root), str(no_execute)):
            with self.subTest(override=override), patch.dict(
                os.environ, {'RETRO_POCKET_POKEMINI': override}
            ), patch('mini._INSTALLED_EXECUTABLES', (self.executable,)):
                with self.assertRaisesRegex(FileNotFoundError, 'RETRO_POCKET_POKEMINI'):
                    launch(b'verified', 'mini-test', self.save_dir)
        self.assertFalse(self.save_dir.exists())

    def test_discovery_uses_fixed_paths_only(self):
        from mini import launch

        support.decoy(self.root / 'PokeMini', self.executable)
        with patch.dict(os.environ, support.minimal_env(PATH=self.root), clear=True):
            with patch('mini._INSTALLED_EXECUTABLES', ()):
                with self.assertRaisesRegex(FileNotFoundError, 'Native PokeMini not found'):
                    launch(b'verified', 'mini-test', self.save_dir)
            with patch('mini._INSTALLED_EXECUTABLES', (self.executable,)):
                self.assertEqual(launch(b'verified', 'mini-test', self.save_dir).wait(10), 0)
