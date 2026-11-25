"""Operating-system differences, kept in one place: Windows and POSIX (Linux).

Everything else imports these helpers instead of testing the platform itself.
"""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

WINDOWS = sys.platform == 'win32'
APP_DIR = Path(__file__).resolve().parent
# Where tools/setup_windows.py installs emulators (and the mGBA core) on Windows.
EMULATORS = APP_DIR / 'emulators'

# Exit code given to every process of a game when the user confirms Force close
# on Windows (DBG_TERMINATE_PROCESS). POSIX uses SIGKILL instead.
TERMINATED = 0x40010004
# Windows exception codes a crashed emulator exits with (NTSTATUS values).
_EXCEPTIONS = {
    0xC0000005: 'ACCESS_VIOLATION', 0xC000001D: 'ILLEGAL_INSTRUCTION',
    0xC0000017: 'NO_MEMORY', 0xC0000094: 'INTEGER_DIVIDE_BY_ZERO', 0xC00000FD: 'STACK_OVERFLOW',
    0xC0000135: 'DLL_NOT_FOUND', 0xC0000139: 'ENTRYPOINT_NOT_FOUND', 0xC0000142: 'DLL_INIT_FAILED',
    0xC000013A: 'CONTROL_C_EXIT', 0xC0000374: 'HEAP_CORRUPTION', 0xC0000409: 'STACK_BUFFER_OVERRUN',
    0xC0000420: 'ASSERTION_FAILURE', 0x80000003: 'BREAKPOINT',
}


def program_files():
    """Fixed Windows install roots (never PATH): Program Files and the per-user Programs folder."""
    roots = [os.environ.get(name) for name in ('ProgramFiles', 'ProgramW6432', 'ProgramFiles(x86)')]
    local = os.environ.get('LOCALAPPDATA')
    if local:
        roots.append(str(Path(local) / 'Programs'))
    return tuple(dict.fromkeys(Path(root) for root in roots if root and Path(root).is_absolute()))


def is_executable(path) -> bool:
    """An absolute path to a program this platform can start directly."""
    path = Path(path)
    if not path.is_absolute() or not path.is_file():
        return False
    if WINDOWS:
        # CreateProcess starts .exe images directly. A .bat or .cmd file would
        # go through cmd.exe, which re-parses arguments such as ROM paths.
        return path.suffix.lower() == '.exe'
    return os.access(path, os.X_OK)


def exit_reason(code):
    """A name for a Windows exception or force-close exit code, else None."""
    if not WINDOWS or code is None:
        return None
    code &= 0xFFFFFFFF
    if code == TERMINATED:
        return 'force closed'
    if code in _EXCEPTIONS:
        return f'{_EXCEPTIONS[code]}, 0x{code:08X}'
    if code >= 0xC0000000:
        return f'Windows exception 0x{code:08X}'
    return None


def _usable(stream):
    try:
        stream.flush()
        stream.fileno()
        return True
    except (AttributeError, OSError, ValueError):
        return False


def popen(argv, **kwargs) -> subprocess.Popen:
    """Start a child that is part of the game: on Windows, with no console window.

    The worker, the integrated player and the emulators run without a
    console, so a console program (Python, Mupen64Plus) would otherwise open
    a new console window, and its output would never reach the launch log.
    Standard output and error are therefore passed on explicitly.
    """
    if WINDOWS:
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
        kwargs.setdefault('stdin', subprocess.DEVNULL)
        for name, stream in (('stdout', sys.stdout), ('stderr', sys.stderr)):
            if name not in kwargs and _usable(stream):
                kwargs[name] = stream
    return subprocess.Popen(argv, **kwargs)


