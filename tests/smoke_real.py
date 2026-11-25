"""End-to-end verified launch and recovery on a disposable X11 display.

Usage: python tests/smoke_real.py ABS_ROM ABS_CORE, where ABS_ROM is a catalogued GB, GBC or
GBA dump (it is copied into a temporary ROM folder, and that copy is later corrupted).
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App, pg
from library import Library
from smoke_ds import Display, eventually


def xdo(*args):
    return subprocess.check_output(['xdotool', *map(str, args)], text=True, timeout=8)


def window_id(pattern):
    tree = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True, timeout=8)
    match = re.search(r'^\s+(0x[0-9a-f]+) "' + pattern + '"', tree, re.M)
    return str(int(match.group(1), 16)) if match else None


def wait_for_resize(window, size, tick=lambda: None):
    xdo('windowsize', window, *size)
    for _ in range(60):
        tick()
        g = xdo('getwindowgeometry', '--shell', window)
        if f'WIDTH={size[0]}\n' in g and f'HEIGHT={size[1]}\n' in g:
            return
        time.sleep(.03)
    raise AssertionError(f'X11 window {window} did not resize to {size}: {g}')


def main(rom, core_path):
    assert os.environ.get('DISPLAY') and shutil.which('xdotool'), 'Requires X11 and xdotool'
    with tempfile.TemporaryDirectory(prefix='retro-pocket-test-') as tmp:
        rom_dir = Path(tmp) / 'roms'
        rom_dir.mkdir()
        shutil.copyfile(rom, rom_dir / Path(rom).name)
        library = Library(root=Path(tmp) / 'data', rom_dir=rom_dir)
        app = App(library, core_path, show_all=True)
        try:
            catalogue = window_id('Retro Pocket')
            assert catalogue is not None
            def paint_catalogue():
                for event in pg.event.get():
                    app.event(event)
                app.draw()

            while app.scanning:
                paint_catalogue()
                app.update()
                time.sleep(.05)
            app.update()
            game = next(g for g in library.games if library.found(g))
            assert game['platform'] in ('GB', 'GBC', 'GBA'), game['platform']

            for size in ((960, 480), (460, 670), (840, 620)):
                wait_for_resize(catalogue, size, paint_catalogue)
                paint_catalogue()
                assert app.presentation.get_size() == size
                x, y = app.actions['tile:1'][0].center
                r = app.viewport
                xdo('mousemove', '--window', catalogue, r.x + x * r.w // 840, r.y + y * r.h // 620, 'click', 1)
                for _ in range(30):
                    paint_catalogue()
                    if app.index == 1:
                        break
                    time.sleep(.02)
                assert app.index == 1, 'Catalogue mouse hitbox did not follow its resized row'
                app.select(0)
            # C switches to My games, where the search finds the one copied ROM.
            xdo('windowfocus', '--sync', catalogue, 'key', 'c')
            for _ in range(30):
                paint_catalogue()
                if not app.show_all:
                    break
                time.sleep(.02)
            assert not app.show_all, 'C did not switch to My games'
            xdo('key', 'slash')
            paint_catalogue()
            xdo('type', game['title'].split()[-1])
            for _ in range(30):
                paint_catalogue()
                if len(app.visible) == 1:
                    break
                time.sleep(.02)
            assert len(app.visible) == 1 and app.game['id'] == game['id'], app.query
            xdo('key', 'Return')
            paint_catalogue()
            assert not app.searching
            app.play()
            app.update()
            session = app.session
            assert session is not None, app.status
            for _ in range(75):
                win = window_id(re.escape(game['title']) + '.*Retro Pocket')
                if win:
                    break
                if session.process.poll() is not None:
                    raise RuntimeError(session.log.read_text())
                time.sleep(.1)
            else:
                tree = subprocess.run(['xwininfo', '-root', '-tree'], capture_output=True, text=True)
                raise RuntimeError('Handheld player window did not appear: ' + session.log.read_text() + tree.stdout)
            xdo('windowfocus', '--sync', win)
            for size in ((920, 500), (470, 680), (410, 300)):
                wait_for_resize(win, size)
                assert session.process.poll() is None
            # Click the actual, resized Close control rather than sending Escape.
            w, h = size
            scale = min(w / 840, h / 620, 2.5)
            x, y = w - round(98 * scale), round(32 * scale)
            display = Display()
            try:
                def button_painted():
                    image = display.x.XGetImage(display.handle, int(win), x, y - 5, 1, 1, -1, 2)
                    if not image:
                        return False
                    try:
                        return display.x.XGetPixel(image, 0, 0) & 0xffffff == 0x283546
                    finally:
                        display.x.XDestroyImage(image)
                eventually(button_painted, True, 'Resized close button painted')
            finally:
                display.close()
            xdo('mousemove', '--window', win, x, y, 'click', 1)
            assert session.process.wait(timeout=15) == 0, session.log.read_text()
            app.update()
            assert app.session is None and app.status == 'Returned from emulator.'
            path = library.source(app.game)  # The copy in the temporary ROM folder.
            valid = path.read_bytes()
            path.write_bytes(bytes([valid[0] ^ 1]) + valid[1:])
            app.play()
            session = app.session
            assert session is not None
            assert session.process.wait(timeout=15) != 0
            app.update()
            assert app.session is None and 'digest' in app.status, app.status
            assert app.last_log == session.log
            app.draw()
            assert 'Copy log path' in app.actions
            print('Verified resizes and mouse hitboxes on both X11 windows, isolated mGBA launch, and corrupt-cache recovery')
        finally:
            if app.session and app.session.process.poll() is None:
                os.killpg(app.session.process.pid, 15)
                app.session.process.wait(timeout=5)
            pg.quit()


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
