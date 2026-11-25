import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'handheld_player.py'


class HandheldCLITest(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                              cwd=Path(args[2]).parent, capture_output=True, text=True,
                              env={**os.environ, 'SDL_VIDEODRIVER': 'dummy',
                                   'SDL_AUDIODRIVER': 'dummy'}, timeout=10)

    def test_bad_core_returns_error_and_traceback_on_stderr(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rom, core = root / 'staged.gb', root / 'bad-core.so'
            rom.write_bytes(b'ROM')
            core.write_bytes(b'not a shared library')
            result = self.invoke(rom, core, root / 'saves', 'A title with spaces')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('Traceback (most recent call last)', result.stderr)
        # The error line names the core ("<core>: invalid ELF header" on Linux, "dlopen(<core>, ...)" on macOS).
        errors = [line for line in result.stderr.splitlines() if line.startswith('RETRO_POCKET_ERROR: ')]
        self.assertTrue(errors and str(core) in errors[-1], result.stderr)

    def test_relative_paths_are_rejected(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self.invoke(root / 'staged.gb', 'mgba.so', root / 'saves', 'Title')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('absolute path', result.stderr)


class HandheldSessionTest(unittest.TestCase):
    def test_onscreen_a_press_is_written_to_real_battery_save(self):
        from test_core import gb_rtc_rom, installed_core
        core_path = installed_core()
        if not core_path:
            self.skipTest('Set MGBA_LIBRETRO to the absolute core path')
        import handheld_player

        pg = handheld_player.pg
        original_step = handheld_player.Player.step
        frames = 0

        def step(player, buttons):
            nonlocal frames
            original_step(player, buttons)
            frames += 1
            if frames == 1:
                pg.event.post(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1,
                                             pos=player.pads['a'].center))
            elif frames == 4:
                pg.event.post(pg.event.Event(pg.QUIT))
            elif frames > 4:
                self.fail('QUIT did not stop emulation')

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            'SDL_VIDEODRIVER': 'dummy', 'SDL_AUDIODRIVER': 'dummy',
        }), patch.object(handheld_player.Player, 'step', step):
            root = Path(tmp)
            rom, saves = root / 'staged.gb', root / 'saves'
            rom.write_bytes(gb_rtc_rom())
            self.assertEqual(handheld_player.main([str(rom), core_path, str(saves), 'Battery']), 0)
            self.assertEqual((saves / 'cartridge.sav').read_bytes()[0], 0x5a)

    def test_escape_flushes_battery_before_closing(self):
        import handheld_player
        import pygame as pg

        calls = []

        class TestCore:
            sample_rate = 32768
            fps = 60
            audio = bytearray()

            def run(self, buttons):
                calls.append('frame')
                pg.event.post(pg.event.Event(pg.KEYDOWN, key=pg.K_ESCAPE))
                return 1, 1, b'\xff\x08\x01'

            def save(self):
                calls.append('save')

            def close(self):
                calls.append('close')

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            'SDL_VIDEODRIVER': 'dummy', 'SDL_AUDIODRIVER': 'dummy',
        }), patch('core.Core', return_value=TestCore()) as open_core:
            root = Path(tmp)
            rom, core, saves = root / 'staged.gb', root / 'mgba.so', root / 'saves'
            rom.write_bytes(b'verified by parent')
            status = handheld_player.main([str(rom), str(core), str(saves), 'Title'])
            open_core.assert_called_once_with(b'verified by parent', str(core), saves)

        self.assertEqual(status, 0)
        self.assertEqual(calls, ['frame', 'save', 'close'])
        self.assertFalse(pg.display.get_init())


class SignalSaveTest(unittest.TestCase):
    def test_sigterm_during_play_still_saves_and_closes(self):
        import signal

        import handheld_player

        calls = []

        class TestCore:
            sample_rate = 32768
            fps = 60
            audio = bytearray()

            def run(self, buttons):
                calls.append('frame')
                # Delivered to the Python handler on every platform (on Windows,
                # os.kill(SIGTERM) would end the process without running it).
                signal.raise_signal(signal.SIGTERM)
                return 1, 1, b'\xff\x08\x01'

            def save(self):
                calls.append('save')

            def close(self):
                calls.append('close')

        before = signal.getsignal(signal.SIGTERM)
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
            'SDL_VIDEODRIVER': 'dummy', 'SDL_AUDIODRIVER': 'dummy',
        }), patch('core.Core', return_value=TestCore()):
            rom = Path(tmp) / 'staged.gb'
            rom.write_bytes(b'rom')
            with self.assertRaises(SystemExit) as stopped:
                handheld_player.play(rom, Path(tmp) / 'mgba.so', Path(tmp) / 'saves', 'Title')
        self.assertEqual(stopped.exception.code, 128 + signal.SIGTERM)
        self.assertEqual(calls, ['frame', 'save', 'close'])
        self.assertIs(signal.getsignal(signal.SIGTERM), before)
