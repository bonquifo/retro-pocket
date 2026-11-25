#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import sys
import threading
import time
import unicodedata

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
import pygame as pg

import compat
import covers
from core import locate_core  # noqa: F401  (re-exported for callers)
from library import DEFAULT_SERIES
from session import EmulatorSession, exit_message
from viewport import WindowFrame, draw_fullscreen_icon, fit_rect, open_window, render_text, surface_point

BG, CARD, SURFACE = '#121820', '#1c2632', '#283546'
INK, MUTED, ACCENT, DARK = '#f2f6fc', '#bac9da', '#a9ebad', '#123323'
W, H = 840, 620
OPENING = 'Opening emulator in a separate window…'
LOADING = 'Loading your games…'
PLAYING_AFTER = 4  # Seconds; a 3DS game takes a few seconds to check before its window opens.

# Cover grid (left card) and details (right card), in logical pixels.
GRID_CARD = pg.Rect(28, 112, 520, 460)
GRID_VIEW = pg.Rect(40, 122, 496, 414)     # Scrolling area inside the card
DETAIL_CARD = pg.Rect(560, 112, 252, 460)
DX, DW = 574, 224                           # Detail text column
COLS, TILE_W, COVER_H, CAPTION_H = 4, 112, 112, 22
TILE_H = COVER_H + CAPTION_H
GAP_X, GAP_Y, HEADER_H, SECTION_GAP = 16, 12, 28, 18
WHEEL_STEP = 60
# Header: title and search field on the first row, tabs and the view switch below.
SEARCH_RECT = pg.Rect(512, 20, 254, 38)
FULLSCREEN_RECT = pg.Rect(774, 20, 38, 38)
TABS_Y = 72
HEADER_BOTTOM = GRID_CARD.y - 6           # Dragging here moves the window
FIELD, FIELD_EDGE, HINT = '#1a2430', '#33465a', '#7f91a6'
DETAIL_COVER = (132, 150)


def series(game):
    return game.get('series', DEFAULT_SERIES)


def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c))


