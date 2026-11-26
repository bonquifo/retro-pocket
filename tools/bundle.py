"""Shared pieces of Retro Pocket's build scripts (build_windows.py, build_macos.py, build_linux.py)."""
import datetime
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'build' / 'cache'
sys.path.insert(0, str(ROOT))
import updater  # noqa: E402  (pure Python: version parsing and the build-info format)


def _git(*arguments):
    result = subprocess.run(['git', *arguments], cwd=ROOT, capture_output=True, text=True, timeout=30)
    return result.stdout.strip() if result.returncode == 0 else ''


def version():
    """The version a build reports.

    $RETRO_POCKET_VERSION (CI sets it for releases: "1.2.0"), else git's
    description of the commit: "1.2.0" on a release tag, "1.2.0-3-gabc1234"
    three commits later, "0.0.0-<commits>-g<hash>" before the first release.
    """
    explicit = os.environ.get('RETRO_POCKET_VERSION', '').strip()
    if explicit:
        explicit = explicit[1:] if explicit.startswith('v') else explicit
        if updater.parse_version(explicit) is None:
            raise ValueError(f'RETRO_POCKET_VERSION must look like 1.2.3, not {explicit!r}')
        return explicit
    try:
        described = _git('describe', '--tags', '--match', 'v[0-9]*.[0-9]*.[0-9]*', '--abbrev=7')
        if described and updater.parse_version(described):
            return described[1:]
        commits, commit = _git('rev-list', '--count', 'HEAD'), _git('rev-parse', '--short=7', 'HEAD')
        if commits and commit:
            return f'0.0.0-{commits}-g{commit}'
    except (OSError, subprocess.SubprocessError):
        pass
    return '0.0.0'


def pinned(package):
    """The version requirements.txt pins for ``package`` (the one list Dependabot keeps current)."""
    for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines():
        requirement = line.split('#', 1)[0].split(';', 1)[0].strip()
        name, _, version = requirement.partition('==')
        if name.strip().lower() == package.lower() and version.strip():
            return version.strip()
    raise ValueError(f'requirements.txt pins no version of {package}')


def pypi_wheel(package, patterns):
    """(url, size, sha256) of the pinned version's wheel on PyPI, the first file matching ``patterns``.

    The SHA-256 is PyPI's own (what pip checks), so the download is verified
    as pip would verify it.
    """
    import fnmatch
    import urllib.request
    version = pinned(package)
    url = f'https://pypi.org/pypi/{package}/{version}/json'
    request = urllib.request.Request(url, headers={'User-Agent': 'retro-pocket-build'})
    context = None
    try:
        import certifi
        import ssl
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    with urllib.request.urlopen(request, timeout=60, context=context) as response:
        files = json.load(response)['urls']
    for pattern in patterns:
        for file in files:
            if fnmatch.fnmatchcase(file['filename'], pattern) and file['packagetype'] == 'bdist_wheel':
                return file['url'], file['size'], file['digests']['sha256']
    raise ValueError(f'{package} {version} has no wheel on PyPI matching {patterns}')


def build_info(kind, asset):
    """build-info.json for a build: what it is, and which release file updates it."""
    commit = ''
    try:
        commit = os.environ.get('GITHUB_SHA') or _git('rev-parse', 'HEAD')
    except (OSError, subprocess.SubprocessError):
        pass
    return json.dumps({
        'version': version(), 'kind': kind, 'asset': asset, 'commit': commit,
        'repository': os.environ.get('GITHUB_REPOSITORY') or updater.DEFAULT_REPOSITORY,
        'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }, indent=2).encode()

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
