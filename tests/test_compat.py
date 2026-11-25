import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import compat
import support
from support import WINDOWS


class CompatTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_lock_is_exclusive_across_processes_and_ends_with_them(self):
        lock = self.root / '.playing.lock'
        hold = ('import sys, time; sys.path.insert(0, sys.argv[2]); import compat\n'
                'f = open(sys.argv[1], "ab"); compat.lock_exclusive(f); print("locked", flush=True); time.sleep(60)')
        holder = subprocess.Popen([sys.executable, '-c', hold, str(lock), str(compat.APP_DIR)],
                                  stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'locked')
            with lock.open('ab') as mine, self.assertRaises(BlockingIOError):
                compat.lock_exclusive(mine)
        finally:
            holder.kill()
            holder.wait(timeout=10)
            holder.stdout.close()
        # Released when its holder exits (Windows releases a killed process's locks shortly after).
        deadline = time.monotonic() + 10
        with lock.open('ab') as mine:
            while True:
                try:
                    compat.lock_exclusive(mine)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.05)

    def test_owner_alive_tells_running_from_finished_processes(self):
        self.assertTrue(compat.owner_alive(compat.launch_owner()))
        finished = subprocess.Popen([sys.executable, '-c', 'pass'], start_new_session=not WINDOWS)
        finished.wait(timeout=10)
        self.assertFalse(compat.owner_alive(finished.pid))

    def test_private_install_links_files_and_replaces_stale_ones(self):
        source = self.root / 'emulator'
        (source / 'plugins').mkdir(parents=True)
        (source / 'emu.exe').write_bytes(b'program')
        (source / 'plugins' / 'video.dll').write_bytes(b'plugin')
        target = self.root / 'game'
        files = [('emu.exe', source / 'emu.exe'), ('plugins/video.dll', source / 'plugins' / 'video.dll')]
        compat.private_install(files, target)
        self.assertTrue(os.path.samefile(target / 'emu.exe', source / 'emu.exe'))
        self.assertTrue(os.path.samefile(target / 'plugins' / 'video.dll', source / 'plugins' / 'video.dll'))
        # An update replaces the file in the emulator folder: the game's copy follows.
        (source / 'emu.exe').unlink()
        (source / 'emu.exe').write_bytes(b'new program')
        compat.private_install(files, target)
        self.assertEqual((target / 'emu.exe').read_bytes(), b'new program')
        self.assertEqual(sorted(p.name for p in target.iterdir()), ['emu.exe', 'plugins'])
        for unsafe in ('../escape.dll', str(self.root / 'absolute.dll')):
            with self.subTest(name=unsafe), self.assertRaisesRegex(ValueError, 'Unsafe'):
                compat.private_install([(unsafe, source / 'emu.exe')], target)
        with self.assertRaisesRegex(ValueError, 'folder of its own'):
            compat.private_install(files * 3, target, limit=5)

    def test_link_or_copy_falls_back_to_a_copy(self):
        from unittest.mock import patch

        source = self.root / 'emu.exe'
        source.write_bytes(b'program')
        with patch('compat.os.link', side_effect=OSError(17, 'not the same device')):
            compat.link_or_copy(source, self.root / 'copy' / 'emu.exe')
        copy = self.root / 'copy' / 'emu.exe'
        self.assertFalse(os.path.samefile(copy, source))
        self.assertEqual(copy.read_bytes(), b'program')

    def test_only_real_programs_are_executable(self):
        program = support.program(self.root / 'emulator', 'pass\n')
        self.assertTrue(compat.is_executable(program))
        self.assertFalse(compat.is_executable(Path(program.name)))  # Relative
        self.assertFalse(compat.is_executable(self.root))
        self.assertFalse(compat.is_executable(self.root / 'missing.exe'))
        script = self.root / 'emulator.bat'
        script.write_text('@echo off\n')
        if not WINDOWS:
            script.chmod(0o600)
        self.assertFalse(compat.is_executable(script))

    def test_exit_reasons_name_windows_exceptions(self):
        if WINDOWS:
            self.assertEqual(compat.exit_reason(0xC0000005), 'ACCESS_VIOLATION, 0xC0000005')
            self.assertEqual(compat.exit_reason(compat.TERMINATED), 'force closed')
            self.assertEqual(compat.exit_reason(0xC0001234), 'Windows exception 0xC0001234')
            self.assertIsNone(compat.exit_reason(1))
        else:
            self.assertIsNone(compat.exit_reason(0xC0000005))

    def test_rotational_and_gamepad_probes_answer_without_errors(self):
        self.assertIsInstance(compat.rotational(self.root), bool)
        self.assertIsInstance(compat.gamepad_connected(), bool)
        self.assertGreaterEqual(compat.system_scale(), 1.0)

    @unittest.skipUnless(WINDOWS, 'junctions are a Windows feature')
    def test_junctions_count_as_links(self):
        target = self.root / 'target'
        target.mkdir()
        support.directory_link(self.root / 'junction', target)
        self.assertTrue(compat.is_link(self.root / 'junction'))
        self.assertFalse(compat.is_link(target))
        self.assertFalse(compat.is_link(self.root / 'missing'))
