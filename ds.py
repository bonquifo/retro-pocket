"""Launch the native Nintendo DS emulator with already-verified ROM bytes.

DeSmuME on Linux and Windows; melonDS on macOS (melonds_backend.py), where
DeSmuME's frontend can't be started on a ROM and supervised.
"""

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import compat
from controls import LAYOUT, sdl_keycode


if compat.MACOS:
    EMULATOR, OVERRIDE_ENV = 'melonDS', 'RETRO_POCKET_MELONDS'
    _INSTALLED_EXECUTABLES = tuple(folder / 'melonDS.app'
                                   for folder in (compat.EMULATORS / 'melonds', *compat.applications()))
    _INSTALL_HINT = 'run setup.command to install melonds'
elif compat.WINDOWS:
    EMULATOR, OVERRIDE_ENV = 'DeSmuME', 'RETRO_POCKET_DESMUME'
    # The official Windows build (setup.cmd installs it), or a copy in
    # Program Files. Its own default keys already match controls.LAYOUT.
    _INSTALLED_EXECUTABLES = tuple(
        directory / name
        for directory in (compat.EMULATORS / 'desmume', *(root / 'DeSmuME' for root in compat.program_files()))
        for name in ('DeSmuME_0.9.13_x64.exe', 'DeSmuME_x64.exe', 'DeSmuME.exe')
    )
    _INSTALL_HINT = 'run setup.cmd to install desmume'
else:
    EMULATOR, OVERRIDE_ENV = 'DeSmuME', 'RETRO_POCKET_DESMUME'
    # Recent Ubuntu packages ship only desmume-cli (an SDL GUI despite the name).
    # Older distro packages also ship a graphical frontend named desmume.
    _INSTALLED_EXECUTABLES = (
        Path('/usr/games/desmume-cli'),
        Path('/usr/bin/desmume-cli'),
        Path('/usr/games/desmume'),
        Path('/usr/bin/desmume'),
    )
    _INSTALL_HINT = 'install the desmume package'


def _find_executable() -> Path:
    override = os.environ.get(OVERRIDE_ENV)
    if override is not None:
        executable = compat.app_executable(override)
        if compat.is_executable(executable):
            return executable
        raise FileNotFoundError(f'{OVERRIDE_ENV} must be an absolute path to an executable file')

    # Don't search PATH: a ROM directory or working directory may be on it.
    for candidate in _INSTALLED_EXECUTABLES:
        executable = compat.app_executable(candidate)
        if compat.is_executable(executable):
            return executable
    raise FileNotFoundError(f'{EMULATOR} not found; {_INSTALL_HINT} or set {OVERRIDE_ENV}')


_SHIM_SOURCE = Path(__file__).resolve().with_name('ds_input_shim.c')
_COMPILERS = (Path('/usr/bin/cc'), Path('/usr/bin/gcc'))
# desmume-cli's intact default joystick table (device 0); see ds_input_shim.c.
_JOYPAD = {'a': 'b1', 'b': 'b0', 'x': 'b4', 'y': 'b3', 'l': 'b6', 'r': 'b7',
           'start': 'b8', 'select': 'b5', 'right': 'x+', 'left': 'x-', 'up': 'y-', 'down': 'y+'}
# Windows DeSmuME reads desmume.ini beside its executable. Relative paths are
# relative to that folder, so ".\" keeps battery saves (<game>.dsv) there too.
# Its default window shows the screens at 1x (256x384), tiny on today's
# displays: start at 2x. View > Window Size changes it and is remembered.
_WINDOWS_INI = '[PathSettings]\nBattery=.\\\n[Video]\nWindow Size=2\n'


def keymap() -> str:
    """The shared layout as RETRO_POCKET_DS_KEYMAP for the input shim."""
    return ','.join(f'{sdl_keycode(LAYOUT[button])}:{target}' for button, target in _JOYPAD.items())


