#!/usr/bin/env python3
"""Build Retro Pocket for Windows: one folder with everything in it, zipped.

    python tools/build_windows.py            # dist/Retro-Pocket-Windows.zip

Runs on any OS. Every part is downloaded (pinned by size and SHA-256, except
the mGBA core's nightly build) and written straight into the zip:

    Retro Pocket/
      Retro Pocket.cmd     starts the library (no console window)
      app.py ...           Retro Pocket and its catalogue
      python/              relocatable CPython 3.12 with pygame-ce
      emulators/           mGBA core, DeSmuME, Mupen64Plus, Azahar
      roms/                put your game dumps here

Unzip it anywhere and double-click "Retro Pocket.cmd": no Python, setup or
administrator rights needed. Downloads are cached in build/cache/.
"""
import argparse
from pathlib import Path, PurePosixPath
import struct
import sys
import tarfile
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bundle  # noqa: E402
import install_emulators as emulators  # noqa: E402

FOLDER = 'Retro Pocket'
ZIP_NAME = 'Retro-Pocket-Windows.zip'
PYTHON = ('https://github.com/astral-sh/python-build-standalone/releases/download/20261124/'
          'cpython-3.12.16%2B20261124-x86_64-pc-windows-msvc-install_only.tar.gz', 47497711,
          '8152ff5b6c6c044ddbbaa3531dda59cb9ce5bd6cb670d4c9ac2e3ab91afa8778')
WHEELS = [
    ('https://files.pythonhosted.org/packages/1f/d4/43b006affa13e2f4572aa28a0d1f64c91c330d289c30a022b5416245714c/'
     'pygame_ce-2.5.7-cp312-cp312-win_amd64.whl', 10414958,
     'b6b7eec2779fac11ed265a18ab926b3829654120a5c9a07c36eeedeb012b8c3c'),
]
SITE_PACKAGES = 'python/Lib/site-packages/'
# Parts of the standalone Python Retro Pocket doesn't use.
PYTHON_EXCLUDE = ('include/', 'libs/', 'Scripts/', 'tcl/', 'Lib/test/', 'Lib/idlelib/', 'Lib/turtledemo/',
                  'Lib/tkinter/', 'Lib/ensurepip/_bundled/', 'Lib/site-packages/pip/', 'Lib/site-packages/pip-')
LAUNCHER = ('@echo off\r\n'
            'rem Start Retro Pocket without a console window. Options are passed on (see app.py --help).\r\n'
            'start "" "%~dp0python\\pythonw.exe" "%~dp0app.py" %*\r\n')
REQUIRED = ('Retro Pocket.cmd', 'app.py', '_win32.py', 'updater.py', 'build-info.json', 'catalog.json',
            'python/python.exe', 'python/pythonw.exe',
            'python/Lib/os.py', SITE_PACKAGES + 'pygame/__init__.py', 'roms/README.txt',
            *(f'emulators/{name}/{package.check}' for name, package in emulators.PLATFORMS['windows-x86_64'].items()))


def add_python(out: bundle.Archive, archive: Path):
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            if path.parts[0] != 'python' or member.isdir():
                continue
            relative = str(PurePosixPath(*path.parts[1:]))
            if relative.startswith(PYTHON_EXCLUDE) or '/__pycache__/' in f'/{relative}':
                continue
            if member.isfile() or member.islnk():
                bundle.add_python_file(out, f'python/{relative}', tar.extractfile(member).read())


def _pe_machine(header: bytes):
    if header[:2] != b'MZ' or len(header) < 0x40:
        return None
    offset, = struct.unpack_from('<I', header, 0x3C)
    if offset + 6 > len(header) or header[offset:offset + 4] != b'PE\0\0':
        return None
    return struct.unpack_from('<H', header, offset + 4)[0]


def verify(zip_path: Path):
    """Everything is in place, and every program and library is 64-bit x86 Windows code."""
    problems = []
    with zipfile.ZipFile(zip_path) as archive:
        names = {info.filename[len(FOLDER) + 1:]: info for info in archive.infolist()}
        problems += [f'missing {name}' for name in REQUIRED if name not in names]
        for name, info in names.items():
            if name.lower().endswith(('.exe', '.dll', '.pyd')):
                with archive.open(info) as file:
                    machine = _pe_machine(file.read(4096))
                if machine != 0x8664:
                    problems.append(f'not a 64-bit x86 Windows binary: {name}')
    if problems:
        raise ValueError(f'{zip_path.name}:\n  ' + '\n  '.join(problems[:20]))


def build(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    zip_path = output / ZIP_NAME
    print(f'{FOLDER} {bundle.version()} (Windows):')
    python, _ = emulators.cached(*PYTHON, bundle.CACHE)
    wheels = [emulators.cached(url, size, sha256, bundle.CACHE)[0] for url, size, sha256 in WHEELS]
    partial = zip_path.with_name(zip_path.name + '.part')
    out = bundle.Archive(partial, FOLDER)
    try:
        out.file('Retro Pocket.cmd', LAUNCHER.encode())
        out.file('build-info.json', bundle.build_info('windows', ZIP_NAME))
        out.file('roms/README.txt', bundle.ROMS_README.replace('\n', '\r\n').encode())
        for name, path in bundle.retro_pocket_files():
            bundle.add_python_file(out, name, path.read_bytes())
        add_python(out, python)
        for wheel in wheels:
            bundle.add_wheel(out, wheel, SITE_PACKAGES, bundle.PYGAME_EXCLUDE)
        bundle.add_emulators(out, 'windows-x86_64', 'emulators')
    finally:
        out.close()
    verify(partial)
    partial.replace(zip_path)
    print(f'  {zip_path} ({zip_path.stat().st_size // (1024 * 1024)} MB, {len(out.names)} files, checked)')
    return zip_path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the self-contained Windows version.')
    parser.add_argument('--output', type=Path, default=bundle.ROOT / 'dist')
    build(parser.parse_args(argv).output.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
