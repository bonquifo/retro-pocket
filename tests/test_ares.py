"""ares, the macOS N64 emulator. The backend works with any ares, so this runs everywhere."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ares_backend
from controls import C_KEYS, DPAD_KEYS, LAYOUT
import support

REPORT = r'''
import json, os, sys
from pathlib import Path
Path('report.json').write_text(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()}))
'''


class AresSettingsTest(unittest.TestCase):
    def setUp(self):
        self.lines = ares_backend.settings_text().splitlines()

    def bound(self, name):
        line = next(line for line in self.lines if line.strip().startswith(f'{name}: '))
        return line.split(': ')[1]

    def test_n64_controls_match_the_linux_and_windows_layout(self):
        key = ares_backend.binding
        # ares's virtual pad: N64 A = South, B = West, Z = R-Trigger (desktop-ui/emulator/nintendo-64.cpp)
        expected = {
            'A..South': key(LAYOUT['a']), 'X..West': key(LAYOUT['b']), 'R-Trigger': key(LAYOUT['y']),
            'L-Bumper': key(LAYOUT['l']), 'R-Bumper': key(LAYOUT['r']), 'Start': key(LAYOUT['start']),
            'L-Up': key('up'), 'L-Right': key('right'), 'Pad.Up': key(DPAD_KEYS['up']),
            'R-Left': key(C_KEYS['left']), 'QuitEmulator': key('escape'),
        }
        for name, value in expected.items():
            self.assertEqual(self.bound(name), value, name)
        # ares's macOS key list: X is key 63, Return 97, the up arrow 92, Escape 0.
        self.assertEqual(self.bound('A..South'), '0x1/0/63')
        self.assertEqual(self.bound('Start'), '0x1/0/97')
        self.assertEqual(self.bound('L-Up'), '0x1/0/92')
        self.assertEqual(self.bound('QuitEmulator'), '0x1/0/0')

    def test_settings_file_is_bml_with_two_space_children_and_no_key_twice(self):
        self.assertEqual(self.lines[0], 'VirtualPad1')
        self.assertIn('Hotkey', self.lines)
        children = [line for line in self.lines if line.startswith('  ')]
        self.assertTrue(all(': 0x1/0/' in line for line in children))
        keys = [line.split(': ')[1] for line in children]
        self.assertEqual(len(keys), len(set(keys)))


class AresLaunchTest(unittest.TestCase):
    def test_runs_ares_with_this_games_settings_and_keeps_later_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saves = root / 'saves' / 'n64-test'
            saves.mkdir(parents=True)
            rom = saves / 'n64-test.z64'
            rom.write_bytes(b'verified')
            program = support.program(root / 'ares', REPORT)
            self.assertEqual(ares_backend.start(program, rom, saves).wait(timeout=10), 0)
            seen = json.loads((saves / 'report.json').read_text())
            settings = saves / 'ares' / 'settings.bml'
            self.assertEqual(seen['argv'], ['--system', 'Nintendo 64', '--no-file-prompt',
                                            '--settings-file', str(settings), str(rom)])
            self.assertEqual(Path(seen['cwd']).resolve(), saves.resolve())
            self.assertEqual(settings.read_text(), ares_backend.settings_text())
            settings.write_text('VirtualPad1\n  A..South: 0x1/0/40\n')  # Remapped in ares: kept.
            self.assertEqual(ares_backend.start(program, rom, saves).wait(timeout=10), 0)
            self.assertEqual(settings.read_text(), 'VirtualPad1\n  A..South: 0x1/0/40\n')

    def test_refuses_a_linked_settings_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / 'outside'
            outside.mkdir()
            support.directory_link(root / 'ares', outside)
            with self.assertRaisesRegex(ValueError, 'symlink'):
                ares_backend.start(root / 'ares-program', root / 'game.z64', root)
            self.assertEqual(list(outside.iterdir()), [])


class MacN64DispatchTest(unittest.TestCase):
    def test_macos_n64_games_start_ares_on_the_staged_rom(self):
        import n64

        with tempfile.TemporaryDirectory() as tmp:
            saves = Path(tmp) / 'saves'
            program = Path(tmp) / 'ares'
            with patch('compat.MACOS', True), patch('n64._find_executable', return_value=program), \
                    patch('ares_backend.start', return_value='process') as start:
                self.assertEqual(n64.launch(b'rom', 'n64-test', saves), 'process')
            start.assert_called_once_with(program, saves.resolve() / 'n64-test.z64', saves.resolve())
            self.assertFalse(os.path.exists(saves / 'mupen64plus.cfg'))
