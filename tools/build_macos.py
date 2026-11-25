#!/usr/bin/env python3
"""Build Retro Pocket's macOS apps: one for Apple Silicon Macs, one for Intel Macs.

    python tools/build_macos.py                 # both, into dist/
    python tools/build_macos.py --arch arm64    # Apple Silicon only (or x86_64: Intel)

Runs on macOS, Windows or Linux: every part is downloaded (pinned by size and
SHA-256, except the mGBA core's nightly build) and written straight into a zip
that keeps Unix permissions and symlinks, so the app works once unzipped on a
Mac. Each app is self-contained:

    Retro Pocket (Apple Silicon).app/Contents/
      Info.plist
      MacOS/RetroPocket          launcher script (the app's executable)
      MacOS/python3.12           relocatable CPython for this architecture
      Resources/python/          its standard library, pygame-ce and certifi
      Resources/app/             Retro Pocket, with its emulators in emulators/

Nothing in the app is signed by a developer, so macOS asks before the first
start (see README.md). Downloads are cached in build/cache/.
"""
import argparse
from dataclasses import dataclass
import datetime
import importlib.util
from pathlib import Path, PurePosixPath
import plistlib
import posixpath
import stat
import struct
import sys
import tarfile
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install_emulators as emulators  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / 'build' / 'cache'
VERSION = '1.0'

_PBS = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261124/'
PYTHON = {
    'arm64': (_PBS + 'cpython-3.12.16%2B20261124-aarch64-apple-darwin-install_only.tar.gz', 25399370,
              '431b99a9c2cdd37ad9b06e425be0e520d2dbce0552abe454257abef592fe3634'),
    'x86_64': (_PBS + 'cpython-3.12.16%2B20261124-x86_64-apple-darwin-install_only.tar.gz', 25113881,
               'ccce24cfd3f56f62561d2c9480fcc567ca3a9bac68450cd73e11aeb631befa1f'),
}
_PYPI = 'https://files.pythonhosted.org/packages/'
WHEELS = [  # Universal (or pure Python) wheels, the same in both apps.
    (_PYPI + '57/a7/cd305034f505bfa1a1acdafd3d86af54da14b29151a0d99f348306272773/'
     'pygame_ce-2.5.7-cp312-cp312-macosx_10_13_universal2.whl', 17210332,
     'dca2f8ba56bf3b4b8c73c4863d0603773403f4f66bc2fe25784ea74aee3fffc3'),
    (_PYPI + '6d/39/5eec3296860b94ac20bb8ed807725b88f6adfab3f343df592afd975f5f86/'
     'certifi-2026.11.20-py3-none-any.whl', 127913,
     '7422df25243767b9877031a2248cb14d09ddac9beee846f4cef3d5c9191d488f'),
]


@dataclass(frozen=True)
class Target:
    arch: str
    label: str          # In the app's name
    slug: str           # In the zip's name
    minimum: str        # LSMinimumSystemVersion: what Python and pygame-ce need
    packages: str       # install_emulators platform


TARGETS = {
    'arm64': Target('arm64', 'Apple Silicon', 'Apple-Silicon', '11.0', 'macos-arm64'),
    'x86_64': Target('x86_64', 'Intel', 'Intel', '10.15', 'macos-x86_64'),
}

# Retro Pocket's own files in the app: the program and its catalogue.
APP_FILES = ('*.py', 'catalog*.json', 'covers-index.json', 'README.md', 'SOURCES*.md')
APP_EXCLUDE = {'_win32.py'}  # Windows only
# Parts of the standalone Python the app doesn't use. MacOS/python3.12 has
# libpython built in, and no extension module links the separate library.
PYTHON_EXCLUDE = ('bin/', 'include/', 'share/', 'lib/libpython3.12.dylib', 'lib/pkgconfig/',
                  'lib/python3.12/config-3.12-darwin/', 'lib/python3.12/test/', 'lib/python3.12/idlelib/',
                  'lib/python3.12/turtledemo/', 'lib/python3.12/ensurepip/_bundled/',
                  'lib/python3.12/site-packages/pip/', 'lib/python3.12/site-packages/pip-')
