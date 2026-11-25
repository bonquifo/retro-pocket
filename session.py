"""Emulator subprocess supervision and user-facing exit diagnostics."""
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

import compat


@dataclass
class EmulatorSession:
    process: subprocess.Popen
    log: Path
    job: object = None  # Windows: the Job Object holding the game's process tree

    @classmethod
    def start(cls, argv, log):
        log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with log.open('wb') as output:
            if compat.WINDOWS:
                # Its own process group (Ctrl+C in the app's console doesn't reach
                # the game) and no console window of its own.
                process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output,
                                           stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                                           | subprocess.CREATE_NO_WINDOW)
            else:
                process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=output,
                                           stderr=subprocess.STDOUT, start_new_session=True)
        job = None
        if compat.WINDOWS:
            try:
                job = compat.Job(process)
            except OSError as exc:  # Force close then ends the tree with taskkill instead.
                print(f'Could not track the emulator processes: {exc}', file=sys.stderr)
        return cls(process, log, job)

    @classmethod
    def for_game(cls, library, game, core_path=None):
        root = library.root.resolve()
        category = root / 'logs' / game['id']
        category.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix='launch-', suffix='.log', dir=category, delete=False) as log:
            path = Path(log.name)
        script = Path(__file__).resolve().with_name('emulator_worker.py')
        argv = [sys.executable, '-u', str(script), '--data-dir', str(root), '--', game['id']]
        if core_path:
            argv[3:3] = ['--core', core_path]
        if getattr(library, 'rom_dir', None) is not None:
            argv[3:3] = ['--rom-dir', str(Path(library.rom_dir).resolve())]
        return cls.start(argv, path)

    def request_stop(self, force=False):
        if self.process.poll() is not None:
            return
        if compat.WINDOWS:
            if force:
                if self.job is not None:
                    self.job.terminate()
                else:
                    compat.kill_tree(self.process.pid)
            elif self.job is not None:
                self.job.close_windows()  # Like the close button: the emulator saves and exits.
            return
        try:
            os.killpg(self.process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass  # The emulator may have exited between poll and signal.


def exit_message(code, log):
    if not code:
        return None
    if code < 0:
        try:
            reason = signal.Signals(-code).name
        except ValueError:
            reason = f'signal {-code}'
    else:
        reason = compat.exit_reason(code) or f'status {code}'
    try:
        with log.open('rb') as src:
            src.seek(max(0, log.stat().st_size - 8192))
            tail = src.read(8192).decode('utf-8', errors='replace')
        details = [s.partition('RETRO_POCKET_ERROR: ')[2].strip() for s in tail.splitlines()
                   if s.startswith('RETRO_POCKET_ERROR: ')]
    except OSError:
        details = []
    info = f' — {details[-1][:240]}' if details else ''
    return f'Emulator exited ({reason}){info}. Log: {log}'
