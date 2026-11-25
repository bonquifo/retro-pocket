"""melonDS, the macOS DS emulator. The backend works with any melonDS, so this runs everywhere."""
import json
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

import melonds_backend
import support

# Reports what melonDS would see: its arguments, its folder and whether its
# portable settings folder (beside the program, or beside the .app) exists.
REPORT = r'''
import json, os, sys
from pathlib import Path
program = Path(sys.argv[0]).resolve()
contents = program.parent.parent
home = contents.parent.parent if contents.name == 'Contents' else program.parent
Path('report.json').write_text(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd(), 'program': str(program),
                                           'portable': (home / 'portable' / 'melonDS.toml').is_file()}))
'''


class MelonDSSettingsTest(unittest.TestCase):
    def test_keyboard_layout_uses_melonds_key_numbers(self):
        text = melonds_backend.settings_text(macos=False)
        self.assertTrue(text.startswith('[Instance0.Keyboard]\n'))
        values = dict(line.split(' = ') for line in text.splitlines()[1:])
        self.assertEqual(values['A'], str(ord('X')))
        self.assertEqual(values['B'], str(ord('Z')))
        self.assertEqual(values['X'], str(ord('S')))
        self.assertEqual(values['Y'], str(ord('A')))
        self.assertEqual((values['L'], values['R']), (str(ord('Q')), str(ord('W'))))
        self.assertEqual(values['Start'], str(0x01000004))             # Qt::Key_Return
        self.assertEqual(values['Select'], str(0x81000020 - (1 << 32)))  # Qt::Key_Shift, right-hand
        self.assertEqual(values['Up'], str(0x01000013))
        self.assertEqual(len(set(values.values())), 12)

    def test_macos_arrow_keys_carry_the_keypad_modifier(self):
        values = dict(line.split(' = ') for line in melonds_backend.settings_text(macos=True).splitlines()[1:])
        self.assertEqual(values['Up'], str(0x21000013))  # Qt reports arrows with KeypadModifier on macOS
        self.assertEqual(values['A'], str(ord('X')))


class MelonDSLaunchTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.saves = self.root / 'saves' / 'nds-test'
        self.saves.mkdir(parents=True)
        self.rom = self.saves / 'nds-test.nds'
        self.rom.write_bytes(b'verified')

    def run_melonds(self, program):
        process = melonds_backend.start(program, self.rom, self.saves)
        self.assertEqual(process.wait(timeout=10), 0)
        return json.loads((self.saves / 'melonds' / 'report.json').read_text())

    def test_each_game_runs_its_own_linked_copy_with_portable_settings(self):
        program = support.program(self.root / 'melonDS', REPORT)
        seen = self.run_melonds(program)
        profile = self.saves / 'melonds'
        self.assertEqual(seen['argv'], [str(self.rom)])
        self.assertEqual(Path(seen['cwd']).resolve(), profile.resolve())
        self.assertTrue(os.path.samefile(seen['program'], program))  # A hard link to the installed program
        self.assertTrue(seen['portable'])
        settings = profile / 'portable' / 'melonDS.toml'
        self.assertEqual(settings.read_text(), melonds_backend.settings_text())
        settings.write_text('[Instance0.Keyboard]\nA = 75\n')  # Remapped in melonDS: kept.
        self.run_melonds(program)
        self.assertEqual(settings.read_text(), '[Instance0.Keyboard]\nA = 75\n')

    def test_macos_app_bundle_is_copied_whole_with_settings_beside_it(self):
        bundle = self.root / 'emulators' / 'melonDS.app'
        (bundle / 'Contents' / 'MacOS').mkdir(parents=True)
        (bundle / 'Contents' / 'Resources').mkdir()
        (bundle / 'Contents' / 'Resources' / 'melon.icns').write_bytes(b'icon')
        name = support.program(bundle / 'Contents' / 'MacOS' / 'melonDS', REPORT).name
        (bundle / 'Contents' / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': name}))
        program = melonds_backend.compat.app_executable(bundle)
        self.assertEqual(program, bundle / 'Contents' / 'MacOS' / name)
        seen = self.run_melonds(program)
        copy = self.saves / 'melonds' / 'melonDS.app'
        self.assertEqual(Path(seen['program']), (copy / 'Contents' / 'MacOS' / name).resolve())
        self.assertEqual((copy / 'Contents' / 'Resources' / 'melon.icns').read_bytes(), b'icon')
        self.assertTrue(seen['portable'])  # melonDS looks beside the .app on macOS

    def test_refuses_a_linked_profile_folder(self):
        outside = self.root / 'outside'
        outside.mkdir()
        support.directory_link(self.saves / 'melonds', outside)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            melonds_backend.start(support.program(self.root / 'melonDS', 'pass\n'), self.rom, self.saves)
        self.assertEqual(list(outside.iterdir()), [])


class MacDSDispatchTest(unittest.TestCase):
    def test_macos_ds_games_start_melonds_on_the_staged_rom(self):
        import ds

        with tempfile.TemporaryDirectory() as tmp:
            saves = Path(tmp) / 'saves'
            program = Path(tmp) / 'melonDS'
            with patch('compat.MACOS', True), patch('ds._find_executable', return_value=program), \
                    patch('melonds_backend.start', return_value='process') as start:
                self.assertEqual(ds.launch(b'rom', 'nds-test', saves), 'process')
            start.assert_called_once_with(program, saves.resolve() / 'nds-test.nds', saves.resolve())
            self.assertEqual((saves / 'nds-test.nds').read_bytes(), b'rom')