class App:
    def __init__(self, library, core_path=None, *, show_all=False, download_covers=False):
        self.library, self.core_path = library, core_path
        pg.display.init()
        pg.font.init()
        covers.clear_caches()
        self.window = open_window('Retro Pocket', (W, H))
        self.window_frame = WindowFrame(self.window)
        self.screen = pg.Surface((W, H))
        self.presentation = self.window.get_surface()
        self.viewport = fit_rect((W, H), self.presentation.get_size())
        self.fonts = {n: pg.font.Font(None, n) for n in (20, 23, 29, 40)}
        self.index = self.scroll = 0
        self.searching, self.query, self.session = False, '', None
        # Categories in catalogue order; the Pokémon catalogue loads first.
        self.categories = list(dict.fromkeys(series(g) for g in library.games)) or [DEFAULT_SERIES]
        self.category = self.categories[0]
        # By default only games the owner has (found in the ROM folder);
        # C switches to the full catalogue.
        self.show_all = show_all
        self.owned_ids, self.cover_paths = set(), {}
        root = getattr(library, 'root', None)
        # Box art from covers-index.json, cached under the data directory.
        self.box_art = (covers.BoxArt(Path(root) / 'covers' / 'downloaded', enabled=download_covers)
                        if root is not None else None)
        self.visible, self.tiles, self.rows, self.row_of, self.headers = [], [], [], {}, []
        self.content_height = 0
        self.scanning = getattr(library, 'rom_dir', None) is not None
        self.refresh()
        self.session_title, self.session_started = '', 0.0
        self.running = True
        self.actions = {}
        self.status = ''
        self.last_log = None
        self.confirm_force = False
        self.presented = None  # Last (pixels, window size) shown on screen
        self.listed_after_scan = not self.scanning
        if self.scanning:
            self.status = LOADING
            threading.Thread(target=self.scan_roms, daemon=True).start()

    def scan_roms(self):
        # The status never names the ROM folder's location.
        def progress(done, total):
            self.status = f'{LOADING} {done}/{total}'
        try:
            self.library.scan(progress=progress)
            if self.status.startswith(LOADING):
                self.status = ''  # The grid shows what was found.
        except (OSError, ValueError) as exc:
            print(f'Could not scan the ROM folder: {exc}', file=sys.stderr)
            self.status = 'Could not load your games.'
        finally:
            self.scanning = False

    @property
    def game(self):
        return self.visible[self.index] if self.visible else None

    # ----- What is listed ---------------------------------------------------

    def is_owned(self, game):
        """Found in the ROM folder (or a local copy in the data directory): playable now."""
        if game.get('unavailable'):
            return False
        try:
            path = getattr(self.library, 'path', None)
            if path is not None and path(game).is_file():
                return True
            found = getattr(self.library, 'found', None)
            return bool(found is not None and found(game))
        except (OSError, ValueError):
            return False

    def refresh(self):
        """Re-read ownership and covers, keeping the selected game if it is still listed."""
        selected = self.game['id'] if self.visible else None
        self.owned_ids = {g['id'] for g in self.library.games if self.is_owned(g)}
        self.cover_paths = {}
        self.filter_games()
        ids = [g['id'] for g in self.visible]
        if selected in ids:
            self.show(ids.index(selected))
        if self.box_art is not None:
            for game in self.library.games:  # Fetch the collection's art first.
                if game['id'] in self.owned_ids:
                    self.box_art.request(game)

    def listed(self, game):
        return self.show_all or game['id'] in self.owned_ids

    def category_count(self, name):
        return sum(1 for g in self.library.games if series(g) == name and self.listed(g))

    def filter_games(self):
        def matches(game, term):
            # A year matches only from three digits ("199", "2013"), so the
            # "2" in "stadium 2" doesn't also pick up every game from 2000.
            return (term in fold(f"{game['title']} {game['platform']}") or
                    len(term) >= 3 and str(game['year']).startswith(term))
        terms = fold(self.query).split()
        games = [g for g in self.library.games if series(g) == self.category and self.listed(g)
                 and all(matches(g, term) for term in terms)]
        # Group by system, oldest handhelds first; catalogue order within a system.
        first_seen = {}
        for game in self.library.games:
            first_seen.setdefault(game['platform'], len(first_seen))
        self.visible = sorted(games, key=lambda g: (covers.platform_rank(g['platform']),
                                                    first_seen[g['platform']]))
        self.layout_grid()
        self.index = self.scroll = 0

    def layout_grid(self):
        """Place tiles in rows of COLS under one heading per system."""
        self.tiles, self.rows, self.row_of, self.headers = [], [], {}, []
        y, col, platform = 0, 0, None
        for i, game in enumerate(self.visible):
            if game['platform'] != platform:
                if platform is not None:
                    y += TILE_H + SECTION_GAP
                platform = game['platform']
                count = sum(1 for g in self.visible if g['platform'] == platform)
                self.headers.append((covers.platform_name(platform), count, y))
                y += HEADER_H
                self.rows.append([])
                col = 0
            elif col == COLS:
                y += TILE_H + GAP_Y
                self.rows.append([])
                col = 0
            self.tiles.append(pg.Rect(col * (TILE_W + GAP_X), y, TILE_W, TILE_H))
            self.rows[-1].append(i)
            self.row_of[i] = len(self.rows) - 1
            col += 1
        self.content_height = y + TILE_H if self.visible else 0

    # ----- Selection and scrolling -----------------------------------------

    def show(self, index):
        """Select a tile and scroll it (and its heading, on a first row) into view."""
        if not self.visible:
            self.index = self.scroll = 0
            return
        self.index = max(0, min(len(self.visible) - 1, index))
        tile = self.tiles[self.index]
        row = self.row_of[self.index]
        starts_section = row == 0 or self.visible[self.rows[row - 1][0]]['platform'] != \
            self.visible[self.index]['platform']
        top = tile.top - (HEADER_H if starts_section else 0)
        if top < self.scroll:
            self.scroll = top
        elif tile.bottom > self.scroll + GRID_VIEW.h:
            self.scroll = tile.bottom - GRID_VIEW.h
        self.scroll_by(0)

    def select(self, index):
        self.show(index)
        self.status = ''

    def move_row(self, step):
        if not self.visible:
            return
        row = self.row_of[self.index]
        target = row + step
        if 0 <= target < len(self.rows):
            column = self.rows[row].index(self.index)
            self.select(self.rows[target][min(column, len(self.rows[target]) - 1)])

    def scroll_by(self, pixels):
        limit = max(0, self.content_height - GRID_VIEW.h)
        self.scroll = max(0, min(limit, self.scroll + pixels))

    # ----- Drawing ----------------------------------------------------------

    def text(self, text, x, y, *, size=23, color=INK, width=None):
        font = self.fonts[size]
        if width is not None and font.size(text)[0] > width:
            while text and font.size(text + '…')[0] > width:
                text = text[:-1]
            text += '…'
        self.screen.blit(render_text(font, text, color), (x, y))

    def wrapped(self, text, x, y, *, size=20, color=MUTED, width=DW, max_lines=None):
        """Draw word-wrapped text; returns the y below it."""
        font = self.fonts[size]
        lines, line = [], ''
        for word in text.split():
            candidate = f'{line} {word}'.strip()
            if line and font.size(candidate)[0] > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines - 1] + [' '.join(lines[max_lines - 1:])]
        for line in lines:
            self.text(line, x, y, size=size, color=color, width=width)
            y += font.get_linesize()
        return y

    def box(self, rect, color, radius=10):
        return pg.draw.rect(self.screen, color, rect, border_radius=radius)

    def action(self, label, rect, callback, *, primary=False, centered=True):
        r = self.box(rect, ACCENT if primary else SURFACE)
        color = DARK if primary else INK
        if centered:
            rendered = render_text(self.fonts[23], label, color)
            self.screen.blit(rendered, rendered.get_rect(center=r.center))
        else:
            self.text(label, r.x+12, r.y+10, color=color)
        self.actions[label] = (r, callback)

    def pill(self, name, label, x, y, active, callback):
        r = self.box((x, y, self.fonts[20].size(label)[0] + 26, 26), ACCENT if active else SURFACE, radius=8)
        rendered = render_text(self.fonts[20], label, DARK if active else INK)
        self.screen.blit(rendered, rendered.get_rect(center=r.center))
        self.actions[name] = (r, callback)
        return r

    def draw_search(self):
        """A rounded field: magnifier, query or placeholder, then a count and clear button or a / hint."""
        r = SEARCH_RECT
        active = self.searching
        pg.draw.rect(self.screen, FIELD, r, border_radius=r.h // 2)
        pg.draw.rect(self.screen, ACCENT if active else FIELD_EDGE, r, width=2 if active else 1,
                     border_radius=r.h // 2)
        # Magnifier: a ring and a handle.
        cx, cy = r.x + 21, r.centery - 2
        icon = ACCENT if active else MUTED
        pg.draw.circle(self.screen, icon, (cx, cy), 7, 2)
        pg.draw.line(self.screen, icon, (cx + 5, cy + 5), (cx + 10, cy + 10), 3)
        right = r.right - 14
        if self.query:
            clear = pg.Rect(0, 0, 22, 22)
            clear.center = (r.right - 21, r.centery)
            pg.draw.circle(self.screen, SURFACE, clear.center, 11)
            for sign in (-1, 1):
                pg.draw.line(self.screen, INK, (clear.centerx - 4, clear.centery - 4 * sign),
                             (clear.centerx + 4, clear.centery + 4 * sign), 2)
            self.actions['search:clear'] = (clear.inflate(8, 8), self.clear_search)
            found = len(self.visible)
            count = render_text(self.fonts[20], f"{found} game{'' if found == 1 else 's'}", HINT)
            right = clear.left - 8
            self.screen.blit(count, count.get_rect(midright=(right, r.centery)))
            right -= count.get_width() + 8
        elif not active:
            key = render_text(self.fonts[20], '/', HINT)
            chip = pg.Rect(0, 0, 22, 22)
            chip.center = (r.right - 21, r.centery)
            pg.draw.rect(self.screen, FIELD_EDGE, chip, width=1, border_radius=6)
            self.screen.blit(key, key.get_rect(center=chip.center))
            right = chip.left - 8
        x = r.x + 38
        font = self.fonts[23]
        caret = active and time.monotonic() % 1 < .6
        if self.query:
            shown = self.query
            while shown and font.size(shown)[0] > right - x - 4:
                shown = shown[1:]  # Keep the end of a long query, where typing happens.
            label = render_text(font, shown, INK)
            self.screen.blit(label, label.get_rect(midleft=(x, r.centery)))
            x += label.get_width() + 1
        else:
            label = render_text(font, 'Search games', HINT)
            self.screen.blit(label, label.get_rect(midleft=(x + (2 if active else 0), r.centery)))
        if caret:
            pg.draw.line(self.screen, ACCENT, (x, r.centery - 10), (x, r.centery + 9), 2)
        self.actions['search'] = (r, self.start_search)  # After the clear button: it is checked first.

    def icon_button(self, name, rect, callback):
        r = self.box(rect, SURFACE, radius=10)
        draw_fullscreen_icon(self.screen, r, INK, exit_icon=self.window_frame.fullscreen)
        self.actions[name] = (r, callback)

    def draw(self):
        self.screen.fill(BG)
        self.actions.clear()
        self.draw_library()
        if self.session is not None:
            label = 'Confirm force close' if self.confirm_force else 'Force close'
            self.action(label, (645, 576, 168, 38), self.force_close)
        elif self.last_log:
            self.action('Copy log path', (660, 576, 153, 38), self.copy_log)
        self.text(self.status, 28, 589, size=20, color=ACCENT,
                  width=607 if self.last_log or self.session else W-56)
        self.presentation = self.window.get_surface()
        self.viewport = fit_rect((W, H), self.presentation.get_size())
        # Drawing the logical screen is cheap; scaling and presenting it to a
        # large window is not. Present only when the pixels or size changed.
        frame = (self.screen.get_buffer().raw, self.presentation.get_size())  # memcpy, no pixel conversion
        if frame == self.presented:
            return
        self.presented = frame
        if self.viewport.w and self.viewport.h:
            self.presentation.fill(BG)
            scaled = self.screen if self.viewport.size == (W, H) else pg.transform.smoothscale(self.screen, self.viewport.size)
            self.presentation.blit(scaled, self.viewport)
            self.window_frame.draw_grip(self.presentation)
            self.window.flip()

    def draw_library(self):
        self.text('RETRO POCKET', 28, 27, size=40)
        self.draw_search()
        self.icon_button('fullscreen', FULLSCREEN_RECT, self.window_frame.toggle_fullscreen)
        x = 28
        for name in self.categories:
            r = self.pill('tab:' + name, f'{name}  {self.category_count(name)}', x, TABS_Y,
                          name == self.category, lambda name=name: self.set_category(name))
            x = r.right + 8
        # View switch, right-aligned with the search field and full-screen button.
        labels = (('view:mine', 'My games', False), ('view:all', 'Full catalogue', True))
        widths = [self.fonts[20].size(label)[0] + 26 for _, label, _ in labels]
        x = FULLSCREEN_RECT.right - sum(widths) - 6
        for (name, label, everything), width in zip(labels, widths):
            self.pill(name, label, x, TABS_Y, self.show_all == everything,
                      lambda everything=everything: self.set_view(everything))
            x += width + 6
        self.box(GRID_CARD, CARD)
        self.box(DETAIL_CARD, CARD)
        self.draw_grid()
        other = 'my games' if self.show_all else 'all games'
        self.text(f'Arrows: browse  •  Enter: play  •  Tab: series  •  C: {other}',
                  GRID_VIEW.x, 546, size=20, color=MUTED, width=GRID_VIEW.w)
        self.draw_details()

    def draw_grid(self):
        view = GRID_VIEW
        if not self.visible:
            self.draw_empty_grid()
            return
        self.screen.set_clip(view)
        for name, count, y in self.headers:
            top = view.y + y - self.scroll
            if top + HEADER_H > view.y and top < view.bottom:
                self.text(name.upper(), view.x, top + 4, size=20, color=ACCENT)
                self.text(str(count), view.x + self.fonts[20].size(name.upper())[0] + 10, top + 4,
                          size=20, color=MUTED)
        for i, tile in enumerate(self.tiles):
            r = tile.move(view.x, view.y - self.scroll)
            if not r.colliderect(view):
                continue
            self.draw_tile(i, r)
            self.actions[f'tile:{i}'] = (r.clip(view), lambda i=i: self.select(i))
        self.screen.set_clip(None)
        if self.content_height > view.h:
            track = pg.Rect(view.right + 4, view.y, 4, view.h)
            thumb_h = max(24, track.h * view.h // self.content_height)
            thumb_y = track.y + (track.h - thumb_h) * self.scroll // max(1, self.content_height - view.h)
            self.box(track, SURFACE, radius=2)
            self.box((track.x, thumb_y, track.w, thumb_h), MUTED, radius=2)

    def draw_tile(self, i, r):
        game = self.visible[i]
        art = self.cover(game)
        # Art keeps its own shape and stands on a shelf, so captions line up.
        cover_rect = art.get_rect(midbottom=(r.x + TILE_W // 2, r.y + COVER_H))
        self.screen.blit(art, cover_rect)
        if game['id'] not in self.owned_ids:
            # Full catalogue: dim what can't be played from here right now.
            shade = pg.Surface(cover_rect.size, pg.SRCALPHA)
            shade.fill((10, 14, 20, 150 if game.get('unavailable') else 95))
            self.screen.blit(shade, cover_rect)
            badge = 'NOT PLAYABLE' if game.get('unavailable') else 'NOT OWNED'
            # Over the system strip: the heading already names the system,
            # and the label (the game's name) stays readable.
            band = pg.Rect(r.x + 4, cover_rect.y + 4, TILE_W - 8, 20)
            self.box(band, '#0b0f14', radius=5)
            label = render_text(self.fonts[20], badge, MUTED)
            self.screen.blit(label, label.get_rect(center=band.center))
        selected = i == self.index
        if selected:
            pg.draw.rect(self.screen, ACCENT, cover_rect.inflate(8, 8), width=3, border_radius=6)
        self.text(game['title'], r.x, r.y + COVER_H + 6, size=20,
                  color=ACCENT if selected else MUTED, width=TILE_W)

    def cover(self, game, size=(TILE_W, COVER_H)):
        if game['id'] not in self.cover_paths:
            found = getattr(self.library, 'found', None)
            try:
                rom = found(game) if found is not None else None
            except (OSError, ValueError):
                rom = None
            path = covers.find_cover(game, getattr(self.library, 'root', None), rom)
            if path is None and self.box_art is not None:
                path = self.box_art.path(game)
                if path is None:
                    self.box_art.request(game)  # Shown with a generated cover until it arrives.
            self.cover_paths[game['id']] = path
        return covers.cover(game, size, self.cover_paths[game['id']])

    def draw_empty_grid(self):
        x, y, width = GRID_VIEW.x + 8, GRID_VIEW.y + 20, GRID_VIEW.w - 16
        if self.query:
            self.text(f'No matching {self.category} games.', x, y, width=width)
            hint = ('Press Tab for other series or Esc to reset the search.' if len(self.categories) > 1
                    else 'Press Esc to reset the search.')
            self.wrapped(hint, x, y + 30, width=width)
        elif self.show_all:
            self.text(f'The catalogue has no {self.category} games.', x, y, width=width)
        elif self.scanning:
            self.text(LOADING, x, y, width=width)
        else:
            self.text(f'No {self.category} games in your collection yet.', x, y, width=width)
            self.wrapped('Press C to browse the full catalogue.', x, y + 30, width=width)

    def draw_details(self):
        game = self.game
        if game is None:
            return
        picture = self.cover(game, DETAIL_COVER)
        art = pg.Rect(0, 0, *DETAIL_COVER)
        art.midtop = (DX + DW // 2, 126)
        self.screen.blit(picture, picture.get_rect(midbottom=art.midbottom))
        self.text(f"{covers.platform_name(game['platform'])}  /  {game['year']}", DX, art.bottom + 12,
                  size=20, color=ACCENT, width=DW)
        y = self.wrapped(game['title'], DX, art.bottom + 34, size=29, color=INK, max_lines=2) + 4
        bottom = DETAIL_CARD.bottom - 12
        if game.get('unavailable'):
            self.text('Catalogue only — not playable here', DX, y, size=20, color=ACCENT, width=DW)
            self.wrapped(game['unavailable'], DX, y + 24, max_lines=max(1, (bottom - y - 24) // 22))
            return
        path = getattr(self.library, 'path', None)
        found = getattr(self.library, 'found', lambda game: None)(game)
        installed = bool(path and path(game).is_file())
        # Plain status only: where games are stored is never shown.
        source = ('Ready to play' if installed or found else
                  LOADING if self.scanning else
                  'Not in your collection')
        y = self.wrapped(source, DX, y, max_lines=2) + 10
        # Play only for games that can start: owned, or maybe still being found.
        if not self.searching and (installed or found or self.scanning):
            self.action('Play', (DX, y, DW, 40), self.play, primary=True)
            y += 50
        variants = game.get('variants', ())
        room = (bottom - y - 22) // 20
        if not variants or room < 1:
            return
        self.text('Supported release variants:', DX, y, size=20, color=ACCENT, width=DW)
        shown = variants if len(variants) <= room else variants[:room - 1]
        for i, variant in enumerate(shown):
            self.text(variant['label'], DX, y + 22 + 20 * i, size=20, color=MUTED, width=DW)
        if len(shown) < len(variants):
            self.text(f'+ {len(variants) - len(shown)} more (see catalogue file)', DX,
                      y + 22 + 20 * len(shown), size=20, color=MUTED, width=DW)

    # ----- Commands ----------------------------------------------------------

    def force_close(self):
        if self.session is None:
            return
        if not self.confirm_force:
            self.confirm_force = True
            self.status = 'Force closing may lose unsaved progress. Click again to confirm.'
            return
        try:
            self.session.request_stop(force=True)
            self.status = 'Force closing emulator…'
        except OSError as exc:
            self.status = f'Could not force close: {exc}'
        finally:
            self.confirm_force = False

    def copy_log(self):
        if self.last_log:
            try:
                pg.scrap.put_text(str(self.last_log))
                self.status = 'Emulator log path copied.'
            except pg.error:
                self.status = f'Log: {self.last_log}'

    def set_category(self, name):
        """Show one category; an active search filter carries over."""
        if name == self.category:
            return
        self.category = name
        self.filter_games()
        self.status = ''

    def set_view(self, everything):
        """Switch between the owner's games and the full catalogue."""
        if everything == self.show_all:
            return
        self.show_all = everything
        selected = self.game['id'] if self.visible else None
        self.filter_games()
        ids = [g['id'] for g in self.visible]
        if selected in ids:
            self.show(ids.index(selected))
        self.status = ''

    def start_search(self):
        self.searching = True
        pg.key.start_text_input()

    def clear_search(self):
        self.end_search(reset=True)

    def end_search(self, reset=False):
        self.searching = False
        pg.key.stop_text_input()
        if reset:
            self.query = ''
            self.filter_games()

    def play(self):
        if self.searching or not self.game:
            return
        if self.game.get('unavailable'):
            self.status = self.game['unavailable']
            return
        if self.session is not None:
            self.status = 'Close the existing emulator window before starting another game.'
            return
        source = getattr(self.library, 'source', self.library.path)
        if not source(self.game).is_file():
            if self.scanning:
                self.status = 'Still loading your games; try again in a moment.'
            else:
                self.status = 'This game is not in your collection.'
            return
        try:
            self.session = EmulatorSession.for_game(self.library, self.game, self.core_path)
            self.session_title = self.game['title']
            self.session_started = time.monotonic()
            self.status = OPENING
        except (OSError, ValueError) as exc:
            self.status = f'Could not start emulator: {exc}'

    # ----- Input and main loop ---------------------------------------------

    _REPAINT_EVENTS = tuple(getattr(pg, name) for name in (
        'WINDOWEXPOSED', 'WINDOWSHOWN', 'WINDOWRESTORED', 'WINDOWMAXIMIZED',
        'WINDOWRESIZED', 'WINDOWSIZECHANGED', 'WINDOWDISPLAYCHANGED', 'VIDEOEXPOSE') if hasattr(pg, name))
    _ARROWS = {pg.K_LEFT: (0, -1), pg.K_RIGHT: (0, 1), pg.K_UP: (-1, 0), pg.K_DOWN: (1, 0)}

    def navigate(self, key):
        rows, step = self._ARROWS[key]
        if rows:
            self.move_row(rows)
        else:
            self.select(self.index + step)

    def logical_point(self, pos):
        """A window-coordinate point on the 840x620 canvas, or None in the margins."""
        pixels = self.window.get_surface().get_size()
        viewport = fit_rect((W, H), pixels)
        point = surface_point(pos, pixels, self.window.size, viewport)
        if point is None or not viewport.w or not viewport.h:
            return None
        return ((point[0]-viewport.x)*W//viewport.w, (point[1]-viewport.y)*H//viewport.h)

    def draggable(self, pos):
        """The header (or the margins around the canvas), away from its buttons, moves the window."""
        logical = self.logical_point(pos)
        if logical is None:
            return True
        return logical[1] < HEADER_BOTTOM and not any(
            rect.collidepoint(logical) for rect, _ in self.actions.values())

    def event(self, event):
        if event.type in self._REPAINT_EVENTS:
            self.presented = None  # The compositor may need the frame again.
        if self.window_frame.handle(event, self.draggable):
            return
        if event.type in (pg.QUIT, pg.WINDOWCLOSE):
            self.running = False
        elif event.type == pg.TEXTINPUT and self.searching:
            # SDL can deliver the slash that opened the search as text as well.
            self.query = (self.query + event.text.replace('/', ' '))[:128].lstrip()
            self.filter_games()
        elif event.type == pg.KEYDOWN:
            if event.key == pg.K_TAB:
                step = -1 if event.mod & pg.KMOD_SHIFT else 1
                position = self.categories.index(self.category) + step
                self.set_category(self.categories[position % len(self.categories)])
            elif self.searching:
                if event.key == pg.K_ESCAPE:
                    self.end_search(reset=True)
                elif event.key == pg.K_RETURN:
                    self.end_search()
                elif event.key == pg.K_BACKSPACE:
                    self.query = self.query[:-1]
                    self.filter_games()
                elif event.key in self._ARROWS:
                    self.navigate(event.key)
            else:
                if event.key == pg.K_SLASH:
                    self.start_search()
                elif event.key == pg.K_ESCAPE and self.query:
                    self.end_search(reset=True)
                elif event.key in self._ARROWS:
                    self.navigate(event.key)
                elif event.key == pg.K_RETURN:
                    self.play()
                elif event.key == pg.K_c:
                    self.set_view(not self.show_all)
        elif event.type == pg.MOUSEWHEEL:
            self.scroll_by(-event.y * WHEEL_STEP)
        elif event.type == pg.MOUSEBUTTONDOWN and event.button == 1:
            logical = self.logical_point(event.pos)
            if logical is None:
                return
            hit = next(((name, callback) for name, (rect, callback) in self.actions.items()
                        if rect.collidepoint(logical)), None)
            if self.searching and (hit is None or not hit[0].startswith('search')):
                self.end_search()  # Clicking elsewhere finishes typing; the filter stays.
            if hit is not None:
                hit[1]()

    def update(self):
        if self.box_art is not None:
            for game_id in self.box_art.drain():
                self.cover_paths.pop(game_id, None)  # Its art arrived: draw it next frame.
        if not self.listed_after_scan and not self.scanning:
            # The background scan finished: list what it found.
            self.listed_after_scan = True
            self.refresh()
        if (self.session is not None and self.status == OPENING and self.session.process.poll() is None
                and time.monotonic() - self.session_started >= PLAYING_AFTER):
            self.status = f'Playing {self.session_title}. Close its window to come back here.'
        if self.session is not None and (code := self.session.process.poll()) is not None:
            self.status = exit_message(code, self.session.log) or 'Returned from emulator.'
            self.last_log = self.session.log if code else None
            self.session = None
            self.confirm_force = False

    def run(self):
        clock = pg.time.Clock()
        try:
            idle = 0
            while self.running:
                events = pg.event.get()
                for event in events:
                    self.event(event)
                # Input and foreground work redraw every tick (30 fps). When
                # idle, refresh at 10 Hz: still prompt for background status
                # (ROM scan, emulator exit) at a third of the CPU cost.
                idle = 0 if events else idle + 1
                if idle % 3 == 0:
                    self.update()
                    self.draw()
                clock.tick(30)
        finally:
            render_text.cache_clear()
            covers.clear_caches()
            pg.quit()


def _windowless_output(library, windowless):
    """Started without a console or terminal: keep diagnostics in the data directory."""
    if not windowless:
        return
    try:
        logs = library.root / 'logs'
        logs.mkdir(mode=0o700, parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(logs / 'retro-pocket.log', 'a', encoding='utf-8', buffering=1)
    except OSError:
        pass


def _report(message, windowless):
    print(message, file=sys.stderr)
    if not windowless:
        return
    # No console to read it in: show it.
    if compat.WINDOWS:
        import ctypes
        try:
            ctypes.windll.user32.MessageBoxW(None, message, 'Retro Pocket', 0x10)
        except OSError:
            pass
    elif compat.MACOS:
        import subprocess
        script = ('on run argv', 'display alert "Retro Pocket" message (item 1 of argv) as critical', 'end run')
        try:
            subprocess.run(['/usr/bin/osascript', *(arg for line in script for arg in ('-e', line)), message],
                           stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
        except (OSError, subprocess.SubprocessError):
            pass


def main():
    # pythonw.exe (the Windows launcher), or the macOS app, which says so.
    windowless = sys.stderr is None or os.environ.get('RETRO_POCKET_WINDOWLESS') == '1'
    parser = argparse.ArgumentParser(description='Retro Pocket: a Pokémon and Mario game library')
    parser.add_argument('--core', help='trusted local mGBA libretro core (mgba_libretro.so or .dll)')
    parser.add_argument('--data-dir', type=Path, help='override the default data directory')
    parser.add_argument('--roms-dir', type=Path,
                        help='folder to scan for game dumps (default: $RETRO_POCKET_ROMS or ./roms)')
    parser.add_argument('--all', action='store_true', help='start on the full catalogue, not just your games')
    parser.add_argument('--no-cover-downloads', action='store_true',
                        help="don't download box art; use your own pictures and generated covers")
    args = parser.parse_args()
    try:
        from library import Library, default_rom_dir
        library = Library(root=args.data_dir, rom_dir=args.roms_dir or default_rom_dir())
        _windowless_output(library, windowless)
        App(library, args.core, show_all=args.all, download_covers=not args.no_cover_downloads).run()
    except (OSError, ValueError, pg.error) as e:
        _report(f'Retro Pocket: {e}', windowless)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
