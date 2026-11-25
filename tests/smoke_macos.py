"""Start real games through Retro Pocket's worker on macOS and check each emulator opens a window.

Usage:
    .venv/bin/python tests/smoke_macos.py [GAME_ID ...]           # this checkout (after setup.command)
    .venv/bin/python tests/smoke_macos.py --app "/Applications/Retro Pocket (Intel).app" [GAME_ID ...]

Each game starts exactly as the Play button starts it (the worker verifies
the dump, links it and launches the emulator), using a temporary data folder
that is removed afterwards. With --app, the test runs inside that app's own
Python with its code and emulators: on an Apple Silicon Mac, the Intel app
runs under Rosetta. ROMs come from --roms, $RETRO_POCKET_ROMS, ~/Retro Pocket/roms
or this checkout's roms folder. Emulator windows open while it runs.
"""
import argparse
import ctypes
import ctypes.util
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

REPO = Path(__file__).resolve().parents[1]
CODE = Path(os.environ.get('RETRO_POCKET_SMOKE_CODE', REPO))
sys.path.insert(0, str(CODE))
sys.path.insert(1, str(REPO / 'tools'))

DEFAULT = ['pokemon-red', 'pokemon-crystal', 'pokemon-emerald', 'pokemon-platinum',
           'n64-super-mario-64', '3ds-x']
BOOT = {'GB': 6, 'GBC': 6, 'GBA': 8, 'NDS': 15, 'N64': 20, '3DS': 40}


def reexec_in_app(app: Path):
    """Run this script again with the app's own Python, code and emulators."""
    contents = app.resolve() / 'Contents'
    python = contents / 'MacOS' / 'python3.12'
    if not python.is_file():
        sys.exit(f'{app} is not a Retro Pocket app (no Contents/MacOS/python3.12)')
    resources = contents / 'Resources'
    env = dict(os.environ, PYTHONHOME=str(resources / 'python'), PYTHONNOUSERSITE='1',
               PYTHONDONTWRITEBYTECODE='1', RETRO_POCKET_SMOKE_CODE=str(resources / 'app'),
               SSL_CERT_FILE=str(resources / 'python/lib/python3.12/site-packages/certifi/cacert.pem'))
    os.execve(str(python), [str(python), __file__, *sys.argv[1:]], env)


def descendants(pid):
    rows = subprocess.run(['/bin/ps', '-A', '-o', 'pid=,ppid=,comm='], capture_output=True, text=True).stdout
    children, names = {}, {}
    for row in rows.splitlines():
        parts = row.split(None, 2)
        if len(parts) == 3:
            children.setdefault(int(parts[1]), []).append(int(parts[0]))
            names[int(parts[0])] = parts[2]
    found, stack = {}, [pid]
    while stack:
        current = stack.pop()
        found[current] = names.get(current, '?')
        stack.extend(children.get(current, []))
    return found


def windows_of(pids):
    """On-screen windows (owner PID, width, height) via CoreGraphics; needs no permission."""
    try:
        cg = ctypes.CDLL(ctypes.util.find_library('CoreGraphics'))
        cf = ctypes.CDLL(ctypes.util.find_library('CoreFoundation'))
    except (OSError, TypeError):
        return None
    void = ctypes.c_void_p
    cg.CGWindowListCopyWindowInfo.restype = void
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [void]
    cf.CFArrayGetValueAtIndex.restype = void
    cf.CFArrayGetValueAtIndex.argtypes = [void, ctypes.c_long]
    cf.CFDictionaryGetValue.restype = void
    cf.CFDictionaryGetValue.argtypes = [void, void]
    cf.CFStringCreateWithCString.restype = void
    cf.CFStringCreateWithCString.argtypes = [void, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFNumberGetValue.argtypes = [void, ctypes.c_int, void]
    cf.CFRelease.argtypes = [void]

    def key(name):
        return cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)  # UTF-8

    def number(dictionary, name, kind=13, ctype=ctypes.c_double):  # kCFNumberDoubleType
        value = cf.CFDictionaryGetValue(dictionary, key(name))
        result = ctype()
        if value:
            cf.CFNumberGetValue(value, kind, ctypes.byref(result))
        return result.value

    windows = cg.CGWindowListCopyWindowInfo(1, 0)  # On screen only
    found = []
    for index in range(cf.CFArrayGetCount(windows)):
        info = cf.CFArrayGetValueAtIndex(windows, index)
        owner = int(number(info, 'kCGWindowOwnerPID', 3, ctypes.c_int32))  # kCFNumberSInt32Type
        if owner in pids:
            bounds = cf.CFDictionaryGetValue(info, key('kCGWindowBounds'))
            width, height = number(bounds, 'Width'), number(bounds, 'Height')
            if width > 150 and height > 150:
                found.append((owner, int(width), int(height)))
    cf.CFRelease(windows)
    return found


