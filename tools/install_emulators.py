#!/usr/bin/env python3
"""Install the emulators Retro Pocket uses on Windows and macOS into emulators/ beside app.py.

Each archive is an official release, pinned by URL, size and SHA-256, and
unpacked into its own folder. The mGBA libretro core comes from the libretro
buildbot's current build (it has no pinned release), so it is checked to be a
library for this computer and its SHA-256 is printed. Run it again to repair
or update; installed packages whose archive digest is unchanged are skipped.
Linux uses its distribution's packages instead (see README.md).

Only emulators are installed. ROMs, BIOS and firmware files and console keys
are never downloaded. Usage (setup.cmd and setup.command run it):

    python tools/install_emulators.py              # everything for this computer
    python tools/install_emulators.py desmume      # one package
    python tools/install_emulators.py --mgba-core /path/to/mgba_libretro.dll
"""
import argparse
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import platform
import posixpath
import shutil
import stat
import struct
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EMULATORS = ROOT / 'emulators'
MARKER = '.retro-pocket-package'
AGENT = {'User-Agent': 'retro-pocket-setup'}
BUILDBOT = 'https://buildbot.libretro.com/nightly'
GITHUB = 'https://github.com'


@dataclass(frozen=True)
class Package:
    what: str
    url: str
    sha256: str | None  # None: an unpinned nightly build, checked by its contents instead
    size: int | None
    check: str          # The program or library, relative to the package folder
    arch: str | None = None  # The architecture check's library must contain


def _mgba(url, check, arch):
    return Package('mGBA libretro core (Game Boy, Game Boy Color, Game Boy Advance)',
                   url, None, None, check, arch)


_WINDOWS = {
    'mgba': _mgba(f'{BUILDBOT}/windows/x86_64/latest/mgba_libretro.dll.zip', 'mgba_libretro.dll', 'x86_64'),
    'desmume': Package(
        'DeSmuME 0.9.13 (Nintendo DS)',
        f'{GITHUB}/TASEmulators/desmume/releases/download/release_0_9_13/desmume-0.9.13-win64.zip',
        'cbf710b8e6b29f0904e289a9b9a895548a2d7c7af5a3145c8279b97a69a09276', 6086795,
        'DeSmuME_0.9.13_x64.exe'),
    'mupen64plus': Package(
        'Mupen64Plus 2.6.0 (Nintendo 64)',
        f'{GITHUB}/mupen64plus/mupen64plus-core/releases/download/2.6.0/mupen64plus-bundle-win64-2.6.0.zip',
        '8292c68d6ffc3428d4181ac09b1368ef2adb2cc568325545aac78cb6c1e66e21', 2721037,
        'mupen64plus-ui-console.exe'),
    'azahar': Package(
        'Azahar 2127.0.1 (Nintendo 3DS)',
        f'{GITHUB}/azahar-emu/azahar/releases/download/2127.0.1/azahar-windows-msvc-2127.0.1.zip',
        '0ea6107f54d0a16390bd520a3626b5bb89f1b07ab6d2e9c1d1e8d95e484c837e', 53741164,
        'azahar.exe'),
}

# melonDS and ares publish universal builds (Apple Silicon and Intel in one
# program); mGBA's core and Azahar come in one build per architecture.
_MACOS_SHARED = {
    'melonds': Package(
        'melonDS 1.1 (Nintendo DS)',
        f'{GITHUB}/melonDS-emu/melonDS/releases/download/1.1/melonDS-1.1-macOS-universal.zip',
        '79843a5e5cab93188bd11942bff5440b9505ee91c6f526f7e90c22e3cff6718d', 24378474,
        'melonDS.app/Contents/MacOS/melonDS'),
    'ares': Package(
        'ares v148 (Nintendo 64)',
        f'{GITHUB}/ares-emulator/ares/releases/download/v148/ares-macos-universal.zip',
        '1ae232ab6de341210f171f51d84b311527eb1399060706589334a8a7de136bb0', 79914130,
        'ares.app/Contents/MacOS/ares'),
}
_AZAHAR_MACOS = f'{GITHUB}/azahar-emu/azahar/releases/download/2127.0.1/azahar-macos-{{}}-2127.0.1.zip'
_MACOS_ARM64 = {
    'mgba': _mgba(f'{BUILDBOT}/apple/osx/arm64/latest/mgba_libretro.dylib.zip', 'mgba_libretro.dylib', 'arm64'),
    **_MACOS_SHARED,
    'azahar': Package(
        'Azahar 2127.0.1 (Nintendo 3DS, macOS 13.4 or later)', _AZAHAR_MACOS.format('arm64'),
        '20bc20f5c71e2c10c55876a23e46b77a05af7f93665cddd68eb4d2b8cdc97482', 114416989,
        'Azahar.app/Contents/MacOS/azahar', 'arm64'),
}
_MACOS_X86_64 = {
    'mgba': _mgba(f'{BUILDBOT}/apple/osx/x86_64/latest/mgba_libretro.dylib.zip', 'mgba_libretro.dylib', 'x86_64'),
    **_MACOS_SHARED,
    'azahar': Package(
        'Azahar 2127.0.1 (Nintendo 3DS, macOS 13.4 or later)', _AZAHAR_MACOS.format('x86_64'),
        'dfcffc38877f2e80807d28fb169d0ebc7024d4bbb7283e80affaac571973d208', 102011356,
        'Azahar.app/Contents/MacOS/azahar', 'x86_64'),
}
PLATFORMS = {'windows-x86_64': _WINDOWS, 'macos-arm64': _MACOS_ARM64, 'macos-x86_64': _MACOS_X86_64}