def input_shim(cache: Path) -> Path | None:
    """Build (once per source version) the keyboard fix; None if no compiler."""
    source = _SHIM_SOURCE.read_bytes()
    target = cache / f'ds-input-{hashlib.sha256(source).hexdigest()[:16]}.so'
    if target.is_file() and not target.is_symlink():
        return target
    compiler = next((c for c in _COMPILERS if c.is_file() and os.access(c, os.X_OK)), None)
    if compiler is None:
        print('Warning: no C compiler at /usr/bin/cc; DeSmuME keyboard input stays scrambled '
              '(install build-essential, or use a gamepad)', file=sys.stderr)
        return None
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as temporary:
        built = Path(temporary) / 'shim.so'
        result = subprocess.run([compiler, '-shared', '-fPIC', '-O2', '-o', built, _SHIM_SOURCE, '-ldl'],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
                                env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        if result.returncode or not built.is_file():
            print('Warning: could not build the DeSmuME keyboard fix:\n'
                  + result.stderr.decode(errors='replace'), file=sys.stderr)
            return None
        built.chmod(0o500)
        os.replace(built, target)
    return target


def _require_placed(rom: Path, staged: Path) -> None:
    """A path argument must be the caller's verified file at the stable name."""
    if rom.resolve() != staged or rom.is_symlink() or not staged.is_file():
        raise ValueError(f'Verified ROM must already be placed at {staged}')


def _windows_profile(executable: Path, directory: Path) -> Path:
    """This game's own DeSmuME: a linked copy whose folder keeps its settings and saves."""
    profile = directory / 'desmume'
    if compat.is_link(profile):
        raise ValueError('DeSmuME profile must not be a symlink')
    if Path(tempfile.gettempdir()).resolve() in profile.parents:
        print('Warning: DeSmuME ignores the settings and save folder beside it when it runs from '
              'the temporary folder, and uses %LOCALAPPDATA%\\DeSmuME instead; '
              'choose a --data-dir outside %TEMP%', file=sys.stderr)
    files = [(executable.name, executable)]
    database = executable.with_name('desmume.ddb')  # Save-type database shipped beside the program
    if database.is_file():
        files.append((database.name, database))
    compat.private_install(files, profile)
    ini = profile / 'desmume.ini'
    try:
        with ini.open('x', encoding='ascii', newline='\r\n') as output:
            output.write(_WINDOWS_INI)
    except FileExistsError:
        pass  # Keep the player's settings across launches.
    return profile / executable.name


def launch(rom: bytes | Path, game_id: str, save_dir: Path) -> subprocess.Popen:
    """Start DeSmuME in a persistent per-game save directory.

    The caller verifies the ROM and owns the returned process. Leave the ROM
    on disk while running: DeSmuME can stream it instead of preloading it.
    """
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', game_id):
        raise ValueError('Invalid Nintendo DS game ID')
    executable = _find_executable()
    directory = save_dir.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    staged = directory / f'{game_id}.nds'
    if isinstance(rom, Path):
        _require_placed(rom, staged)
    else:
        # Publish only a complete image, without writing through an existing
        # symlink. Keep the pathname stable for saves.
        output = tempfile.NamedTemporaryFile(dir=directory, delete=False)
        temporary = Path(output.name)
        try:
            with output:
                output.write(rom)
            temporary.replace(staged)
        finally:
            temporary.unlink(missing_ok=True)

    if compat.MACOS:
        import melonds_backend  # Saves: saves/<game>/<game>.sav
        return melonds_backend.start(executable, staged, directory)
    if compat.WINDOWS:
        # Saves: saves/<game>/desmume/<game>.dsv, the same place as on Linux.
        program = _windows_profile(executable, directory)
        return compat.popen([program, str(staged)], cwd=program.parent)

    # Linux DeSmuME stores .dsv and states under $XDG_CONFIG_HOME/desmume.
    env = dict(os.environ, XDG_CONFIG_HOME=str(directory))
    shim = input_shim(directory.parent / '.ds-input')
    if shim is not None and any(c in str(shim) for c in ' :'):
        print('Warning: LD_PRELOAD cannot load a path containing spaces or colons; '
              'DeSmuME keyboard input stays scrambled', file=sys.stderr)
        shim = None
    if shim is not None:
        env['LD_PRELOAD'] = ' '.join(filter(None, (str(shim), env.get('LD_PRELOAD'))))
        env['RETRO_POCKET_DS_KEYMAP'] = keymap()
    # Its working directory is searched for desmume.ddb: keep it private.
    return subprocess.Popen([executable, str(staged)], env=env, cwd=directory)
