#!/usr/bin/env python3
"""Build Retro Pocket for Linux: a tarball to unpack and set up with the distribution's emulators.

    python tools/build_linux.py              # dist/Retro-Pocket-Linux.tar.gz

    retro-pocket/
      setup.sh            Python environment with pygame-ce; names missing emulator packages
      RetroPocket.sh      starts the library
      app.py ...          Retro Pocket, its catalogue, and the DeSmuME keyboard fix's source
      roms/               put your game dumps here

Linux distributions package the emulators (libretro-mgba, desmume,
mupen64plus), so unlike the Windows and macOS builds this one doesn't carry
them, or its own Python. Runs on any OS.
"""
import argparse
import io
from pathlib import Path
import sys
import tarfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bundle  # noqa: E402

FOLDER = 'retro-pocket'
TAR_NAME = 'Retro-Pocket-Linux.tar.gz'
EXECUTABLE = {'setup.sh', 'RetroPocket.sh'}
EXTRA = ('ds_input_shim.c', 'requirements.txt', 'setup.sh', 'RetroPocket.sh')
REQUIRED = ('app.py', 'updater.py', 'build-info.json', 'catalog.json', 'ds_input_shim.c', 'requirements.txt',
            'setup.sh', 'RetroPocket.sh', 'roms/README.txt')


def _add(tar, name, data: bytes, mode):
    info = tarfile.TarInfo(f'{FOLDER}/{name}')
    info.size, info.mode, info.mtime = len(data), mode, int(time.time())
    tar.addfile(info, io.BytesIO(data))


def verify(path: Path):
    with tarfile.open(path) as tar:
        members = {member.name[len(FOLDER) + 1:]: member for member in tar.getmembers()}
    problems = [f'missing {name}' for name in REQUIRED if name not in members]
    problems += [f'not executable: {name}' for name in EXECUTABLE if name in members and not members[name].mode & 0o111]
    problems += [f'Windows line endings would break {name}' for name in EXECUTABLE
                 if b'\r' in (bundle.ROOT / name).read_bytes()]
    if problems:
        raise ValueError(f'{path.name}:\n  ' + '\n  '.join(problems))


def build(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    path = output / TAR_NAME
    partial = path.with_name(path.name + '.part')
    with tarfile.open(partial, 'w:gz') as tar:
        for name, source in bundle.retro_pocket_files(exclude={'_win32.py'}, extra=EXTRA):
            _add(tar, name, source.read_bytes(), 0o755 if name in EXECUTABLE else 0o644)
        _add(tar, 'build-info.json', bundle.build_info('linux', TAR_NAME), 0o644)
        _add(tar, 'roms/README.txt', bundle.ROMS_README.encode(), 0o644)
    verify(partial)
    partial.replace(path)
    print(f'retro-pocket {bundle.version()} (Linux): {path} ({path.stat().st_size // 1024} KB, checked)')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build the Linux tarball.')
    parser.add_argument('--output', type=Path, default=bundle.ROOT / 'dist')
    build(parser.parse_args(argv).output.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
