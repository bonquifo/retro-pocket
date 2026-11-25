"""Launch real games through Retro Pocket's worker on Windows and capture each emulator's window.

Usage: .venv\\Scripts\\python tests\\smoke_windows.py OUTPUT_DIR [GAME_ID ...]

Each game is started exactly as the Play button starts it (the worker
verifies the dump, links it and launches the emulator), using your ROM
folder, the emulators in emulators\\ and a temporary data folder in
%LOCALAPPDATA% that is removed afterwards (hard links: no extra disk space). Once the game's window appears and has had time to
boot, it is captured to OUTPUT_DIR\\<game>.png and closed: first politely (as
its close button does), then by force if it is still running. The default
games cover every system in your collection.
"""
import ctypes
from ctypes import wintypes as W
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import compat  # noqa: E402
from library import Library, default_rom_dir  # noqa: E402
from session import EmulatorSession, exit_message  # noqa: E402

DEFAULT = ['pokemon-red', 'pokemon-crystal', 'pokemon-emerald', 'pokemon-platinum',
           'n64-super-mario-64', '3ds-x']
BOOT = {'GB': 6, 'GBC': 6, 'GBA': 8, 'NDS': 12, 'N64': 15, '3DS': 30}

user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32 = ctypes.WinDLL('gdi32')
user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.GetWindowRect.argtypes = [W.HWND, ctypes.POINTER(W.RECT)]
user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
user32.GetWindowDC.argtypes = [W.HWND]
user32.GetWindowDC.restype = W.HDC
user32.ReleaseDC.argtypes = [W.HWND, W.HDC]
user32.PrintWindow.argtypes = [W.HWND, W.HDC, W.UINT]
user32.IsWindowVisible.argtypes = [W.HWND]
user32.GetWindow.argtypes = [W.HWND, W.UINT]
user32.GetWindow.restype = W.HWND
user32.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
gdi32.CreateCompatibleDC.argtypes = [W.HDC]
gdi32.CreateCompatibleDC.restype = W.HDC
gdi32.CreateCompatibleBitmap.argtypes = [W.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = W.HBITMAP
gdi32.SelectObject.argtypes = [W.HDC, W.HGDIOBJ]
gdi32.SelectObject.restype = W.HGDIOBJ
gdi32.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, ctypes.c_void_p, ctypes.c_void_p, W.UINT]
gdi32.DeleteObject.argtypes = [W.HGDIOBJ]
gdi32.DeleteDC.argtypes = [W.HDC]
_ENUM = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)


def windows_of(pids):
    found = []

    @_ENUM
    def visit(hwnd, _):
        owner = W.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids and user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4):
            rect = W.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            found.append((hwnd, title.value, rect.right - rect.left, rect.bottom - rect.top))
        return True
    user32.EnumWindows(visit, 0)
    return found


