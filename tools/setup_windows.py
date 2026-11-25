#!/usr/bin/env python3
"""Install the emulators Retro Pocket uses on Windows into emulators\\ beside app.py.

Each archive is an official release, pinned by URL, size and SHA-256, and
extracted into its own folder. The mGBA libretro core comes from the libretro
buildbot's current Windows build (it has no pinned release), so it is checked
to be a 64-bit Windows DLL and its SHA-256 is printed. Run it again to repair
or update; installed packages whose archive digest is unchanged are skipped.

Only emulators are installed. ROMs, BIOS and firmware files and console keys
are never downloaded. Usage:

    .venv\\Scripts\\python tools\\setup_windows.py              # everything
    .venv\\Scripts\\python tools\\setup_windows.py desmume      # one package
    .venv\\Scripts\\python tools\\setup_windows.py --mgba-core C:\\path\\mgba_libretro.dll
"""
import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EMULATORS = ROOT / 'emulators'
MARKER = '.retro-pocket-package'
AGENT = {'User-Agent': 'retro-pocket-setup'}

PACKAGES = {
    'mgba': dict(
        what='mGBA libretro core (Game Boy, Game Boy Color, Game Boy Advance)',
        url='https://buildbot.libretro.com/nightly/windows/x86_64/latest/mgba_libretro.dll.zip',
        sha256=None, size=None, check='mgba_libretro.dll'),
    'desmume': dict(
        what='DeSmuME 0.9.13 (Nintendo DS)',
        url='https://github.com/TASEmulators/desmume/releases/download/release_0_9_13/desmume-0.9.13-win64.zip',
        sha256='cbf710b8e6b29f0904e289a9b9a895548a2d7c7af5a3145c8279b97a69a09276', size=6086795,
        check='DeSmuME_0.9.13_x64.exe'),
    'mupen64plus': dict(
        what='Mupen64Plus 2.6.0 (Nintendo 64)',
        url='https://github.com/mupen64plus/mupen64plus-core/releases/download/2.6.0/'
            'mupen64plus-bundle-win64-2.6.0.zip',
        sha256='8292c68d6ffc3428d4181ac09b1368ef2adb2cc568325545aac78cb6c1e66e21', size=2721037,
        check='mupen64plus-ui-console.exe'),
    'azahar': dict(
        what='Azahar 2127.0.1 (Nintendo 3DS)',
        url='https://github.com/azahar-emu/azahar/releases/download/2127.0.1/azahar-windows-msvc-2127.0.1.zip',
        sha256='0ea6107f54d0a16390bd520a3626b5bb89f1b07ab6d2e9c1d1e8d95e484c837e', size=53741164,
        check='azahar.exe'),
}


def download(url, size, target):
    limit = (size or 256 * 1024 * 1024) + 1
    digest = hashlib.sha256()
    received = 0
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=60) as response, \
            open(target, 'wb') as output:
        while chunk := response.read(1024 * 1024):
            received += len(chunk)
            if received > limit:
                raise ValueError(f'{url} is larger than expected')
            digest.update(chunk)
            output.write(chunk)
    if size is not None and received != size:
        raise ValueError(f'{url}: expected {size} bytes, received {received}')
    return digest.hexdigest()


def members(archive):
    """Archive entries with the single top-level folder (if any) removed; rejects unsafe names."""
    names = [info for info in archive.infolist() if not info.is_dir()]
    paths = [PurePosixPath(info.filename.replace('\\', '/')) for info in names]
    for path in paths:
        if path.is_absolute() or '..' in path.parts or ':' in str(path):
            raise ValueError(f'Unsafe path in archive: {path}')
    tops = {path.parts[0] for path in paths}
    strip = len(tops) == 1 and all(len(path.parts) > 1 for path in paths)
    return [(info, PurePosixPath(*path.parts[1:]) if strip else path) for info, path in zip(names, paths)]


def is_windows_dll(path):
    with open(path, 'rb') as file:
        header = file.read(4096)
    if header[:2] != b'MZ' or len(header) < 0x40:
        return False
    offset, = struct.unpack_from('<I', header, 0x3C)
    if offset + 6 > len(header) or header[offset:offset + 4] != b'PE\0\0':
        return False
    machine, = struct.unpack_from('<H', header, offset + 4)
    return machine == 0x8664  # x86-64


def install(name, package, force=False):
    target = EMULATORS / name
    marker = target / MARKER
    if not force and marker.is_file() and (target / package['check']).is_file() and (
            package['sha256'] is None or marker.read_text(encoding='ascii').strip() == package['sha256']):
        update = ' (--force downloads the current build)' if package['sha256'] is None else ''
        print(f'{name}: already installed ({package["what"]}){update}')
        return target
    EMULATORS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.{name}-', dir=EMULATORS) as scratch:
        scratch = Path(scratch)
        archive_path = scratch / 'download.zip'
        print(f'{name}: downloading {package["what"]}')
        digest = download(package['url'], package['size'], archive_path)
        if package['sha256'] and digest != package['sha256']:
            raise ValueError(f'{name}: SHA-256 {digest} does not match the pinned {package["sha256"]}')
        unpacked = scratch / name
        with zipfile.ZipFile(archive_path) as archive:
            for info, relative in members(archive):
                destination = unpacked.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(destination, 'wb') as output:
                    shutil.copyfileobj(source, output)
        if not (unpacked / package['check']).is_file():
            raise ValueError(f'{name}: the archive has no {package["check"]}')
        if name == 'mgba' and not is_windows_dll(unpacked / package['check']):
            raise ValueError('mgba: the download is not a 64-bit Windows DLL')
        (unpacked / MARKER).write_text(package['sha256'] or digest, encoding='ascii')
        replace(unpacked, target)
    if not package['sha256']:
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


def install_local_core(path):
    path = Path(path).expanduser().resolve()
    if not path.is_file() or not is_windows_dll(path):
        raise ValueError(f'{path} is not a 64-bit Windows DLL')
    target = EMULATORS / 'mgba' / 'mgba_libretro.dll'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    print(f'mgba: copied {path} to {target}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Install Retro Pocket\'s Windows emulators into emulators\\')
    parser.add_argument('packages', nargs='*', metavar='package',
                        help=f'what to install (default: all of {", ".join(PACKAGES)})')
    parser.add_argument('--force', action='store_true', help='download again even if installed')
    parser.add_argument('--mgba-core', help='use this mgba_libretro.dll instead of downloading one')
    args = parser.parse_args(argv)
    unknown = [name for name in args.packages if name not in PACKAGES]
    if unknown:
        parser.error(f'unknown package {", ".join(unknown)}; choose from {", ".join(PACKAGES)}')
    if os.name != 'nt':
        print('This installer is for Windows; on Linux use the distribution packages in README.md.',
              file=sys.stderr)
        return 2
    wanted = args.packages or list(PACKAGES)
    failed = []
    for name in wanted:
        try:
            if name == 'mgba' and args.mgba_core:
                install_local_core(args.mgba_core)
            else:
                install(name, PACKAGES[name], args.force)
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