def run(library, game):
    from session import EmulatorSession, exit_message

    print(f'\n=== {game["id"]} ({game["platform"]}): {game["title"]}')
    session = EmulatorSession.for_game(library, game)
    started = time.monotonic()
    shown = []
    while time.monotonic() - started < 120 and session.process.poll() is None:
        processes = descendants(session.process.pid)
        shown = windows_of(set(processes))
        if shown is None or shown:
            break
        time.sleep(0.5)
    if shown:
        print(f'window after {time.monotonic() - started:.1f}s: {shown}')
    time.sleep(BOOT[game['platform']])
    processes = descendants(session.process.pid)
    alive = session.process.poll() is None
    print(f'running after boot: {alive}; processes: {sorted(set(processes.values()))}')
    session.request_stop()  # SIGTERM to the game's process group
    try:
        code = session.process.wait(timeout=20)
        how = 'stopped politely'
    except subprocess.TimeoutExpired:
        session.request_stop(force=True)
        code = session.process.wait(timeout=20)
        how = 'force closed'
    print(f'{how}; exit {code}; {exit_message(code, session.log) or "clean exit"}')
    tail = session.log.read_text(errors='replace').strip().splitlines()[-8:]
    print('log tail:', *tail, sep='\n  ')
    return alive and (shown is None or bool(shown))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--app', type=Path, help='test this Retro Pocket .app instead of the checkout')
    parser.add_argument('--roms', type=Path, help='folder of game dumps')
    parser.add_argument('games', nargs='*', default=DEFAULT)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        sys.exit('This smoke test is for macOS (see smoke_windows.py and smoke_real.py).')
    if args.app and 'RETRO_POCKET_SMOKE_CODE' not in os.environ:
        reexec_in_app(args.app)

    import compat
    from library import Library
    import install_emulators

    translated = subprocess.run(['/usr/sbin/sysctl', '-n', 'sysctl.proc_translated'],
                                capture_output=True, text=True).stdout.strip() == '1'
    print(f'Python {platform.python_version()} running as {platform.machine()}'
          f'{" under Rosetta" if translated else ""}; code: {CODE}')
    for name in ('mgba/mgba_libretro.dylib', 'melonds/melonDS.app/Contents/MacOS/melonDS',
                 'ares/ares.app/Contents/MacOS/ares', 'azahar/Azahar.app/Contents/MacOS/azahar'):
        path = compat.EMULATORS / name
        print(f'  {name}: {sorted(install_emulators.architectures(path)) if path.is_file() else "MISSING"}')

    roms = args.roms or (Path(os.environ['RETRO_POCKET_ROMS']) if os.environ.get('RETRO_POCKET_ROMS') else None)
    if roms is None:
        home = Path.home() / 'Retro Pocket' / 'roms'
        roms = home if home.is_dir() and any(home.rglob('*.*')) else REPO / 'roms'
    print(f'ROM folder: {roms}')
    results = {}
    with tempfile.TemporaryDirectory(prefix='RetroPocket-smoke-') as data:
        library = Library(root=Path(data), rom_dir=roms)
        found = library.scan()
        print(f'{len(found)} games found in the ROM folder')
        games = {g['id']: g for g in library.games}
        for game_id in args.games:
            if game_id not in found:
                print(f'\n=== {game_id}: not in the ROM folder, skipped')
                continue
            results[game_id] = run(library, games[game_id])
        print('\nfiles written in the save folders:')
        for path in sorted((Path(data) / 'saves').rglob('*')):
            if path.is_file() and not path.is_symlink() and '.app/' not in str(path) and path.suffix not in (
                    '.nds', '.z64', '.3ds', '.gb', '.gbc', '.gba') and path.stat().st_size:
                print(f'  {path.relative_to(Path(data) / "saves")}  {path.stat().st_size} bytes')
    failed = [game for game, ok in results.items() if not ok]
    print('\nRESULT:', f'problems with {failed}' if failed else f'all {len(results)} games started and kept running')
    return 1 if failed or not results else 0


if __name__ == '__main__':
    raise SystemExit(main())