def capture(hwnd, width, height, path):
    """The window's own rendering (PrintWindow, full content), saved as PNG.

    Only the emulator's window is read, never the screen, so nothing else
    on the desktop is recorded. DeSmuME's default DirectDraw output does not
    appear in such captures: its window shows an empty client area.
    """
    import pygame as pg

    screen = user32.GetWindowDC(hwnd)
    memory = gdi32.CreateCompatibleDC(screen)
    bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
    gdi32.SelectObject(memory, bitmap)
    user32.PrintWindow(hwnd, memory, 2)  # PW_RENDERFULLCONTENT: GPU-drawn content too

    class Header(ctypes.Structure):
        _fields_ = [('biSize', W.DWORD), ('biWidth', W.LONG), ('biHeight', W.LONG), ('biPlanes', W.WORD),
                    ('biBitCount', W.WORD), ('biCompression', W.DWORD), ('biSizeImage', W.DWORD),
                    ('biXPelsPerMeter', W.LONG), ('biYPelsPerMeter', W.LONG), ('biClrUsed', W.DWORD),
                    ('biClrImportant', W.DWORD)]
    header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory, bitmap, 0, height, pixels, ctypes.byref(header), 0)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory)
    user32.ReleaseDC(hwnd, screen)
    bgra = pixels.raw
    rgb = bytearray(width * height * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgra[2::4], bgra[1::4], bgra[0::4]
    image = pg.image.frombytes(bytes(rgb), (width, height), 'RGB')
    if width > 1600:
        image = pg.transform.smoothscale(image, (width // 2, height // 2))
    pg.image.save(image, str(path))
    distinct = len(set(bgra[i:i + 3] for i in range(0, len(bgra), 4 * 997)))
    return distinct  # A blank (single-colour) capture has 1.


def run(library, game, output):
    print(f'\n=== {game["id"]} ({game["platform"]}): {game["title"]}')
    session = EmulatorSession.for_game(library, game)
    started = time.monotonic()
    shown = []

    def pids():
        return session.job.pids() if session.job else {session.process.pid}
    while time.monotonic() - started < 90 and session.process.poll() is None:
        shown = [w for w in windows_of(pids()) if w[2] > 200 and w[3] > 150]
        if shown:
            break
        time.sleep(0.25)
    result = {'game': game['id'], 'window': None}
    if shown:
        print(f'window after {time.monotonic() - started:.1f}s: {[(t, w, h) for _, t, w, h in shown]}')
        time.sleep(BOOT[game['platform']])
        alive = session.process.poll() is None
        shown = [w for w in windows_of(pids()) if w[2] > 200 and w[3] > 150] or shown
        hwnd, title, width, height = max(shown, key=lambda w: w[2] * w[3])
        colours = capture(hwnd, width, height, output / f'{game["id"]}.png') if alive else 0
        result.update(window=title, size=(width, height), alive=alive, colours=colours)
        print(f'still running after boot: {alive}; capture: {output / (game["id"] + ".png")} ({colours} colours)')
    else:
        print('no window appeared')
    session.request_stop()  # Politely, like the close button.
    try:
        code = session.process.wait(timeout=15)
        how = 'closed politely'
    except Exception:
        session.request_stop(force=True)
        code = session.process.wait(timeout=15)
        how = 'force closed'
    result.update(exit=code, how=how)
    print(f'{how}; exit {code}; {exit_message(code, session.log) or "clean exit"}')
    tail = session.log.read_text(errors='replace').strip().splitlines()[-6:]
    print('log tail:', *tail, sep='\n  ')
    return result


def main():
    if not compat.WINDOWS:
        print('This smoke test is for Windows; see smoke_real.py for X11.', file=sys.stderr)
        return 2
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # Per-monitor v2: real pixel sizes
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[2:] or DEFAULT
    # Not under %TEMP%: DeSmuME ignores its per-game folder when it runs from there.
    local = Path(os.environ['LOCALAPPDATA'])
    with tempfile.TemporaryDirectory(prefix='RetroPocket-smoke-', dir=local, ignore_cleanup_errors=True) as data:
        library = Library(root=Path(data), rom_dir=default_rom_dir())
        library.scan()
        games = {g['id']: g for g in library.games}
        results = []
        for game_id in wanted:
            if library.found(games[game_id]) is None:
                print(f'\n=== {game_id}: not in the ROM folder, skipped')
                continue
            results.append(run(library, games[game_id], output))
        saves = Path(data) / 'saves'
        print('\nsave folders:')
        for path in sorted(saves.rglob('*')):
            if path.is_file() and path.suffix.lower() not in ('.dll', '.exe', '.nds', '.z64', '.3ds') \
                    and 'plugins' not in path.parts and path.stat().st_size:
                print(f'  {path.relative_to(saves)}  {path.stat().st_size} bytes')
    failed = [r['game'] for r in results if not r.get('alive') or r.get('colours', 0) < 4]
    print('\nRESULT:', 'all games booted and rendered' if not failed else f'problems with {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