SITE_PACKAGES = 'Contents/Resources/python/lib/python3.12/site-packages/'
WHEEL_EXCLUDE = ('pygame/docs/', 'pygame/examples/', 'pygame/tests/')

LAUNCHER = r'''#!/bin/sh
# Retro Pocket for macOS ({label}): starts the game library with the Python
# inside this app. Built by tools/build_macos.py.
CONTENTS="$(cd "$(dirname "$0")/.." && pwd -P)"
APP="$(dirname "$CONTENTS")"
RESOURCES="$CONTENTS/Resources"

alert() {{
  /usr/bin/osascript -e 'on run argv' -e 'display alert "Retro Pocket" message (item 1 of argv) as critical' \
    -e 'end run' "$1" >/dev/null 2>&1
}}

ARM64_MAC="$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || echo 0)"
if [ "{arch}" = arm64 ] && [ "$ARM64_MAC" != 1 ]; then
  alert "This is Retro Pocket for Apple Silicon Macs. On this Mac, use Retro Pocket (Intel)."
  exit 1
fi
if [ "{arch}" = x86_64 ] && [ "$ARM64_MAC" = 1 ] && ! /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null; then
  alert "This is Retro Pocket for Intel Macs, which needs Rosetta on this Mac. Use Retro Pocket (Apple Silicon), or install Rosetta: in Terminal, run  softwareupdate --install-rosetta"
  exit 1
fi

# A browser or AirDrop marks downloads as quarantined, and macOS would ask
# again for each program inside. Once the app itself has been allowed to open,
# lift the mark from what it contains.
/usr/bin/xattr -dr com.apple.quarantine "$APP" 2>/dev/null

export PYTHONHOME="$RESOURCES/python"
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
export SSL_CERT_FILE="$RESOURCES/python/lib/python3.12/site-packages/certifi/cacert.pem"
export RETRO_POCKET_WINDOWLESS=1
# Game dumps go in ~/Retro Pocket/roms unless RETRO_POCKET_ROMS says otherwise.
RETRO_POCKET_ROMS="${{RETRO_POCKET_ROMS:-$HOME/Retro Pocket/roms}}"
export RETRO_POCKET_ROMS
/bin/mkdir -p "$RETRO_POCKET_ROMS" 2>/dev/null

# Finder on old macOS versions adds a -psn_ argument; drop it.
for argument in "$@"; do
  shift
  case "$argument" in -psn_*) ;; *) set -- "$@" "$argument" ;; esac
done
exec "$CONTENTS/MacOS/python3.12" "$RESOURCES/app/app.py" "$@"
'''


class AppZip:
    """A zip of one .app, with Unix permissions and symlinks as macOS restores them."""

    def __init__(self, path: Path, app: str):
        self.zip = zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6)
        self.app = app
        self.names = set()
        self.stamp = time.localtime()[:6]

    def _info(self, name, kind, mode):
        name = f'{self.app}/{name}'
        if name in self.names:
            raise ValueError(f'Two files at {name}')
        self.names.add(name)
        info = zipfile.ZipInfo(name, self.stamp)
        info.create_system = 3  # Unix: Archive Utility and ditto apply external_attr
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
    """Bytecode that needs no timestamp check (the app's files never change), or None."""
    if sys.version_info[:2] != (3, 12):
        return None  # Bytecode is per Python version: the app's Python compiles at run time instead.
    from importlib._bootstrap_external import _code_to_hash_pyc
    try:
        code = compile(source, name, 'exec', dont_inherit=True)
    except (SyntaxError, ValueError):
        return None
    return _code_to_hash_pyc(code, importlib.util.source_hash(source), checked=False)


def add_python_file(out: AppZip, name: str, data: bytes, mode: int):
    out.file(name, data, mode)
    if name.endswith('.py'):
        compiled = pyc(data, name)
        if compiled is not None:
            path = PurePosixPath(name)
            out.file(str(path.parent / '__pycache__' / f'{path.stem}.cpython-312.pyc'), compiled)


