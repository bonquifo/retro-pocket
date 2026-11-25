"""Shared pieces of Retro Pocket's build scripts (build_windows.py, build_macos.py, build_linux.py)."""
import importlib.util
from pathlib import Path, PurePosixPath
import stat
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'build' / 'cache'

# Retro Pocket's own files in a build: the program and its catalogue.
APP_FILES = ('*.py', 'catalog*.json', 'covers-index.json', 'README.md', 'SOURCES*.md')
PYTHON_VERSION = (3, 12)  # Of the Python inside the Windows and macOS builds
ROMS_README = ('Put your own game dumps here (any subfolder is fine): .gb, .gbc, .gba, .nds, .z64,\n'
               '.min, uncompressed GameCube .iso, or decrypted 3DS .3ds. Retro Pocket recognises them\n'
               'by their contents, so the file names don\'t matter. See README.md.\n')


def retro_pocket_files(exclude=(), extra=()):
    """(name, path) of Retro Pocket's own files for a build, from this checkout."""
    found = {}
    for pattern in (*APP_FILES, *extra):
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file() and path.name not in exclude:
                found[path.name] = path
    return sorted(found.items())


class Archive:
    """A zip of one folder, with Unix permissions and symlinks as macOS and Linux restore them."""

    def __init__(self, path: Path, folder: str):
        self.zip = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6)
        self.folder = folder
        self.names = set()
        self.stamp = time.localtime()[:6]

    def _info(self, name, kind, mode):
        name = f'{self.folder}/{name}'
        if name in self.names:
            raise ValueError(f'Two files at {name}')
        self.names.add(name)
        info = zipfile.ZipInfo(name, self.stamp)
        info.create_system = 3  # Unix: Archive Utility, ditto and unzip apply external_attr
        info.external_attr = (kind | mode) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        return info

    def file(self, name, data: bytes, mode=0o644):
        self.zip.writestr(self._info(name, stat.S_IFREG, mode), data)

    def link(self, name, target: str):
        info = self._info(name, stat.S_IFLNK, 0o755)
        info.compress_type = zipfile.ZIP_STORED
        self.zip.writestr(info, target.encode())

    def close(self):
        self.zip.close()


def pyc(source: bytes, name: str):
    """Bytecode that needs no timestamp check (a build's files never change), or None.

    Bytecode is per Python version: built with another version, the build's
    own Python compiles at run time instead.
    """
    if sys.version_info[:2] != PYTHON_VERSION:
        return None
    from importlib._bootstrap_external import _code_to_hash_pyc
    try:
        code = compile(source, name, 'exec', dont_inherit=True)
    except (SyntaxError, ValueError):
        return None
    return _code_to_hash_pyc(code, importlib.util.source_hash(source), checked=False)


def add_python_file(out: Archive, name: str, data: bytes, mode=0o644):
    """A file, and next to a .py file its precompiled bytecode."""
    out.file(name, data, mode)
    if name.endswith('.py'):
        compiled = pyc(data, name)
        if compiled is not None:
            path = PurePosixPath(name)
            tag = f'cpython-{PYTHON_VERSION[0]}{PYTHON_VERSION[1]}'
            out.file(str(path.parent / '__pycache__' / f'{path.stem}.{tag}.pyc'), compiled)


def add_wheel(out: Archive, wheel: Path, site_packages: str, exclude=()):
    """Install a wheel by unpacking it into ``site_packages`` (it has no scripts or data)."""
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir() or '.data/' in info.filename or info.filename.startswith(tuple(exclude)):
                continue
            unix = stat.S_IMODE(info.external_attr >> 16) if info.create_system == 3 else 0
            add_python_file(out, site_packages + info.filename, archive.read(info), unix or 0o644)


# pygame-ce's documentation, examples and tests aren't needed to run.
PYGAME_EXCLUDE = ('pygame/docs/', 'pygame/examples/', 'pygame/tests/')


def add_emulators(out: Archive, platform: str, base: str):
    """The pinned emulator packages for ``platform`` (install_emulators.PLATFORMS) under ``base``."""
    import install_emulators as emulators

    for name, package in emulators.PLATFORMS[platform].items():
        archive_path, digest = emulators.cached(package.url, package.size, package.sha256, CACHE)
        if package.sha256 is None:
            print(f'  {name}: unpinned nightly build, SHA-256 {digest}')
        found = False
        with zipfile.ZipFile(archive_path) as archive:
            for entry in emulators.entries(archive):
                path = f'{base}/{name}/{entry.path}'
                if entry.link is not None:
                    out.link(path, entry.link)
                    continue
                data = archive.read(entry.info)
                if str(entry.path) == package.check:
                    found = True
                    if package.arch and package.arch not in emulators.header_architectures(data[:4096]):
                        raise ValueError(f'{name}: {package.check} is not built for {package.arch}')
                out.file(path, data, entry.mode)
        if not found:
            raise ValueError(f'{name}: the archive has no {package.check}')
        out.file(f'{base}/{name}/{emulators.MARKER}', (package.sha256 or digest).encode())
