"""Cover art for the catalogue grid.

A game's cover is, in order:
  1. the owner's own picture (PNG or JPEG, at most 16 MB) at
     <data dir>/covers/<game id>.png|.jpg|.jpeg, or next to the ROM found in
     the ROM folder with the same name ("Pokemon - Red Version (USA, Europe)
     (SGB Enhanced).png", the naming RetroArch's libretro-thumbnails use);
  2. its box art from libretro-thumbnails, listed with a pinned commit, size
     and SHA-256 in covers-index.json, downloaded once into
     <data dir>/covers/downloaded/ and checked against that digest;
  3. a plain card with the system and title, for games without box art
     (download-only and non-Nintendo releases), offline, or while downloading.
"""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import tempfile
import threading
import urllib.request

import pygame as pg

import compat
from viewport import fit_rect

IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg')
MAX_IMAGE_BYTES = 16 * 1024 * 1024
INDEX = Path(__file__).with_name('covers-index.json')
ART_URL_PREFIX = 'https://raw.githubusercontent.com/libretro-thumbnails/'
MAX_ART_BYTES = 4 * 1024 * 1024

PLATFORM_NAMES = {
    'GB': 'Game Boy', 'GBC': 'Game Boy Color', 'GBA': 'Game Boy Advance', 'Mini': 'Pokémon mini',
    'NDS': 'Nintendo DS', '3DS': 'Nintendo 3DS', 'N64': 'Nintendo 64', 'GCN': 'GameCube',
    'Wii': 'Wii', 'Wii U': 'Wii U', 'Switch': 'Nintendo Switch', 'Switch 2': 'Nintendo Switch 2',
    'Arcade': 'Arcade', 'PC': 'PC', 'Mobile': 'Mobile', 'Web': 'Web',
}
# Grid sections run oldest handhelds first; unknown platforms follow in catalogue order.
PLATFORM_ORDER = tuple(PLATFORM_NAMES)

# Accent colour per system (the stripe on cards without box art), loosely after its hardware.
_SHELLS = {
    'GB': '#9d9a93', 'GBC': '#5b3f9e', 'GBA': '#463a8c', 'Mini': '#2f78b5', 'NDS': '#3a3e45',
    '3DS': '#24589a', 'N64': '#2f3237', 'GCN': '#463b8a', 'Wii': '#c9ced4', 'Wii U': '#1b6a9c',
    'Switch': '#c8232b', 'Switch 2': '#2a2d33',
}
_DEFAULT_SHELL = '#3a4656'
CARD_FILL, CARD_EDGE, CARD_INK, CARD_MUTED = '#243140', '#33465a', '#f2f6fc', '#9fb1c5'

def clear_caches():
    """Drop cached fonts and covers; pygame fonts die with pg.quit()."""
    _font.cache_clear()
    generated_cover.cache_clear()
    _image_cover.cache_clear()


def platform_name(platform):
    return PLATFORM_NAMES.get(platform, platform)


def platform_rank(platform):
    try:
        return PLATFORM_ORDER.index(platform)
    except ValueError:
        return len(PLATFORM_ORDER)


def _wrap(font, text, width):
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
    return lines


@lru_cache(maxsize=8)
def _font(size):
    return pg.font.Font(None, size)