def add_python(out: AppZip, archive: Path):
    """The standalone CPython: its program in MacOS/, everything else in Resources/python/."""
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            if path.parts[0] != 'python' or member.isdir():
                continue
            relative = str(PurePosixPath(*path.parts[1:]))
            if relative == 'bin/python3.12':
                out.file('Contents/MacOS/python3.12', tar.extractfile(member).read(), 0o755)
                continue
            if relative.startswith(PYTHON_EXCLUDE) or '/__pycache__/' in f'/{relative}':
                continue
            name = f'Contents/Resources/python/{relative}'
            if member.issym():
                out.link(name, member.linkname)
            elif member.isfile() or member.islnk():
                add_python_file(out, name, tar.extractfile(member).read(), stat.S_IMODE(member.mode) or 0o644)


def add_wheel(out: AppZip, wheel: Path):
    with zipfile.ZipFile(wheel) as archive:
        for info in archive.infolist():
            if info.is_dir() or '.data/' in info.filename or info.filename.startswith(WHEEL_EXCLUDE):
                continue
            unix = stat.S_IMODE(info.external_attr >> 16) if info.create_system == 3 else 0
            add_python_file(out, SITE_PACKAGES + info.filename, archive.read(info), unix or 0o644)


def add_emulators(out: AppZip, target: Target):
    for name, package in emulators.PLATFORMS[target.packages].items():
        archive_path, digest = emulators.cached(package.url, package.size, package.sha256, CACHE)
        if package.sha256 is None:
            print(f'  {name}: unpinned nightly build, SHA-256 {digest}')
        base = f'Contents/Resources/app/emulators/{name}'
        found = False
        with zipfile.ZipFile(archive_path) as archive:
            for entry in emulators.entries(archive):
                path = f'{base}/{entry.path}'
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
        out.file(f'{base}/{emulators.MARKER}', (package.sha256 or digest).encode())


def add_retro_pocket(out: AppZip):
    for pattern in APP_FILES:
        for path in sorted(ROOT.glob(pattern)):
            if path.name not in APP_EXCLUDE and path.is_file():
                add_python_file(out, f'Contents/Resources/app/{path.name}', path.read_bytes(), 0o644)


def info_plist(target: Target):
    return plistlib.dumps({
        'CFBundleName': 'Retro Pocket',
        'CFBundleDisplayName': 'Retro Pocket',
        'CFBundleIdentifier': 'local.retropocket.RetroPocket',
        'CFBundleExecutable': 'RetroPocket',
        'CFBundlePackageType': 'APPL',
        'CFBundleInfoDictionaryVersion': '6.0',
        'CFBundleShortVersionString': VERSION,
        'CFBundleVersion': datetime.date.today().strftime('%Y.%m.%d'),
        'LSMinimumSystemVersion': target.minimum,
        'LSArchitecturePriority': [target.arch],
        'LSApplicationCategoryType': 'public.app-category.games',
        'NSHighResolutionCapable': True,
        'NSHumanReadableCopyright': 'Retro Pocket. Emulators are their authors\' work, under their own licences.',
    })


REQUIRED = {  # path in the app: must be executable
    'Contents/Info.plist': False, 'Contents/MacOS/RetroPocket': True, 'Contents/MacOS/python3.12': True,
    'Contents/Resources/python/lib/python3.12/os.py': False,
    SITE_PACKAGES + 'pygame/__init__.py': False, SITE_PACKAGES + 'certifi/cacert.pem': False,
    'Contents/Resources/app/app.py': False, 'Contents/Resources/app/catalog.json': False,
}


def _slices(data: bytes):
    """(architecture, signed) for each slice of a Mach-O file; [] for anything else."""
    cpus = {0x01000007: 'x86_64', 0x0100000c: 'arm64'}
    magic, = struct.unpack_from('>I', data, 0)
    if magic in (0xcafebabe, 0xcafebabf):
        count, = struct.unpack_from('>I', data, 4)
        if not 0 < count < 10:
            return []
        size = 20 if magic == 0xcafebabe else 32
        offsets = [struct.unpack_from('>Q' if size == 32 else '>I', data, 8 + i * size + 8)[0] for i in range(count)]
        return [s for offset in offsets for s in _slices(data[offset:])]
    if data[:4] not in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe'):
        return []
    cpu, _, _, ncmds = struct.unpack_from('<IIII', data, 4)
    position, signed = (32 if data[:4] == b'\xcf\xfa\xed\xfe' else 28), False
    for _ in range(ncmds):
        command, size = struct.unpack_from('<II', data, position)
        signed |= command == 0x1d  # LC_CODE_SIGNATURE
        position += size
    return [(cpus.get(cpu, hex(cpu)), signed)]


