"""mGBA child entry point. The caller owns ROM verification and process monitoring."""

import argparse
import faulthandler
import os
from pathlib import Path
import signal
import sys
import time
import traceback

if __name__ == '__main__' and sys.stderr is not None:
    # Register before Pygame so its crash handler doesn't mask the original signal.
    faulthandler.enable()

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import pygame as pg

from controls import KEYS, MOUSE, active_buttons, pad_rects
from viewport import WindowFrame, draw_fullscreen_icon, fit_rect, open_window, render_text, surface_point

BG, SURFACE = '#121820', '#283546'
INK, MUTED, ACCENT, DARK = '#f2f6fc', '#bac9da', '#a9ebad', '#123323'
W, H = 840, 620
EXIT_RECT = (670, 12, 144, 40)
SAVE_INTERVAL = 10
HELP = 'Arrows: D-pad  •  X/Z: A/B  •  Q/W: L/R  •  Enter: Start  •  Right Shift: Select'
HELP_NO_SHOULDERS = 'Arrows: D-pad  •  X/Z: A/B  •  Enter: Start  •  Right Shift: Select'
NO_SHOULDER_PLATFORMS = {'GB', 'GBC'}  # The original Game Boy has no L or R button.
# Triangle points for the D-pad labels, as fractions of the button's half-size.
# The default pygame font has no arrow glyphs, so the arrows are drawn.
ARROWS = {
    'up': ((0, -.45), (-.5, .3), (.5, .3)),
    'down': ((0, .45), (-.5, -.3), (.5, -.3)),
    'left': ((-.45, 0), (.3, -.5), (.3, .5)),
    'right': ((.45, 0), (-.3, -.5), (-.3, .5)),
}


class Player:
    def __init__(self, core, title, shoulders=True):
        self.core = core
        self.title = title
        self.shoulders = shoulders
        self.help = HELP if shoulders else HELP_NO_SHOULDERS
        self.held_keys = set()
        self.held_mouse = {}
        self.frame = None
        self.next_save = time.monotonic() + SAVE_INTERVAL
        pg.display.init()
        pg.font.init()
        self.window = open_window(f'{title} — Retro Pocket', (W, H))
        self.window_frame = WindowFrame(self.window)
        self.layout_size = None
        self.refresh_layout()
        self.channel = None
        self.audio_status = self.save_status = ''
        try:
            pg.mixer.init(frequency=round(core.sample_rate), size=-16, channels=2, buffer=512)
            self.channel = pg.mixer.Channel(0)
        except pg.error:
            self.audio_status = 'Audio unavailable; playing without sound.'

    def refresh_layout(self):
        self.screen = self.window.get_surface()
        width, height = self.screen.get_size()
        if self.layout_size == (width, height):
            return
        self.layout_size = (width, height)
        scale = min(width / W, height / H, 2.5)
        def scaled(value):
            return max(1, round(value * scale))

        margin = scaled(28)
        self.area = pg.Rect(margin, scaled(60), max(0, width - 2 * margin),
                            max(0, height - scaled(229)))
        self.picture = pg.Rect(0, 0, 0, 0)
        self.exit_rect = pg.Rect(width - scaled(W - EXIT_RECT[0]), scaled(12), scaled(144), scaled(40))
        self.pads = {button: pg.Rect(width // 2 + round((x - W // 2) * scale),
                                     height - scaled(H - y), scaled(w), scaled(h))
                     for button, (x, y, w, h) in pad_rects(W, H).items()
                     if self.shoulders or button not in ('l', 'r')}
        self.fullscreen_rect = pg.Rect(self.exit_rect.left - scaled(50), scaled(12), scaled(40), scaled(40))
        self.title_rect = (margin, scaled(22), max(0, self.fullscreen_rect.left - 2 * margin), scaled(36))
        self.status_rect = (margin, height - scaled(30), max(0, width - 2 * margin), scaled(24))
        self.fonts = {size: pg.font.Font(None, scaled(size)) for size in (20, 23, 29)}

    def draggable(self, pos):
        """The top bar, away from its buttons, moves the window."""
        self.refresh_layout()
        point = surface_point(pos, self.screen.get_size(), self.window.size, self.screen.get_rect())
        return (point is not None and point[1] < self.area.top
                and not self.exit_rect.collidepoint(point) and not self.fullscreen_rect.collidepoint(point))

    def handle_event(self, event):
        """Return false when the window should close."""
        if event.type in (pg.QUIT, pg.WINDOWCLOSE):
            return False
        if self.window_frame.handle(event, self.draggable):
            return True
        if event.type == pg.WINDOWFOCUSLOST:
            self.held_keys.clear()
            self.held_mouse.clear()
        elif event.type == pg.KEYDOWN:
            if event.key == pg.K_ESCAPE:
                return False
            key = pg.key.name(event.key)
            if key in KEYS:
                self.held_keys.add(key)
        elif event.type == pg.KEYUP:
            self.held_keys.discard(pg.key.name(event.key))
        elif event.type == pg.MOUSEBUTTONDOWN:
            if event.button == 1:
                self.refresh_layout()
                point = surface_point(event.pos, self.screen.get_size(), self.window.size, self.screen.get_rect())
                if point is None:
                    return True
                if self.exit_rect.collidepoint(point):
                    return False
                if self.fullscreen_rect.collidepoint(point):
                    self.window_frame.toggle_fullscreen()
                    return True
                for button, rect in self.pads.items():
                    if rect.collidepoint(point):
                        self.held_mouse[1] = button
                        break
            elif event.button in MOUSE:
                self.held_mouse[event.button] = MOUSE[event.button]
        elif event.type == pg.MOUSEBUTTONUP:
            self.held_mouse.pop(event.button, None)
        return True

    def draw(self, buttons):
        self.refresh_layout()
        self.screen.fill(BG)
        self.text(self.title, self.title_rect, 29, INK)
        self.draw_button(self.exit_rect, 'Close · Esc', False, size=23)
        pg.draw.rect(self.screen, SURFACE, self.fullscreen_rect, border_radius=10)
        draw_fullscreen_icon(self.screen, self.fullscreen_rect, INK, exit_icon=self.window_frame.fullscreen)
        pg.draw.rect(self.screen, '#080b10', self.area, border_radius=10)
        if self.frame is not None:
            width, height, rgb = self.frame
            self.picture = fit_rect((width, height), self.area.size).move(self.area.topleft)
            if self.picture.w and self.picture.h:
                image = pg.image.frombytes(rgb, (width, height), 'RGB')
                self.screen.blit(pg.transform.scale(image, self.picture.size), self.picture)
        for button, rect in self.pads.items():
            if button in ARROWS:
                self.draw_arrow(rect, ARROWS[button], button in buttons)
            else:
                self.draw_button(rect, button.upper(), button in buttons)
        self.text(self.save_status or self.audio_status or self.help, self.status_rect, 20, MUTED)
        self.window_frame.draw_grip(self.screen)
        self.window.flip()

    def text(self, text, rect, size, color):
        label = render_text(self.fonts[size], text, color)
        self.screen.blit(label, rect[:2], (0, 0, rect[2], rect[3]))

    def draw_button(self, rect, text, pressed, size=20):
        pg.draw.rect(self.screen, ACCENT if pressed else SURFACE, rect, border_radius=10)
        label = render_text(self.fonts[size], text, DARK if pressed else INK)
        self.screen.blit(label, label.get_rect(center=rect.center))

    def draw_arrow(self, rect, points, pressed):
        pg.draw.rect(self.screen, ACCENT if pressed else SURFACE, rect, border_radius=10)
        half = min(rect.w, rect.h) * .4
        pg.draw.polygon(self.screen, DARK if pressed else INK,
                        [(rect.centerx + x * half, rect.centery + y * half) for x, y in points])

    def step(self, buttons):
        frame = self.core.run(buttons)
        if frame is not None:
            self.frame = frame
        if self.core.audio and self.channel is not None and self.channel.get_queue() is None:
            chunk = pg.mixer.Sound(buffer=bytes(self.core.audio))
            if self.channel.get_busy():
                self.channel.queue(chunk)
            else:
                self.channel.play(chunk)
        self.core.audio.clear()

        now = time.monotonic()
        if now >= self.next_save:
            self.next_save = now + SAVE_INTERVAL
            try:
                self.core.save()
                self.save_status = ''
            except OSError as exc:
                self.save_status = f'Could not save: {exc}'
                traceback.print_exc()

    def run(self):
        clock = pg.time.Clock()
        fps = round(self.core.fps)
        while True:
            for event in pg.event.get():
                if not self.handle_event(event):
                    return
            buttons = active_buttons(self.held_keys, self.held_mouse)
            self.step(buttons)
            self.draw(buttons)
            clock.tick(fps)