def host_platform():
    """This computer's package set, or None (Linux uses distribution packages)."""
    machine = platform.machine().lower()
    if sys.platform == 'win32' and machine in ('amd64', 'x86_64'):
        return 'windows-x86_64'
    if sys.platform == 'darwin':
        return 'macos-arm64' if machine == 'arm64' else 'macos-x86_64'
    return None


# ----- Downloads -------------------------------------------------------------

def _https():
    try:  # Python on macOS doesn't use the system's certificate store.
        import certifi
        import ssl
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return None


def download(url, size, target, sha256=None):
    """Fetch ``url`` into ``target``; check its size and SHA-256 when pinned. Returns the SHA-256."""
    limit = (size or 512 * 1024 * 1024) + 1
    digest = hashlib.sha256()
    received = 0
    request = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(request, timeout=60, context=_https()) as response, open(target, 'wb') as output:
        while chunk := response.read(1024 * 1024):
            received += len(chunk)
            if received > limit:
                raise ValueError(f'{url} is larger than expected')
            digest.update(chunk)
            output.write(chunk)
    if size is not None and received != size:
        raise ValueError(f'{url}: expected {size} bytes, received {received}')
    if sha256 is not None and digest.hexdigest() != sha256:
        raise ValueError(f'{url}: SHA-256 {digest.hexdigest()} does not match the pinned {sha256}')
    return digest.hexdigest()


def cached(url, size, sha256, cache: Path):
    """A pinned download kept in ``cache`` (checked again on reuse); unpinned files are fetched anew."""
    cache.mkdir(parents=True, exist_ok=True)
    name = url.rsplit('/', 1)[-1]
    path = cache / (name if sha256 else f'{hashlib.sha256(url.encode()).hexdigest()[:12]}-{name}')
    if sha256 and path.is_file():
        if path.stat().st_size == size and hashlib.sha256(path.read_bytes()).hexdigest() == sha256:
            return path, sha256
    partial = path.with_name(path.name + '.part')
    digest = download(url, size, partial, sha256)
    os.replace(partial, path)
    return path, digest


# ----- Archives --------------------------------------------------------------

@dataclass
class Entry:
    path: PurePosixPath   # Inside the package folder
    mode: int             # Permission bits
    link: str | None      # Symlink target, or None for a file
    info: zipfile.ZipInfo


def entries(archive: zipfile.ZipFile):
    """Archive members with the single top-level folder removed (unless it is an .app); unsafe names refused."""
    infos = [info for info in archive.infolist() if not info.is_dir()]
    paths = [PurePosixPath(info.filename.replace('\\', '/')) for info in infos]
    for path in paths:
        if path.is_absolute() or '..' in path.parts or ':' in str(path):
            raise ValueError(f'Unsafe path in archive: {path}')
    tops = {path.parts[0] for path in paths}
    strip = (len(tops) == 1 and all(len(path.parts) > 1 for path in paths)
             and not next(iter(tops)).endswith('.app'))
    result = []
    for info, path in zip(infos, paths):
        unix = info.external_attr >> 16 if info.create_system == 3 else 0
        link = None
        if stat.S_ISLNK(unix):
            link = archive.read(info).decode('utf-8')
            if link.startswith('/') or '\\' in link:
                raise ValueError(f'Unsafe link in archive: {path} -> {link}')
        mode = stat.S_IMODE(unix) or 0o644
        result.append(Entry(PurePosixPath(*path.parts[1:]) if strip else path, mode, link, info))
    for entry in result:  # A link must stay inside the package.
        if entry.link and '..' in PurePosixPath(posixpath.normpath(str(entry.path.parent / entry.link))).parts:
            raise ValueError(f'Link leaves the package: {entry.path} -> {entry.link}')
    return result