def _fitted_lines(text, width, height, sizes):
    """Wrap text at the largest size that fits; shrink words that never fit."""
    for size in sizes:
        font = _font(size)
        lines = _wrap(font, text, width)
        if (len(lines) * font.get_linesize() <= height
                and all(font.size(line)[0] <= width for line in lines)):
            return font, lines
    font = _font(sizes[-1])
    lines = _wrap(font, text, width)
    return font, lines[:max(1, height // font.get_linesize())]


@lru_cache(maxsize=512)
def generated_cover(title, platform, size):
    """A plain card for games without box art: the system, then the title."""
    w, h = size
    surface = pg.Surface(size, pg.SRCALPHA)
    pg.draw.rect(surface, CARD_FILL, surface.get_rect(), border_radius=6)
    pg.draw.rect(surface, CARD_EDGE, surface.get_rect(), width=1, border_radius=6)
    stripe = pg.Rect(1, 1, w - 2, 4)
    pg.draw.rect(surface, _SHELLS.get(platform, _DEFAULT_SHELL), stripe,
                 border_top_left_radius=6, border_top_right_radius=6)

    name = platform_name(platform).upper()
    size_ = next((s for s in range(15, 10, -1) if _font(s).size(name)[0] <= w - 12), 11)
    system = _font(size_).render(name, True, CARD_MUTED)
    surface.blit(system, system.get_rect(midtop=(w // 2, 11)))

    inner = pg.Rect(8, 28, w - 16, h - 36)
    y = inner.top
    name = title
    if title.startswith('Pokémon ') or title.startswith('Pocket Monsters '):
        prefix, name = title.split(' ', 1)
        small = _font(16).render(prefix.upper(), True, CARD_MUTED)
        y += 4
        lines_font, lines = _fitted_lines(name, inner.width, inner.bottom - y - small.get_height() - 2,
                                          (24, 21, 18, 16))
        block = small.get_height() + 2 + len(lines) * lines_font.get_linesize()
        y += max(0, (inner.bottom - y - block) // 2)
        surface.blit(small, small.get_rect(midtop=(w // 2, y)))
        y += small.get_height() + 2
    else:
        lines_font, lines = _fitted_lines(name, inner.width, inner.bottom - y, (24, 21, 18, 16))
        y += max(0, (inner.bottom - y - len(lines) * lines_font.get_linesize()) // 2)
    for line in lines:
        rendered = lines_font.render(line, True, CARD_INK)
        surface.blit(rendered, rendered.get_rect(midtop=(w // 2, y)))
        y += lines_font.get_linesize()
    return surface


def find_cover(game, data_dir=None, rom_path=None):
    """The owner's own picture for this game, if there is one."""
    candidates = []
    if data_dir is not None:
        candidates += [Path(data_dir) / 'covers' / f"{game['id']}{suffix}" for suffix in IMAGE_SUFFIXES]
    if rom_path is not None:
        candidates += [Path(rom_path).with_suffix(suffix) for suffix in IMAGE_SUFFIXES]
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size <= MAX_IMAGE_BYTES:
                return path
        except OSError:
            continue
    return None


@lru_cache(maxsize=256)
def _image_cover(path, mtime, size):
    """The picture scaled to fit size, keeping its proportions (the surface is the fitted size)."""
    loaded = pg.image.load(path)
    # smoothscale needs 32-bit pixels; palette PNGs and JPEGs may not be.
    image = pg.Surface(loaded.get_size(), pg.SRCALPHA)
    image.blit(loaded, (0, 0))
    return pg.transform.smoothscale(image, fit_rect(image.get_size(), size).size)


def cover(game, size, image_path=None):
    """The surface to draw for a game's cover: its picture (see find_cover) or a generated box."""
    if image_path is not None:
        try:
            return _image_cover(str(image_path), image_path.stat().st_mtime_ns, size)
        except (OSError, pg.error, ValueError):
            pass  # Unreadable or not an image: fall back to the generated box.
    return generated_cover(game['title'], game['platform'], size)


class BoxArt:
    """Box art listed in covers-index.json, fetched in the background on request.

    Only the pinned URL is fetched, and a file is kept only when its size and
    SHA-256 match the index. Failures are not retried until the next start.
    """

    def __init__(self, cache_dir, index_path=INDEX, *, enabled=True, opener=None):
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        self._open = opener or (lambda url: urllib.request.urlopen(
            urllib.request.Request(url, headers={'User-Agent': 'retro-pocket'}), timeout=20,
            context=compat.https_context()))
        try:
            entries = json.loads(Path(index_path).read_text(encoding='utf-8'))['covers']
        except (OSError, ValueError, KeyError, TypeError):
            entries = {}
        self.index = {game_id: entry for game_id, entry in entries.items() if self._valid(game_id, entry)}
        self._verified = {}            # game id -> Path, checked this session
        self._attempted = set()
        self._done = []                # ids downloaded since the last drain()
        self.failures = []             # (game id, reason)
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        self._thread = None

    @staticmethod
    def _valid(game_id, entry):
        return (isinstance(game_id, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', game_id)
                and isinstance(entry, dict) and isinstance(entry.get('url'), str)
                and entry['url'].startswith(ART_URL_PREFIX)
                and type(entry.get('size')) is int and 0 < entry['size'] <= MAX_ART_BYTES
                and isinstance(entry.get('sha256'), str)
                and re.fullmatch(r'[0-9a-f]{64}', entry['sha256']) is not None)

    def _file(self, game_id):
        return self.cache_dir / f'{game_id}.png'

    def path(self, game):
        """The verified downloaded art for a game, or None."""
        game_id = game['id']
        if game_id in self._verified:
            return self._verified[game_id]
        entry = self.index.get(game_id)
        if entry is None:
            return None
        try:
            data = self._file(game_id).read_bytes()
        except OSError:
            return None
        if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            return None  # Stale or damaged: a request() downloads it again.
        self._verified[game_id] = self._file(game_id)
        return self._verified[game_id]

    def request(self, game):
        """Queue a download if this game has listed art that isn't cached yet."""
        game_id = game['id']
        if (not self.enabled or game_id not in self.index or game_id in self._attempted
                or self.path(game) is not None):
            return
        self._attempted.add(game_id)
        self._queue.put(game_id)
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name='box-art', daemon=True)
            self._thread.start()

    def drain(self):
        """Game ids whose art arrived since the last call."""
        with self._lock:
            done, self._done = self._done, []
        return done

    def _run(self):
        while True:
            game_id = self._queue.get()
            try:
                self._download(game_id)
                with self._lock:
                    self._done.append(game_id)
            except Exception as exc:  # Network, disk or digest: keep the fallback cover.
                self.failures.append((game_id, str(exc)))

    def _download(self, game_id):
        entry = self.index[game_id]
        with self._open(entry['url']) as response:
            data = response.read(entry['size'] + 1)
        if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('box art does not match covers-index.json')
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.cache_dir, prefix='.art-', delete=False) as out:
            temporary = Path(out.name)
            try:
                out.write(data)
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, self._file(game_id))
        finally:
            temporary.unlink(missing_ok=True)
