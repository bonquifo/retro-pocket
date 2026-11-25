"""Catalog-backed storage for verified, raw cartridge images."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile

import compat


# Read-only, never blocking on a FIFO (POSIX), and never translating line ends (Windows).
_READ_FLAGS = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
_CART_LIMITS = {p: 32 * 1024**2 for p in ('GB', 'GBC', 'GBA')}
_CART_LIMITS.update(NDS=512 * 1024**2, N64=64 * 1024**2, GCN=2 * 1024**3,
                    Wii=9 * 1024**3, Mini=16 * 1024**2)
_CART_LIMITS['3DS'] = 8 * 1024**3  # Largest retail 3DS card
_DIGEST_LENGTHS = {"sha256": 64, "sha1": 40}
DEFAULT_SERIES = 'Pokémon'  # Catalogue category for entries without a "series"


_ROM_SUFFIXES = {'.gb', '.gbc', '.gba', '.nds', '.z64', '.min', '.iso', '.3ds'}
_INDEX_NAME = 'rom-index.json'


def default_rom_dir():
    """The ROM folder Retro Pocket scans: $RETRO_POCKET_ROMS or ./roms beside the app."""
    override = os.environ.get('RETRO_POCKET_ROMS')
    return Path(override).expanduser() if override else Path(__file__).resolve().with_name('roms')


def _advise(fd, advice):
    try:
        os.posix_fadvise(fd, 0, 0, advice)
    except (AttributeError, OSError):
        pass  # Only a page-cache hint.


def _rotational(path):
    """True if ``path`` is on a spinning disk; False if solid state or unknown."""
    return compat.rotational(path)


def _file_digests(path, algorithms):
    digests = {algorithm: hashlib.new(algorithm) for algorithm in algorithms}
    buffer = bytearray(1024 * 1024)
    view = memoryview(buffer)
    fd = os.open(path, _READ_FLAGS)
    try:
        _advise(fd, getattr(os, 'POSIX_FADV_SEQUENTIAL', 2))
        with os.fdopen(fd, 'rb', buffering=0, closefd=False) as source:
            while count := source.readinto(buffer):
                for digest in digests.values():
                    digest.update(view[:count])
        # A bulk scan should not evict everything else from the page cache.
        _advise(fd, getattr(os, 'POSIX_FADV_DONTNEED', 4))
    finally:
        os.close(fd)
    return {algorithm: digest.hexdigest() for algorithm, digest in digests.items()}


def _default_root():
    """$XDG_DATA_HOME/retro-pocket if set; else %LOCALAPPDATA%\\RetroPocket on Windows,
    ~/Library/Application Support/RetroPocket on macOS, ~/.local/share/retro-pocket on Linux."""
    xdg = Path(os.environ.get("XDG_DATA_HOME", ""))
    if xdg.is_absolute():
        return xdg / "retro-pocket"
    if compat.WINDOWS or compat.MACOS:
        return compat.data_home() / "RetroPocket"
    return compat.data_home() / "retro-pocket"


def _variants(entries, max_size):
    if not isinstance(entries, list) or not entries:
        raise ValueError("Catalog game must have at least one ROM variant")
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Invalid ROM variant")
        size = entry.get("size")
        if type(size) is not int or not 0 < size <= max_size:
            raise ValueError("Invalid ROM variant size")
        digests = []
        for algorithm, length in _DIGEST_LENGTHS.items():
            if algorithm in entry:
                digest = entry[algorithm]
                if not isinstance(digest, str) or not re.fullmatch(f"[0-9a-fA-F]{{{length}}}", digest):
                    raise ValueError(f"Invalid {algorithm} digest")
                digests.append((algorithm, digest.lower()))
        if not digests or not isinstance(entry.get("label"), str):
            raise ValueError("ROM variant requires a label and a SHA-1 or SHA-256 digest")
        algorithm, digest = digests[0]  # Prefer SHA-256 if both are supplied.
        result.append((size, algorithm, digest))
    return tuple(result)


def _read(source, variants):
    data = source.read(max(size for size, _, _ in variants) + 1)
    for size, algorithm, digest in variants:
        if len(data) == size and hashlib.new(algorithm, data).hexdigest() == digest:
            if zipfile.is_zipfile(io.BytesIO(data)):
                raise ValueError("ZIP archives are not raw ROMs")
            return data
    raise ValueError("ROM size or digest does not match the catalog")


def _read_file(path, variants):
    fd = os.open(path, _READ_FLAGS)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('ROM must be a regular file')
        variants = tuple(v for v in variants if v[0] == info.st_size)
        if not variants:
            raise ValueError('ROM size does not match the catalog')
        with os.fdopen(fd, 'rb', closefd=False) as source:
            return _read(source, variants)
    finally:
        os.close(fd)


def _load_catalogs(primary, merge):
    files = [primary]
    if merge:
        files += sorted(primary.parent.glob('catalog-*.json'))
    games = []
    for path in files:
        rows = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(rows, list):
            raise ValueError(f'Catalog must be a list of games: {path.name}')
        games.extend(rows)
    if not games:
        raise ValueError('Catalog is empty')
    # A verified platform supplement can replace a matching metadata-only row.
    playable = {g.get('id'): g for g in games if isinstance(g, dict)
                and isinstance(g.get('id'), str) and 'unavailable' not in g}
    rows = []
    for game in games:
        if merge and isinstance(game, dict) and 'unavailable' in game and isinstance(game.get('id'), str):
            promoted = playable.get(game['id'])
            if promoted:
                if promoted.get('platform') != game.get('platform'):
                    raise ValueError(f"Promotion platform mismatch for {game['id']}")
                continue
        rows.append(game)
    return rows


class Library:
    """Import and retrieve ROMs without unpacking or executing them."""

    def __init__(self, root: Path | None = None, catalog: Path | None = None, *, base_catalog=None,
                 rom_dir: Path | None = None):
        self.root = Path(root) if root is not None else _default_root()
        self.rom_dir = Path(rom_dir).expanduser().resolve() if rom_dir is not None else None
        self._found = {}  # game ID -> ROM file discovered by scan()
        primary = Path(catalog or base_catalog or Path(__file__).with_name('catalog.json'))
        self.games = _load_catalogs(primary, catalog is None)
        self._games_by_id = {}
        self._unavailable = {}
        for game in self.games:
            game_id = game.get("id") if isinstance(game, dict) else None
            if not isinstance(game_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", game_id):
                raise ValueError("Invalid catalog game ID")
            if game_id in self._games_by_id or game_id in self._unavailable:
                raise ValueError(f"Duplicate catalog game ID: {game_id}")
            platform = game.get("platform")
            if not isinstance(game.get("title"), str) or type(game.get("year")) is not int:
                raise ValueError(f"Invalid catalog title or year for {game_id}")
            series = game.get("series", DEFAULT_SERIES)
            if not isinstance(series, str) or not series.strip():
                raise ValueError(f"Invalid catalog series for {game_id}")
            if 'download' in game:
                raise ValueError(f'ROM downloads are not supported ({game_id}); put the ROM in the ROM folder')
            if 'unavailable' in game:
                reason = game['unavailable']
                if (not isinstance(reason, str) or not reason.strip() or game.get('variants') != []
                        or not isinstance(platform, str) or not platform.strip()):
                    raise ValueError(f'Invalid catalogue-only entry: {game_id}')
                self._unavailable[game_id] = reason
                continue
            if not isinstance(platform, str) or platform not in _CART_LIMITS:
                raise ValueError(f'Invalid catalog platform for {game_id}')
            # Keep verification metadata independent of the public UI dictionaries.
            self._games_by_id[game_id] = (platform, _variants(game.get('variants'), _CART_LIMITS[platform]))

    def _record(self, game):
        game_id = game.get("id") if isinstance(game, dict) else None
        if isinstance(game_id, str) and game_id in self._unavailable:
            raise ValueError(self._unavailable[game_id])
        if not isinstance(game_id, str) or game_id not in self._games_by_id:
            raise ValueError("Game is not in the catalog")
        return self._games_by_id[game_id]

    def path(self, game) -> Path:
        platform, _ = self._record(game)
        suffix = {'GCN': 'iso', 'Wii': 'iso', 'N64': 'z64', 'Mini': 'min', '3DS': '3ds'}.get(platform, platform.lower())
        return self.root / f"{game['id']}.{suffix}"

    def found(self, game) -> Path | None:
        """The ROM-folder file that scan() matched to this game, if any."""
        return self._found.get(game.get('id')) if isinstance(game, dict) else None

    def source(self, game) -> Path:
        """Where Play reads the game from: an imported copy, else the ROM folder."""
        stored = self.path(game)
        if stored.is_file():
            return stored
        return self.found(game) or stored

    def scan(self, only=None, progress=None) -> dict:
        """Match files under ``rom_dir`` to catalogue variants by size and digest.

        Digests are cached in the data directory, keyed by path, size, inode and
        modification time, so later scans only stat unchanged files. This only
        picks candidates: load() and stage() verify the bytes again at launch.
        ``only`` limits the scan to one game ID; ``progress(done, total)`` is
        called as files are checked.
        """
        wanted = {}
        for game_id, (_, variants) in self._games_by_id.items():
            if only is not None and game_id != only:
                continue
            for size, algorithm, digest in variants:
                wanted.setdefault(size, []).append((game_id, algorithm, digest))
        directory = self.rom_dir
        candidates = []
        if directory is not None and directory.is_dir():
            for parent, folders, files in os.walk(directory):
                # Like symlinks, Windows junctions lead outside the folder: don't follow them.
                folders[:] = sorted(f for f in folders if not compat.is_link(Path(parent) / f))
                for name in sorted(files):
                    path = Path(parent) / name
                    if path.suffix.lower() not in _ROM_SUFFIXES:
                        continue
                    try:
                        info = path.lstat()
                    except OSError:
                        continue
                    if stat.S_ISREG(info.st_mode) and info.st_size in wanted:
                        candidates.append((info.st_size, str(path), info))
        candidates.sort()  # Small cartridges first, so most games appear quickly.

        index_path = self.root / _INDEX_NAME
        try:
            index = json.loads(index_path.read_text(encoding='utf-8'))
            if not isinstance(index, dict):
                index = {}
        except (OSError, ValueError):
            index = {}
        found = {} if only is None else dict(self._found)
        changed = False
        if only is None:  # Forget files that were removed or no longer match any size.
            keys = {key for _, key, _ in candidates}
            pruned = {key: value for key, value in index.items() if key in keys}
            changed, index = len(pruned) != len(index), pruned
        order = {key: position for position, (_, key, _) in enumerate(candidates)}
        work = []
        for size, key, info in candidates:
            # ctime changes on any content write, even if mtime is restored.
            stamp = [size, info.st_ino, info.st_mtime_ns, info.st_ctime_ns]
            entry = index.get(key)
            digests = entry.get('digests', {}) if isinstance(entry, dict) and entry.get('stamp') == stamp else {}
            needed = {algorithm for _, algorithm, _ in wanted[size]} - set(digests)
            work.append((size, key, stamp, digests, needed))

        def record(size, key, digests):
            for game_id, algorithm, digest in wanted[size]:
                if digests.get(algorithm) == digest:
                    current = found.get(game_id)
                    # Deterministic: the first matching file in path order wins.
                    if current is None or order[key] < order[str(current)]:
                        found[game_id] = Path(key)
            self._found = dict(found)

        done = 0
        pending = []
        for size, key, stamp, digests, needed in work:
            if needed:
                pending.append((size, key, stamp, digests, needed))
                continue
            record(size, key, digests)
            done += 1
            if progress:
                progress(done, len(candidates))
        if pending:
            # SHA-1 is CPU-bound below SSD read speed, so hash several files at
            # once; stay sequential on spinning disks, where seeks dominate.
            workers = 1 if _rotational(directory) else max(1, min(4, os.cpu_count() or 1, len(pending)))
            with ThreadPoolExecutor(workers) as pool:
                jobs = {pool.submit(_file_digests, key, needed): (size, key, stamp, digests)
                        for size, key, stamp, digests, needed in pending}
                for job in as_completed(jobs):
                    size, key, stamp, digests = jobs[job]
                    done += 1
                    try:
                        digests = {**digests, **job.result()}
                    except OSError:
                        pass  # Unreadable now; skip it this scan.
                    else:
                        index[key] = {'stamp': stamp, 'digests': digests}
                        changed = True
                        record(size, key, digests)
                    if progress:
                        progress(done, len(candidates))
        if changed:
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile('w', dir=self.root, delete=False, encoding='utf-8') as output:
                    json.dump(index, output)
                Path(output.name).replace(index_path)
            except OSError:
                pass  # The cache is an optimisation; matching already succeeded.
        self._found = found
        return dict(found)

    def staged_name(self, game) -> str:
        return self.path(game).name

    def _copy_verified(self, game, source, target=None) -> Path:
        """Stream-check ``source`` against the catalogue, copying it to ``target`` if given.

        Memory use is one 1 MiB buffer regardless of image size. Without a
        target nothing is written and ``source`` is returned.
        """
        _, variants = self._record(game)
        if target is not None:
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(source, _READ_FLAGS)
        temporary = None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('ROM must be a regular file')
            eligible = [(algorithm, digest) for size, algorithm, digest in variants if size == info.st_size]
            if not eligible:
                raise ValueError('ROM size does not match the catalog')
            _advise(fd, getattr(os, 'POSIX_FADV_SEQUENTIAL', 2))
            with os.fdopen(fd, 'rb', buffering=0, closefd=False) as stream:
                if zipfile.is_zipfile(stream):
                    raise ValueError('ZIP archives are not raw ROMs')
                stream.seek(0)
                digests = {algorithm: hashlib.new(algorithm) for algorithm, _ in eligible}
                buffer = bytearray(1024 * 1024)
                view = memoryview(buffer)
                remaining = info.st_size
                output = None
                if target is not None:
                    output = tempfile.NamedTemporaryFile(dir=target.parent, delete=False)
                    temporary = Path(output.name)
                try:
                    while remaining:
                        count = stream.readinto(view[:min(remaining, len(buffer))])
                        if not count:
                            break
                        chunk = view[:count]
                        if output is not None:
                            output.write(chunk)
                        remaining -= count
                        for digest in digests.values():
                            digest.update(chunk)
                    if remaining or stream.read(1) or not any(
                        digests[algorithm].hexdigest() == expected for algorithm, expected in eligible
                    ):
                        raise ValueError('ROM size or digest does not match the catalog')
                finally:
                    if output is not None:
                        output.close()
            if temporary is None:
                return Path(source)
            temporary.replace(target)
        finally:
            os.close(fd)
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target

    def stage(self, game, target: Path) -> Path:
        """Write a verified copy of the game's source to ``target``."""
        return self._copy_verified(game, self.source(game), target)

    def verify(self, game) -> Path:
        """Check the game's source file in place and return its path; nothing is copied."""
        return self._copy_verified(game, self.source(game))

    def place(self, game, target: Path) -> Path:
        """Verify the source, then publish it at ``target`` as a hard link.

        A hard link costs no data copy and gives the emulator a stable file
        name (some name save files after the ROM). Falls back to a streamed
        copy when linking is not possible, e.g. across filesystems.
        """
        source = self.verify(game)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = target.with_name(f'.{target.name}.{os.getpid()}.link')
        try:
            temporary.unlink(missing_ok=True)
            os.link(source, temporary)
            temporary.replace(target)  # Replaces a stale file or symlink, never its target.
            return target
        except OSError:
            temporary.unlink(missing_ok=True)
            return self._copy_verified(game, source, target)

    def import_rom(self, game, path: Path) -> Path:
        return self._copy_verified(game, path, self.path(game))

    def load(self, game) -> bytes:
        _, variants = self._record(game)
        return _read_file(self.source(game), variants)
