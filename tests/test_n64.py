import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import support
from support import WINDOWS

# A Mupen64Plus stand-in: the config folder first, the save paths as the first
# settings, the ROM last. On Windows it also needs the bundle's plugin and data
# folders. Records the other settings and each run in the config folder.
STAND_IN = r'''
import os, sys
from pathlib import Path
args, options, sets = sys.argv[1:], {}, []
while len(args) > 1:
    name, value, args = args[0], args[1], args[2:]
    if name == '--set':
        sets.append(value)
    elif name in ('--configdir', '--plugindir', '--datadir', '--corelib', '--gfx'):
        options[name] = value
    else:
        sys.exit(5)
directory = options.get('--configdir')
if not directory or not Path(directory).is_dir():
    sys.exit(2)
if sets[:2] != [f'Core[SaveSRAMPath]={directory}', f'Core[SaveStatePath]={directory}']:
    sys.exit(3)
if os.name == 'nt':
    bundle = Path(sys.argv[0]).resolve().parent
    if not all(Path(options.get(name, '')).resolve() == bundle for name in ('--plugindir', '--datadir')):
        sys.exit(4)
Path(directory, 'settings').write_text(''.join(s + '\n' for s in sets[2:]))
if len(args) != 1 or not Path(args[0]).is_file():
    sys.exit(6)
print(Path(args[0]).name)
print('emulator stderr', file=sys.stderr)
with open(Path(directory, 'runs'), 'a') as runs:
    runs.write('started\n')
'''