def absolute_path(value):
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError('expected an absolute path')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Play a staged ROM in a separate mGBA window')
    parser.add_argument('rom', metavar='ABS_STAGED_ROM', type=absolute_path)
    parser.add_argument('core', metavar='ABS_CORE', type=absolute_path)
    parser.add_argument('save_dir', metavar='ABS_SAVEDIR', type=absolute_path)
    parser.add_argument('title', metavar='TITLE')
    parser.add_argument('--platform', help='catalogue platform (GB/GBC hide the L and R buttons)')
    args = parser.parse_args(argv)
    try:
        play(args.rom, args.core, args.save_dir, args.title,
             shoulders=args.platform not in NO_SHOULDER_PLATFORMS)
    except Exception as exc:
        traceback.print_exc()
        print(f'RETRO_POCKET_ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


def _exit_on_signal(signum, frame):
    raise SystemExit(128 + signum)  # Unwinds through play(), which saves.


# Logout, a hangup, a polite kill or (Windows) Ctrl+Break. Windows has no
# SIGHUP; closing the window there, even when asked by Retro Pocket, is a
# normal quit that also saves.
_STOP_SIGNALS = tuple(getattr(signal, name) for name in ('SIGTERM', 'SIGHUP', 'SIGBREAK') if hasattr(signal, name))


def play(rom_path, core_path, save_dir, title, shoulders=True):
    from core import Core

    core = Core(rom_path.read_bytes(), str(core_path), save_dir)
    # Logout, shutdown or a polite kill must not drop up to SAVE_INTERVAL
    # seconds of progress. Force close (SIGKILL, or ending the process tree on Windows) still can.
    previous = {s: signal.signal(s, _exit_on_signal) for s in _STOP_SIGNALS}
    try:
        try:
            Player(core, title, shoulders).run()
        finally:
            core.save()
    finally:
        try:
            for number, handler in previous.items():
                signal.signal(number, handler)
            core.close()
        finally:
            render_text.cache_clear()
            pg.quit()


if __name__ == '__main__':
    raise SystemExit(main())
