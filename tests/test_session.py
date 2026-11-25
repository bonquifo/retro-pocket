import json
import hashlib
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest

import compat
from library import Library
from session import EmulatorSession, exit_message
import support
from support import WINDOWS


def eventually(check, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return check()


class SessionTest(unittest.TestCase):
    def test_reclaims_only_its_own_abandoned_launch_snapshot(self):
        from emulator_worker import cleanup_stale_snapshots
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('rp-launch-abandoned', 'rp-launch-live', 'session-personal'):
                (root / name).mkdir()
                (root / name / 'disc.iso').write_bytes(b'copy')
            job = EmulatorSession.start([sys.executable, '-c', 'pass'], root / 'launch.log')
            job.process.wait(timeout=10)
            (root / 'rp-launch-abandoned' / '.owner').write_text(str(job.process.pid))
            (root / 'rp-launch-live' / '.owner').write_text(str(compat.launch_owner()))
            unrelated = root / 'unrelated'
            unrelated.mkdir()
            (unrelated / 'keep').write_bytes(b'keep')
            support.directory_link(root / 'rp-launch-link', unrelated)  # A junction on Windows
            cleanup_stale_snapshots(root)
            self.assertFalse((root / 'rp-launch-abandoned').exists())
            self.assertTrue((root / 'session-personal' / 'disc.iso').is_file())
            self.assertTrue((root / 'rp-launch-live' / 'disc.iso').is_file())
            self.assertTrue((unrelated / 'keep').is_file())
            self.assertTrue(compat.is_link(root / 'rp-launch-link'))
            support.remove_link(root / 'rp-launch-link')

    def test_user_can_stop_unresponsive_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'run.log'
            session = EmulatorSession.start([sys.executable, '-c', 'import time; time.sleep(60)'], log)
            try:
                session.request_stop(force=True)
                expected = compat.TERMINATED if WINDOWS else -signal.SIGKILL
                self.assertEqual(session.process.wait(timeout=10), expected)
                self.assertIn('force closed' if WINDOWS else 'SIGKILL', exit_message(expected, log))
            finally:
                if session.process.poll() is None:
                    session.process.kill()
                    session.process.wait(timeout=10)

    def test_force_close_ends_the_whole_game_process_tree(self):
        # The worker starts the emulator; Force close must end both (Windows:
        # the job object; POSIX: the process group).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / 'grandchild.pid'
            script = ('import subprocess, sys, time\n'
                      'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
                      f'open({str(marker)!r}, "w").write(str(child.pid))\n'
                      'time.sleep(60)\n')
            session = EmulatorSession.start([sys.executable, '-c', script], root / 'run.log')
            try:
                self.assertTrue(eventually(lambda: marker.is_file() and marker.read_text()))
                grandchild = int(marker.read_text())
                session.request_stop(force=True)
                session.process.wait(timeout=10)
                self.assertTrue(eventually(lambda: not _running(grandchild)), 'the emulator kept running')
            finally:
                if session.process.poll() is None:
                    session.process.kill()

    @unittest.skipUnless(WINDOWS, 'Windows asks windows to close instead of sending SIGTERM')
    def test_polite_stop_on_windows_closes_the_game_window(self):
        script = ('import os\n'
                  'os.environ["SDL_VIDEODRIVER"] = "windows"\n'
                  'import pygame as pg\n'
                  'pg.display.init()\n'
                  'window = pg.Window("polite stop test", size=(160, 120))\n'
                  'while True:\n'
                  '    for event in pg.event.get():\n'
                  '        if event.type in (pg.QUIT, pg.WINDOWCLOSE):\n'
                  '            raise SystemExit(5)\n'
                  '    pg.time.wait(10)\n')
        with tempfile.TemporaryDirectory() as tmp:
            session = EmulatorSession.start([sys.executable, '-c', script], Path(tmp) / 'run.log')
            try:
                self.assertTrue(eventually(lambda: session.job.close_windows() > 0 or session.process.poll() is not None))
                self.assertEqual(session.process.wait(timeout=10), 5)  # It quit by itself, as asked.
            finally:
                if session.process.poll() is None:
                    session.request_stop(force=True)

    def test_native_crash_is_reported_without_killing_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'run.log'
            if WINDOWS:
                # A real access violation (CPython's own test helper, which also
                # suppresses the crash dialog). ctypes would turn one into OSError.
                crash = 'import faulthandler; faulthandler._read_null()'
                expected, name = 0xC0000005, 'ACCESS_VIOLATION'
            else:
                crash = 'import os, signal; os.kill(os.getpid(), signal.SIGTERM)'
                expected, name = -signal.SIGTERM, 'SIGTERM'
            session = EmulatorSession.start([sys.executable, '-c', crash], log)
            code = session.process.wait(timeout=10)
            self.assertEqual(code, expected)
            self.assertIn(name, exit_message(code, log))
            self.assertIn(str(log), exit_message(code, log))
            self.assertIsNone(exit_message(0, log))

    def test_error_details_are_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'run.log'
            session = EmulatorSession.start([sys.executable, '-c', 'import sys; sys.exit("bad ROM")'], log)
            code = session.process.wait(timeout=10)
            self.assertIn('bad ROM', log.read_text())
            self.assertIn('status 1', exit_message(code, log))

    def test_snapshot_is_hash_checked_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            data = b'a' * (3 * 1024 * 1024 + 19)
            game = dict(id='test', title='Test', year=2000, platform='NDS', variants=[dict(label='Original', size=len(data), sha1=hashlib.sha1(data).hexdigest())])
            catalog = d / 'catalog.json'
            catalog.write_text(json.dumps([game]))
            lib = Library(d / 'data', catalog)
            lib.path(game).parent.mkdir()
            lib.path(game).write_bytes(data)
            stage = d / 'stage.nds'
            lib.stage(game, stage)
            self.assertEqual(stage.read_bytes(), data)
            lib.path(game).write_bytes(b'b' + data[1:])
            with self.assertRaisesRegex(ValueError, 'digest'):
                lib.stage(game, stage)
            self.assertEqual(stage.read_bytes(), data)

    def test_supplement_promotes_only_matching_catalogue_record(self):
        from library import _load_catalogs
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / 'catalog.json').write_text('[]')
            original = dict(id='id', platform='N64', title='Example', year=2000, variants=[], unavailable='not playable')
            promoted = dict(original, variants=[dict(label='US', size=17, sha1='a'*40)])
            del promoted['unavailable']
            (d / 'catalog-unavailable.json').write_text(json.dumps([original]))
            (d / 'catalog-n64.json').write_text(json.dumps([promoted]))
            self.assertEqual(_load_catalogs(d / 'catalog.json', True), [promoted])
            promoted['platform'] = 'NDS'
            (d / 'catalog-n64.json').write_text(json.dumps([promoted]))
            with self.assertRaisesRegex(ValueError, 'platform'):
                _load_catalogs(d / 'catalog.json', True)


def _running(pid):
    if WINDOWS:
        return compat._win.process_alive(pid)
    import os
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # A zombie (killed, not yet reaped) no longer runs.
        return Path(f'/proc/{pid}/stat').read_text().split(') ')[1][0] != 'Z'
    except (OSError, IndexError):
        return True