class N64LaunchTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.executable = support.program(self.root / 'mupen64plus test double', STAND_IN)
        self.save_dir = self.root / 'saves with spaces;literal'
        override = patch.dict(os.environ, RETRO_POCKET_MUPEN64PLUS=str(self.executable))
        override.start()
        self.addCleanup(override.stop)

    def test_launch_stages_exact_bytes_and_returns_process(self):
        from n64 import launch

        rom = b'\x80\x37\x12\x40\x00\xff'
        self.save_dir.mkdir()
        staged = self.save_dir / 'test-game.z64'
        staged.write_bytes(b'stale')
        proc = launch(rom, 'test-game', Path(os.path.relpath(self.save_dir)))
        self.assertIsInstance(proc, subprocess.Popen)
        self.assertEqual(proc.wait(timeout=10), 0)
        self.assertEqual(staged.read_bytes(), rom)

    def test_keyboard_uses_the_shared_layout_unless_a_gamepad_is_connected(self):
        from n64 import launch

        for gamepad in (False, True):
            with self.subTest(gamepad=gamepad), patch('n64._gamepad_connected', return_value=gamepad):
                self.assertEqual(launch(b'rom', 'test-game', self.save_dir).wait(timeout=10), 0)
                settings = (self.save_dir / 'settings').read_text().splitlines()
                self.assertIn('CoreEvents[Kbd Mapping Fast Forward]=0', settings)
                self.assertIn('CoreEvents[Kbd Mapping Gameshark]=0', settings)
                keyboard = {
                    'Input-SDL-Control1[mode]=0', 'Input-SDL-Control1[version]=2.000000',
                    'Input-SDL-Control1[A Button]=key(120)',   # X
                    'Input-SDL-Control1[B Button]=key(122)',   # Z
                    'Input-SDL-Control1[Z Trig]=key(97)',      # A (shared Y key)
                    'Input-SDL-Control1[L Trig]=key(113)', 'Input-SDL-Control1[R Trig]=key(119)',
                    'Input-SDL-Control1[Start]=key(13)',
                    'Input-SDL-Control1[DPad U]=key(116)', 'Input-SDL-Control1[DPad L]=key(102)',
                    'Input-SDL-Control1[C Button U]=key(105)', 'Input-SDL-Control1[C Button R]=key(108)',
                    'Input-SDL-Control1[X Axis]=key(276,275)', 'Input-SDL-Control1[Y Axis]=key(273,274)',
                }
                if gamepad:
                    self.assertFalse([s for s in settings if s.startswith('Input-SDL')])
                else:
                    self.assertLessEqual(keyboard, set(settings))

    def test_layout_keys_do_not_collide_or_trigger_hotkeys(self):
        import n64

        keys = list(n64._BUTTONS.values()) + ['up', 'down', 'left', 'right']
        self.assertEqual(len(keys), len(set(keys)))
        # Mupen's default hotkeys: save slots 0-9, pause, mute, volume, frame
        # advance, speed limiter. Fast forward (f) and Gameshark (g) are unbound.
        hotkeys = set('0123456789pm[]/y')
        self.assertFalse(hotkeys & set(keys))

    def test_failed_publication_leaves_no_partial_rom_or_tempfile(self):
        from n64 import launch

        self.save_dir.mkdir()
        staged = self.save_dir / 'test-game.z64'
        staged.mkdir()
        with self.assertRaises(OSError):
            launch(b'verified', 'test-game', self.save_dir)
        self.assertEqual(list(self.save_dir.iterdir()), [staged])

    def test_staging_replaces_symlink_without_touching_target(self):
        from n64 import launch

        target = self.root / 'unrelated'
        target.write_bytes(b'keep')
        self.save_dir.mkdir()
        staged = self.save_dir / 'test-game.z64'
        support.symlink(self, staged, target)
        self.assertEqual(launch(b'verified', 'test-game', self.save_dir).wait(10), 0)
        self.assertFalse(staged.is_symlink())
        self.assertEqual(staged.read_bytes(), b'verified')
        self.assertEqual(target.read_bytes(), b'keep')

    def test_same_title_relaunch_preserves_state(self):
        from n64 import launch

        for _ in range(2):
            self.assertEqual(launch(b'verified', 'test-game', self.save_dir).wait(10), 0)
        self.assertEqual((self.save_dir / 'runs').read_text(), 'started\nstarted\n')

    def test_game_id_cannot_escape_staging_directory(self):
        from n64 import launch

        for game_id in ('../escape', '-option', '/absolute', 'a/b', '', 'a\\b', 'a\n', 'C:x'):
            with self.subTest(game_id=game_id), self.assertRaisesRegex(ValueError, 'game ID'):
                launch(b'verified', game_id, self.save_dir)
        self.assertFalse(self.save_dir.exists())

    def test_bad_override_does_not_fall_back(self):
        from n64 import launch

        for override in ('mupen64plus', str(self.root), str(self.root / 'missing')):
            with self.subTest(override=override), patch.dict(os.environ, RETRO_POCKET_MUPEN64PLUS=override):
                with patch('n64._INSTALLED_EXECUTABLES', (self.executable,)):
                    with self.assertRaisesRegex(FileNotFoundError, 'RETRO_POCKET_MUPEN64PLUS'):
                        launch(b'verified', 'test-game', self.save_dir)
        self.assertFalse(self.save_dir.exists())

    def test_missing_fixed_install_ignores_path_lookup(self):
        from n64 import launch

        support.decoy(self.root / 'mupen64plus', self.executable)
        with patch.dict(os.environ, support.minimal_env(PATH=self.root), clear=True):
            with patch('n64._INSTALLED_EXECUTABLES', (self.root / 'missing',)):
                with self.assertRaisesRegex(FileNotFoundError, 'install.*mupen64plus.*RETRO_POCKET_MUPEN64PLUS'):
                    launch(b'verified', 'test-game', self.save_dir)
            self.assertFalse(self.save_dir.exists())
            with patch('n64._INSTALLED_EXECUTABLES', (self.root / 'missing', self.executable)):
                self.assertEqual(launch(b'verified', 'test-game', self.save_dir).wait(10), 0)

    def test_child_inherits_both_output_streams(self):
        # Simulate the app worker redirecting its own outputs before launch.
        import sys

        proc = subprocess.run(
            [sys.executable, '-c', 'from n64 import launch; from pathlib import Path; '
             'import sys; sys.exit(launch(b"verified", "test-game", Path(sys.argv[1])).wait(10))',
             str(self.save_dir)], check=True, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(proc.stdout, 'test-game.z64\n')
        self.assertEqual(proc.stderr, 'emulator stderr\n')

    @unittest.skipUnless(WINDOWS, 'the Windows bundle is located through its own folder')
    def test_windows_names_the_bundle_core_plugins_and_video_plugin(self):
        import n64

        bundle = self.root / 'bundle'
        bundle.mkdir()
        for name in ('mupen64plus.dll', 'mupen64plus-video-glide64mk2.dll'):
            (bundle / name).write_bytes(b'')
        program = bundle / 'mupen64plus-ui-console.exe'
        self.assertEqual(n64._bundle_arguments(program), [
            '--plugindir', str(bundle), '--datadir', str(bundle),
            '--corelib', str(bundle / 'mupen64plus.dll'), '--gfx', 'mupen64plus-video-glide64mk2'])