def link_or_copy(source: Path, target: Path) -> None:
    """Publish ``source`` at ``target`` as a hard link (a copy across volumes).

    Unchanged targets are left alone; a stale file or symlink is replaced,
    never written through.
    """
    try:
        if os.path.samefile(source, target):
            return
        theirs, ours = source.stat(), target.lstat()
        if not target.is_symlink() and (theirs.st_size, theirs.st_mtime_ns) == (ours.st_size, ours.st_mtime_ns):
            return  # A copy made earlier (copy2 keeps the modification time).
    except FileNotFoundError:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f'.{target.name}.{os.getpid()}.link')
    temporary.unlink(missing_ok=True)
    try:
        try:
            os.link(source, temporary)
        except OSError:
            shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def private_install(files, target: Path, limit=1000) -> None:
    """Give a game its own portable copy of an emulator, made of hard links.

    ``files`` are (relative name, source path) pairs. Windows emulators keep
    their settings next to their executable (portable mode), so each game
    runs a linked copy whose folder holds that game's own settings and saves.
    Links cost no disk space; files are only copied when the data directory
    is on another drive.
    """
    files = list(files)
    if len(files) > limit:
        raise ValueError(f'{target.name}: the emulator folder holds {len(files)} files; '
                         'install the emulator into a folder of its own')
    for relative, source in files:
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ValueError(f'Unsafe emulator file name: {relative}')
        link_or_copy(Path(source), target / relative)


def is_link(path: Path) -> bool:
    """A symlink, or on Windows a directory junction: both lead outside the tree."""
    if Path(path).is_symlink():
        return True
    if WINDOWS:
        try:
            return os.lstat(path).st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
        except OSError:
            return False
    return False


# ----- Processes ------------------------------------------------------------

def launch_owner() -> int:
    """What a launch snapshot records as its owner: the process group, or the worker's PID on Windows."""
    return os.getpid() if WINDOWS else os.getpgrp()


def owner_alive(owner: int) -> bool:
    """Whether the process group (Windows: process) that made a launch snapshot still runs."""
    if WINDOWS:
        return _win.process_alive(owner)
    try:
        os.killpg(owner, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Job:
    """A Windows Job Object: the game's whole process tree, like a POSIX process group.

    Processes started by a process in the job join it, so the worker, the
    integrated player and the emulator can be closed together. Closing the
    handle does not end them; closing the library leaves the game running.
    """

    def __init__(self, process: subprocess.Popen):
        self.handle = _win.create_job()
        self.process = process
        try:
            _win.assign(self.handle, process)
        except OSError:
            _win.close(self.handle)
            self.handle = None
            raise

    def pids(self):
        return _win.job_pids(self.handle) if self.handle else {self.process.pid}

    def close_windows(self):
        """Ask every window of the game to close, as clicking its close button does."""
        return _win.close_windows(self.pids())

    def terminate(self):
        _win.terminate_job(self.handle, TERMINATED)

    def close(self):
        if self.handle:
            _win.close(self.handle)
            self.handle = None

    __del__ = close


def kill_tree(pid: int) -> None:
    """Fallback when a process could not join a job: end it and its descendants."""
    system = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'taskkill.exe'
    subprocess.run([str(system), '/F', '/T', '/PID', str(pid)], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
                   creationflags=subprocess.CREATE_NO_WINDOW)


# ----- Files ----------------------------------------------------------------

def lock_exclusive(file) -> None:
    """Hold an exclusive lock on an open file; BlockingIOError if another process holds it.

    The lock ends when the file is closed or the process exits.
    """
    if WINDOWS:
        import msvcrt
        file.seek(0)
        try:
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise BlockingIOError(*exc.args) from None
    else:
        import fcntl
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


def rotational(path) -> bool:
    """True if ``path`` is on a spinning disk; False if it is solid state or unknown."""
    if WINDOWS:
        return _win.seek_penalty(path)
    try:
        device = os.stat(path).st_dev
        base = Path(f'/sys/dev/block/{os.major(device)}:{os.minor(device)}')
        for queue in (base / 'queue' / 'rotational', base.parent / 'queue' / 'rotational',
                      base.resolve().parent / 'queue' / 'rotational'):
            if queue.is_file():
                return queue.read_text().strip() == '1'
    except (AttributeError, OSError, ValueError):
        pass
    return False


def gamepad_connected() -> bool:
    """Whether a game controller is plugged in (Windows: joystick API; Linux: evdev)."""
    if WINDOWS:
        return _win.joystick_connected()
    try:
        return any(Path('/dev/input/by-id').glob('*-event-joystick'))
    except OSError:
        return False


def system_scale() -> float:
    """Windows display scaling (1.5 at 150%); 1.0 elsewhere or when unknown."""
    if not WINDOWS:
        return 1.0
    return _win.system_scale()


if WINDOWS:
    import _win32 as _win  # noqa: E402  (ctypes bindings, Windows only)
