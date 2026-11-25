"""Shared window geometry for Retro Pocket's SDL user interfaces."""
from functools import lru_cache
import os
import time

import compat

if compat.WINDOWS:
    # Draw at the display's real resolution under Windows display scaling
    # (150% and so on) instead of letting Windows stretch a blurry bitmap.
    # Window sizes and mouse positions stay in scaled points, like the
    # pixel/point split on HiDPI Linux and macOS that the UIs already handle.
    # Must be set before SDL's video subsystem starts; user settings win.
    os.environ.setdefault('SDL_WINDOWS_DPI_AWARENESS', 'permonitorv2')
    os.environ.setdefault('SDL_WINDOWS_DPI_SCALING', '1')

import pygame as pg  # noqa: E402


@lru_cache(maxsize=256)
def render_text(font, text, color):
    """Antialiased label, cached: the UIs redraw the same labels every frame.

    Callers only blit the returned surface; they must not draw on it.
    """
    return font.render(text, True, color)


def fit_rect(content, available):
    cw, ch = content
    w, h = available
    if min(cw, ch, w, h) <= 0:
        return pg.Rect(0, 0, 0, 0)
    scale = min(w / cw, h / ch)
    size = (max(1, round(cw * scale)), max(1, round(ch * scale)))
    return pg.Rect((w - size[0]) // 2, (h - size[1]) // 2, *size)


def surface_point(point, pixels, window, bounds):
    """Map SDL window coordinates to pixels, then reject points outside bounds."""
    if min(*pixels, *window) <= 0:
        return None
    px = point[0] * pixels[0] // window[0]
    py = point[1] * pixels[1] // window[1]
    return (px, py) if bounds.collidepoint(px, py) else None


def window_start_size(design, desktop):
    limit = tuple(max(1, int(length * .9)) for length in desktop)
    if all(a <= b for a, b in zip(design, limit)):
        return design
    return fit_rect(design, limit).size


def desktop_size():
    """The main display's size in window coordinates.

    SDL reports display modes in pixels. With Windows DPI scaling on, window
    sizes and positions are in scaled points instead (2560x1440 on a 4K
    display at 150%), so convert.
    """
    width, height = pg.display.get_desktop_sizes()[0]
    if (compat.WINDOWS and os.environ.get('SDL_WINDOWS_DPI_SCALING') == '1'
            and pg.display.get_driver() == 'windows'):
        scale = compat.system_scale()
        width, height = max(1, round(width / scale)), max(1, round(height / scale))
    return width, height


def open_window(title, design):
    # Both windows are drawn in software. On X11, present that surface with
    # shared memory instead of an OpenGL texture: same pixels, no GL driver
    # (Mesa's llvmpipe alone is ~110 MB) and faster large-window presents.
    # Other drivers keep SDL's default; an explicit user setting always wins.
    if pg.display.get_driver() == 'x11':
        os.environ.setdefault('SDL_FRAMEBUFFER_ACCELERATION', '0')
    window = pg.Window(title, size=window_start_size(design, desktop_size()), resizable=True, allow_high_dpi=True)
    window.minimum_size = tuple(min(a, b) for a, b in zip((384, 280), window.size))
    return window


EDGE, GRIP = 6, 18       # Window coordinates: resize border width, bottom-right grip size
DOUBLE_CLICK = 0.4       # Seconds between top-bar clicks that toggle full screen
_RESIZE_CURSORS = {
    'l': 'SIZEWE', 'r': 'SIZEWE', 't': 'SIZENS', 'b': 'SIZENS',
    'tl': 'SIZENWSE', 'br': 'SIZENWSE', 'tr': 'SIZENESW', 'bl': 'SIZENESW',
}


class WindowFrame:
    """Move, resize and full-screen a window from inside it.

    A desktop's window manager already does this with its title bar and
    borders; this also works without one (a bare X server, a kiosk or a VNC
    session): drag the top bar to move, drag an edge or the bottom-right grip
    to resize, and press F11, click the full-screen button or double-click the
    top bar for full screen. Full screen is a borderless window covering the
    display, which needs no window manager either.
    """

    def __init__(self, window):
        self.window = window
        self._drag = None        # (zone, mouse at start, position at start, size at start)
        self._restore = None     # (position, size, borderless) while full screen
        self._cursor = None
        self._last_click = 0.0

    @property
    def fullscreen(self):
        return self._restore is not None

    def toggle_fullscreen(self):
        window = self.window
        self._drag = None
        if self._restore is None:
            self._restore = (window.position, window.size, window.borderless)
            window.borderless = True
            window.position = (0, 0)
            window.size = desktop_size()
        else:
            position, size, borderless = self._restore
            self._restore = None
            window.borderless = borderless
            window.size = size
            window.position = position

    def zone(self, pos):
        """The resize handle under a point in window coordinates, if any."""
        if self.fullscreen:
            return None
        x, y = pos
        w, h = self.window.size
        if x >= w - GRIP and y >= h - GRIP:
            return 'br'
        zone = ('t' if y < EDGE else 'b' if y >= h - EDGE else '') + \
               ('l' if x < EDGE else 'r' if x >= w - EDGE else '')
        return zone or None

    def handle(self, event, draggable=lambda pos: False):
        """Use an event for moving, resizing or full screen; True if it was used.

        ``draggable(pos)`` says whether a window-coordinate point is on the
        top bar (and not on one of its buttons).
        """
        if event.type == pg.KEYDOWN and event.key == pg.K_F11:
            self.toggle_fullscreen()
            return True
        if event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            zone = self.zone(event.pos)
            if zone is None and draggable(event.pos):
                now = time.monotonic()
                if now - self._last_click < DOUBLE_CLICK:
                    self._last_click = 0.0
                    self.toggle_fullscreen()
                    return True
                self._last_click = now
                zone = None if self.fullscreen else 'move'
            if zone is None:
                return False
            # Where the press happened on screen: the pointer may have moved on by the time it is read.
            x, y = self.window.position
            self._drag = (zone, (x + event.pos[0], y + event.pos[1]), (x, y), self.window.size)
            return True
        if event.type == pg.MOUSEMOTION:
            if self._drag is not None:
                self._follow()
                return True
            zone = self.zone(event.pos)
            self._set_cursor(_RESIZE_CURSORS.get(zone, 'ARROW'))
            return False
        if event.type == pg.MOUSEBUTTONUP and event.button == 1 and self._drag is not None:
            self._follow()
            self._drag = None
            return True
        if event.type == getattr(pg, 'WINDOWLEAVE', None) and self._drag is None:
            self._set_cursor('ARROW')
        return False

    def _follow(self):
        # Screen coordinates: the window moves under the pointer while dragging.
        zone, (mx, my), (x, y), (w, h) = self._drag
        gx, gy = pg.mouse.get_pos(desktop=True)
        dx, dy = gx - mx, gy - my
        if zone == 'move':
            self.window.position = (x + dx, y + dy)
            return
        min_w, min_h = self.window.minimum_size
        new_w = max(min_w, w + dx) if 'r' in zone else max(min_w, w - dx) if 'l' in zone else w
        new_h = max(min_h, h + dy) if 'b' in zone else max(min_h, h - dy) if 't' in zone else h
        if (new_w, new_h) != tuple(self.window.size):
            self.window.size = (new_w, new_h)
        if 'l' in zone or 't' in zone:
            self.window.position = (x + w - new_w if 'l' in zone else x, y + h - new_h if 't' in zone else y)

    def _set_cursor(self, name):
        if name == self._cursor:
            return
        self._cursor = name
        try:
            pg.mouse.set_cursor(getattr(pg, 'SYSTEM_CURSOR_' + name))
        except pg.error:
            pass  # No cursor support (dummy video driver).

    def draw_grip(self, surface, color='#4d5f74'):
        """Three diagonal lines in the bottom-right corner, where resizing starts."""
        if self.fullscreen:
            return
        scale = surface.get_width() / max(1, self.window.size[0])
        w, h = surface.get_size()
        for i in (4, 9, 14):
            step = round(i * scale)
            pg.draw.line(surface, color, (w - step, h - 2), (w - 2, h - step), max(1, round(1.5 * scale)))


def draw_fullscreen_icon(surface, rect, color, exit_icon=False):
    """Four corner brackets: pointing out to enter full screen, in to leave it."""
    rect = pg.Rect(rect)
    size = min(rect.w, rect.h)
    half, arm = size * .26, size * .14
    width = max(2, round(size / 18))
    cx, cy = rect.center
    for sx in (-1, 1):
        for sy in (-1, 1):
            corner = (cx + sx * half, cy + sy * half)
            if exit_icon:   # Brackets bend towards the centre.
                corner = (cx + sx * (half - arm), cy + sy * (half - arm))
                points = [(corner[0] + sx * arm, corner[1]), corner, (corner[0], corner[1] + sy * arm)]
            else:
                points = [(corner[0] - sx * arm, corner[1]), corner, (corner[0], corner[1] - sy * arm)]
            pg.draw.lines(surface, color, False, points, width)