def verify(zip_path: Path, target: Target):
    """Check the app as a Mac will see it once unzipped; raises ValueError with every problem found."""
    problems = []
    with zipfile.ZipFile(zip_path) as archive:
        infos = {info.filename: info for info in archive.infolist()}
        app = next(iter(infos)).split('/')[0]
        modes = {name[len(app) + 1:]: info.external_attr >> 16 for name, info in infos.items()}
        for name, executable in REQUIRED.items():
            if name not in modes:
                problems.append(f'missing {name}')
            elif executable and not modes[name] & 0o111:
                problems.append(f'not executable: {name}')
        names = set(modes)
        folders = {str(PurePosixPath(name).parents[i]) for name in names for i in range(len(PurePosixPath(name).parts))}
        links = {name: archive.read(f'{app}/{name}').decode() for name, mode in modes.items() if stat.S_ISLNK(mode)}

        def resolve(path, depth=0):
            parts = PurePosixPath(path).parts
            for index in range(1, len(parts) + 1):
                prefix = '/'.join(parts[:index])
                if prefix in links and depth < 10:
                    base = posixpath.normpath(posixpath.join(posixpath.dirname(prefix), links[prefix]))
                    return resolve('/'.join((base, *parts[index:])), depth + 1)
            return path
        problems += [f'broken link: {name}' for name in links if resolve(name) not in names | folders]
        for name, mode in modes.items():
            info = infos[f'{app}/{name}']
            if stat.S_ISLNK(mode) or info.file_size < 64:
                continue
            with archive.open(info) as file:
                if file.read(4) not in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf', b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe'):
                    continue
            slices = [s for s in _slices(archive.read(info)) if s[0] == target.arch]
            if not slices:
                problems.append(f'no {target.arch} code: {name}')
            elif target.arch == 'arm64' and not slices[0][1]:
                problems.append(f'unsigned arm64 code (Apple Silicon refuses it): {name}')
            elif '/MacOS/' in f'/{name}' and not mode & 0o111:
                problems.append(f'program not executable: {name}')
    if problems:
        raise ValueError(f'{zip_path.name}:\n  ' + '\n  '.join(problems[:20]))


def build(target: Target, output: Path):
    app = f'Retro Pocket ({target.label}).app'
    zip_path = output / f'Retro-Pocket-macOS-{target.slug}.zip'
    output.mkdir(parents=True, exist_ok=True)
    print(f'{app}:')
    url, size, sha256 = PYTHON[target.arch]
    python, _ = emulators.cached(url, size, sha256, CACHE)
    wheels = [emulators.cached(url, size, sha256, CACHE)[0] for url, size, sha256 in WHEELS]
    partial = zip_path.with_name(zip_path.name + '.part')
    out = AppZip(partial, app)
    try:
        out.file('Contents/Info.plist', info_plist(target))
        out.file('Contents/PkgInfo', b'APPL????')
        out.file('Contents/MacOS/RetroPocket', LAUNCHER.format(arch=target.arch, label=target.label).encode(), 0o755)
        add_python(out, python)
        for wheel in wheels:
            add_wheel(out, wheel)
        add_retro_pocket(out)
        add_emulators(out, target)
    finally:
        out.close()
    verify(partial, target)
    partial.replace(zip_path)
    print(f'  {zip_path} ({zip_path.stat().st_size // (1024 * 1024)} MB, {len(out.names)} files, checked)')
    return zip_path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the macOS apps (Apple Silicon and Intel).')
    parser.add_argument('--arch', choices=[*TARGETS, 'both'], default='both')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args(argv)
    targets = list(TARGETS.values()) if args.arch == 'both' else [TARGETS[args.arch]]
    for target in targets:
        build(target, args.output.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
