"""Launch native PokeMini with caller-verified raw cartridge bytes."""

import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile

import compat
from ds import _require_placed


if compat.WINDOWS:
    # PokeMini's Windows build is a portable folder; keep it in emulators\pokemini.
    _INSTALLED_EXECUTABLES = tuple(
        directory / 'PokeMini.exe'
        for directory in (compat.EMULATORS / 'pokemini', *(root / 'PokeMini' for root in compat.program_files())))
elif compat.MACOS:
    # No official macOS build: a native SDL2 build in emulators/pokemini or on Homebrew's prefix.
    _INSTALLED_EXECUTABLES = tuple(
        Path(directory) / name
        for directory in (compat.EMULATORS / 'pokemini', '/opt/homebrew/bin', '/usr/local/bin')
        for name in ('PokeMini', 'pokemini')
    )
else:
    _INSTALLED_EXECUTABLES = tuple(
        Path(directory) / name
        for directory in ('/usr/local/bin', '/usr/games', '/usr/bin')
        for name in ('PokeMini', 'pokemini')
    )
_OVERRIDE = 'RETRO_POCKET_POKEMINI'


def _find_executable() -> Path:
    override = os.environ.get(_OVERRIDE)
    candidates = (Path(override),) if override is not None else _INSTALLED_EXECUTABLES
    for path in candidates:
        if compat.is_executable(path):
            return path
    if override is not None:
        raise FileNotFoundError(f'{_OVERRIDE} must be an absolute path to an executable file')
    raise FileNotFoundError(f'Native PokeMini not found; set {_OVERRIDE} to the SDL2 executable')


def launch(rom: bytes | Path, game_id: str, save_dir: Path) -> subprocess.Popen:
    """Stage verified bytes and start PokeMini; the caller owns the child.

    Use a trusted, private save directory. Close the emulator normally to
    flush its EEPROM. Do not run multiple instances for the same game/save.
    """
    if not isinstance(game_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', game_id):
        raise ValueError('Invalid Pokémon mini game ID')
    executable = _find_executable()
    directory = save_dir.resolve()
    staged = directory / f'{game_id}.min'
    eeprom = directory / f'{game_id}.eep'
    # Native 0.60 uses fixed buffers (including a 128-byte ROM path in
    # manual save states) and treats backslashes as path separators, which
    # only Windows paths may contain.
    if any(len(os.fsencode(path)) >= limit or ('\\' in str(path) and not compat.WINDOWS)
           for path, limit in ((executable, 256), (staged, 128), (eeprom, 256))):
        raise ValueError('Path too long or unsupported by native PokeMini')
    if os.path.lexists(staged.with_suffix('.minc')):
        raise ValueError('Remove the unverified PokeMini color sidecar before launch')
    try:
        save_mode = eeprom.lstat().st_mode
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(save_mode):
            raise ValueError('PokeMini EEPROM must be a regular file')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if isinstance(rom, Path):
        _require_placed(rom, staged)
    else:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
                temporary = Path(output.name)
                output.write(rom)
            temporary.replace(staged)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    # In PokeMini 0.60, -noeepromshare ignores -eeprom and derives a path
    # from the ROM. Enable the explicit path mode, using one file per game.
    return compat.popen(
        [executable, '-freebios', '-nostate', '-eepromshare', '-eeprom', eeprom, staged],
        cwd=directory,
    )
