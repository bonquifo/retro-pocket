import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import support
from support import LINUX, MACOS, WINDOWS

# A Dolphin stand-in: frontend option, --user DIR, --exec ROM; records each run in DIR.
STAND_IN = r'''
import os, sys
from pathlib import Path
args = sys.argv[1:]
assert len(args) == 5, args
assert args[0] == os.environ.get('EXPECTED_FRONTEND', '--batch'), args
assert args[1] == '--user' and args[3] == '--exec', args
assert args[4] == os.environ['EXPECTED_ROM'], args
assert Path(args[4]).read_bytes() == b'verified'
with open(Path(args[2]) / 'probe', 'a') as probe:
    probe.write('ran')
'''


class DolphinLaunchTests(unittest.TestCase):
    @unittest.skipUnless(LINUX, 'the native X11 frontend is Linux only')
    def test_x11_distro_frontend_uses_nogui_arguments(self):
        from dolphin_backend import launch

        with patch.dict(os.environ, DISPLAY=':3', RETRO_POCKET_DOLPHIN_NOGUI=str(self.executable),
                        EXPECTED_FRONTEND='--platform=x11'):
            self.assertEqual(launch(self.rom, 'gcn-test', self.saves).wait(timeout=10), 0)

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.rom = self.root / 'staged game;literal.iso'
        self.rom.write_bytes(b'verified')
        self.saves = self.root / 'save data;literal'
        self.executable = support.program(self.root / 'test dolphin', STAND_IN)
        env = patch.dict(os.environ, EXPECTED_ROM=str(self.rom), RETRO_POCKET_DOLPHIN=str(self.executable))
        env.start()
        self.addCleanup(env.stop)

    def test_launch_passes_staged_path_to_child_without_copying(self):
        from dolphin_backend import launch

        process = launch(support.relative(self.rom), 'one', self.saves)
        self.assertIsInstance(process, subprocess.Popen)
        self.assertEqual(process.wait(timeout=10), 0)
        self.assertFalse(list(self.saves.rglob('*.iso')))
        self.assertEqual(self.rom.read_bytes(), b'verified')

    def test_rejects_invalid_title_ids_before_creating_save_data(self):
        from dolphin_backend import launch

        for game_id in ('../escape', '/absolute', 'bad/name', '-option', '', 'one two', 'bad\\name'):
            with self.subTest(game_id=game_id), self.assertRaisesRegex(ValueError, 'game ID'):
                launch(self.rom, game_id, self.saves)
        self.assertFalse(self.saves.exists())

    def test_seeds_wii_keyboard_mapping_without_overwriting_edits(self):
        from dolphin_backend import launch

        config = self.saves / 'wii-battle-revolution' / 'Config' / 'WiimoteNew.ini'
        self.assertEqual(launch(self.rom, 'wii-battle-revolution', self.saves).wait(timeout=10), 0)
        self.assertIn('Buttons/A = X | `Click 1`', config.read_text())
        self.assertIn('D-Pad/Up = Up', config.read_text())
        # The keyboard and mouse device as Dolphin names it on this platform.
        device = ('DInput/0/Keyboard Mouse' if WINDOWS else 'Quartz/0/Keyboard & Mouse' if MACOS
                  else 'XInput2/0/Virtual core pointer')
        self.assertIn(f'Device = {device}\n', config.read_text())
        config.write_text('[Wiimote1]\nButtons/A = P\n')
        self.assertEqual(launch(self.rom, 'wii-battle-revolution', self.saves).wait(timeout=10), 0)
        self.assertEqual(config.read_text(), '[Wiimote1]\nButtons/A = P\n')

    def test_user_directory_persists_per_title_and_is_isolated(self):
        from dolphin_backend import launch

        for game_id in ('one', 'two', 'one'):
            self.assertEqual(launch(self.rom, game_id, self.saves).wait(timeout=10), 0)
        self.assertEqual((self.saves / 'one' / 'probe').read_text(), 'ranran')
        self.assertEqual((self.saves / 'two' / 'probe').read_text(), 'ran')

    def test_invalid_override_does_not_select_installed_executable(self):
        from dolphin_backend import launch

        not_executable = support.no_executable(self.root / 'not executable')
        with patch('dolphin_backend._INSTALLED_EXECUTABLES', (self.executable,)):
            for value in ('', 'dolphin-emu', str(self.root), str(not_executable)):
                with self.subTest(value=value), patch.dict(os.environ, RETRO_POCKET_DOLPHIN=value):
                    with self.assertRaisesRegex(FileNotFoundError, 'RETRO_POCKET_DOLPHIN'):
                        launch(self.rom, 'one', self.saves)
        self.assertFalse(self.saves.exists())

    def test_autodetection_only_uses_fixed_paths(self):
        from dolphin_backend import launch

        support.decoy(self.root / ('Dolphin' if WINDOWS else 'dolphin-emu'), self.executable)
        with patch.dict(os.environ, support.minimal_env(PATH=self.root, EXPECTED_ROM=self.rom), clear=True):
            with patch('dolphin_backend._INSTALLED_EXECUTABLES', ()):
                hint = 'emulators.dolphin' if WINDOWS else 'Dolphin.app' if MACOS else 'install dolphin-emu'
                with self.assertRaisesRegex(FileNotFoundError, hint):
                    launch(self.rom, 'one', self.saves)
            with patch('dolphin_backend._INSTALLED_EXECUTABLES', (self.root / 'missing', self.executable)):
                self.assertEqual(launch(self.rom, 'one', self.saves).wait(timeout=10), 0)