def extract(archive_path: Path, target: Path):
    with zipfile.ZipFile(archive_path) as archive:
        for entry in entries(archive):
            destination = target.joinpath(*entry.path.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if entry.link is not None:
                os.symlink(entry.link, destination)  # macOS app bundles use relative links
                continue
            with archive.open(entry.info) as source, open(destination, 'wb') as output:
                shutil.copyfileobj(source, output)
            if os.name != 'nt':
                destination.chmod(entry.mode)


# ----- Checks ----------------------------------------------------------------

_MACHO_CPUS = {0x01000007: 'x86_64', 0x0100000c: 'arm64'}


def architectures(path):
    """The CPU architectures in a Windows (PE) or macOS (Mach-O) program or library."""
    with open(path, 'rb') as file:
        return header_architectures(file.read(4096))


def header_architectures(header: bytes):
    """architectures() for the first bytes of a file."""
    if len(header) < 8:
        return set()
    if header[:2] == b'MZ' and len(header) >= 0x40:
        offset, = struct.unpack_from('<I', header, 0x3C)
        if offset + 6 <= len(header) and header[offset:offset + 4] == b'PE\0\0':
            machine, = struct.unpack_from('<H', header, offset + 4)
            return {{0x8664: 'x86_64', 0xAA64: 'arm64'}.get(machine, hex(machine))}
        return set()
    magic, = struct.unpack_from('>I', header, 0)
    if magic in (0xcafebabe, 0xcafebabf):  # Universal: one slice per architecture
        count, = struct.unpack_from('>I', header, 4)
        size = 20 if magic == 0xcafebabe else 32
        cpus = [struct.unpack_from('>I', header, 8 + i * size)[0] for i in range(min(count, 8))]
        return {_MACHO_CPUS.get(cpu, hex(cpu)) for cpu in cpus}
    if header[:4] in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe'):
        cpu, = struct.unpack_from('<I', header, 4)
        return {_MACHO_CPUS.get(cpu, hex(cpu))}
    return set()


# ----- Installing ------------------------------------------------------------

def install(name, package, force=False):
    target = EMULATORS / name
    marker = target / MARKER
    if not force and marker.is_file() and (target / package.check).is_file() and (
            package.sha256 is None or marker.read_text(encoding='ascii').strip() == package.sha256):
        update = ' (--force downloads the current build)' if package.sha256 is None else ''
        print(f'{name}: already installed ({package.what}){update}')
        return target
    EMULATORS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{name}-', dir=EMULATORS) as scratch:
        scratch = Path(scratch)
        archive_path = scratch / 'download.zip'
        print(f'{name}: downloading {package.what}')
        digest = download(package.url, package.size, archive_path, package.sha256)
        unpacked = scratch / name
        extract(archive_path, unpacked)
        program = unpacked / package.check
        if not program.is_file():
            raise ValueError(f'{name}: the archive has no {package.check}')
        if package.arch and package.arch not in architectures(program):
            raise ValueError(f'{name}: {package.check} is not built for {package.arch}')
        (unpacked / MARKER).write_text(package.sha256 or digest, encoding='ascii')
        replace(unpacked, target)
    if not package.sha256:
        print(f'{name}: SHA-256 of the archive is {digest} (unpinned nightly build)')
    print(f'{name}: installed in {target}')
    return target


def replace(new, target):
    """Swap in a fresh folder, keeping the old one until the new one is in place."""
    old = target.with_name(f'.{target.name}.old')
    if old.exists():
        shutil.rmtree(old)
    if target.exists():
        target.rename(old)
    try:
        new.rename(target)
    except OSError:
        if old.exists():
            old.rename(target)
        raise
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)


def install_local_core(path, package):
    path = Path(path).expanduser().resolve()
    if not path.is_file() or package.arch not in architectures(path):
        raise ValueError(f'{path} is not an mGBA core for this computer ({package.arch})')
    target = EMULATORS / 'mgba' / package.check
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    print(f'mgba: copied {path} to {target}')


def main(argv=None):
    host = host_platform()
    choices = PLATFORMS.get(host, {})
    parser = argparse.ArgumentParser(description='Install Retro Pocket\'s emulators into emulators/')
    parser.add_argument('packages', nargs='*', metavar='package',
                        help=f'what to install (default: all of {", ".join(choices) or "none here"})')
    parser.add_argument('--force', action='store_true', help='download again even if installed')
    parser.add_argument('--mgba-core', help='use this mGBA libretro core instead of downloading one')
    args = parser.parse_args(argv)
    if host is None:
        print('This installer is for Windows and macOS; on Linux use the distribution packages in README.md.',
              file=sys.stderr)
        return 2
    unknown = [name for name in args.packages if name not in choices]
    if unknown:
        parser.error(f'unknown package {", ".join(unknown)}; choose from {", ".join(choices)}')
    failed = []
    for name in args.packages or list(choices):
        try:
            if name == 'mgba' and args.mgba_core:
                install_local_core(args.mgba_core, choices[name])
            else:
                install(name, choices[name], args.force)
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            print(f'{name}: FAILED: {exc}', file=sys.stderr)
            failed.append(name)
    if failed:
        print(f'Not installed: {", ".join(failed)}', file=sys.stderr)
        return 1
    print('Done. GameCube/Wii (Dolphin) and Pokémon mini (PokeMini) are not installed '
          'automatically; see README.md.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
