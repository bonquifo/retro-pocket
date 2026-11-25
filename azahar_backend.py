"""Launch the Azahar Qt frontend (Linux, macOS or Windows) on a verified, staged 3DS image."""

import os
from pathlib import Path
import re
import subprocess
import tempfile

import compat
from controls import C_KEYS, DPAD_KEYS, LAYOUT, qt_keycode


_EXECUTABLE_ENV = 'RETRO_POCKET_AZAHAR'
_ROM_SUFFIXES = {'.cci', '.3ds', '.3dsx'}
# Fixed install locations only; never search PATH (a ROM folder may be on it).
if compat.MACOS:
    _INSTALLED_EXECUTABLES = tuple(folder / 'Azahar.app'
                                   for folder in (compat.EMULATORS / 'azahar', *compat.applications()))
    _INSTALL_HINT = 'run setup.command'
elif compat.WINDOWS:
    _INSTALLED_EXECUTABLES = (
        compat.EMULATORS / 'azahar' / 'azahar.exe',
        *(root / 'Azahar' / 'azahar.exe' for root in compat.program_files()),
    )
    _INSTALL_HINT = 'run setup.cmd'
else:
    _INSTALLED_EXECUTABLES = (
        Path('/usr/bin/azahar'),
        Path('/usr/games/azahar'),
        Path('/usr/local/bin/azahar'),
        Path.home() / 'Applications' / 'azahar.AppImage',
        Path.home() / '.local' / 'bin' / 'azahar',
    )
    _INSTALL_HINT = 'save azahar.AppImage to ~/Applications'


_CONTROLS_MARKER = '.retro-pocket-controls'
# Gen 6-7 games walk with the circle pad (Sun/Moon ignore the D-pad), so the
# arrows drive it; the D-pad keeps Azahar's T/F/G/H and the C-stick I/J/K/L.
_BUTTONS = {'a': 'a', 'b': 'b', 'x': 'x', 'y': 'y', 'l': 'l', 'r': 'r', 'zl': 'zl', 'zr': 'zr',
            'start': 'start', 'select': 'select'}
_EXTRA_KEYS = DPAD_KEYS
# What the per-game Windows copy needs from an Azahar folder: the program, its
# libraries, Qt's path file and Qt's plugins.
_PROGRAM_FILES = ('*.exe', '*.dll', 'qt.conf', 'plugins/**/*.dll')


def _param(**values):
    """Encode a Citra/Azahar ParamPackage (':' -> $0, ',' -> $1, '$' -> $2)."""
    def escape(text):
        return str(text).replace('$', '$2').replace(':', '$0').replace(',', '$1')
    return ','.join(f'{escape(k)}:{escape(v)}' for k, v in sorted(values.items()))


def _key(key):
    return _param(code=qt_keycode(key), engine='keyboard')


def _stick(up, down, left, right):
    return _param(engine='analog_from_button', up=_key(up), down=_key(down), left=_key(left),
                  right=_key(right), modifier=_key('d'), modifier_scale='0.500000')


def _control_settings():
    settings = {f'button_{name}': _key(LAYOUT[button]) for name, button in _BUTTONS.items()}
    settings.update({f'button_{name}': _key(key) for name, key in _EXTRA_KEYS.items()})
    settings['circle_pad'] = _stick(*(LAYOUT[d] for d in ('up', 'down', 'left', 'right')))
    settings['c_stick'] = _stick(*(C_KEYS[d] for d in ('up', 'down', 'left', 'right')))
    return {f'profiles\\1\\{name}': value for name, value in settings.items()}


def _apply_controls(text):
    """Set the first input profile in a Qt ini, leaving every other line alone."""
    settings = _control_settings()
    lines = text.splitlines()
    try:
        start = lines.index('[Controls]') + 1
    except ValueError:
        if lines and lines[-1]:
            lines.append('')
        lines.append('[Controls]')
        start = len(lines)
    end = next((i for i in range(start, len(lines)) if lines[i].startswith('[')), len(lines))
    while end > start and not lines[end - 1].strip():
        end -= 1
    names = set(settings) | {f'{name}\\default' for name in settings}
    section = [line for line in lines[start:end] if line.partition('=')[0] not in names]
    if not any(line.startswith('profiles\\size=') for line in section):
        section.append('profiles\\size=1')
    for name, value in settings.items():
        section += [f'{name}="{value}"', f'{name}\\default=false']
    return '\n'.join(lines[:start] + section + lines[end:]) + '\n'


def _portable():
    """Whether Azahar runs in portable mode: a ``user`` folder holds everything.

    Windows: beside the per-game copy of azahar.exe. macOS: in its working
    directory, the profile. Linux uses the XDG directories set at launch.
    """
    return compat.WINDOWS or compat.MACOS


def user_directory(profile: Path) -> Path:
    """Where Azahar keeps a profile's settings, saves and extra data."""
    return profile / 'user' if _portable() else profile


def config_file(profile: Path) -> Path:
    if _portable():
        return user_directory(profile) / 'config' / 'qt-config.ini'
    return profile / 'config' / 'azahar-emu' / 'qt-config.ini'


def _seed_controls(profile: Path) -> None:
    """Apply the shared layout once per profile; later remaps in Azahar are kept."""
    marker = profile / _CONTROLS_MARKER
    if os.path.lexists(marker):
        return
    ini = config_file(profile)
    config = ini.parent
    config.mkdir(mode=0o700, parents=True, exist_ok=True)
    if ini.is_symlink():
        raise ValueError('Azahar config must not be a symlink')
    try:
        text = ini.read_text(encoding='utf-8')
    except FileNotFoundError:
        text = ''
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=config, delete=False) as output:
        output.write(_apply_controls(text))
    os.replace(output.name, ini)
    marker.touch(mode=0o600)


def _find_executable() -> Path:
    override = os.environ.get(_EXECUTABLE_ENV)
    if override is not None:
        executable = compat.app_executable(override)
        if compat.is_executable(executable):
            return executable
        raise FileNotFoundError(f'{_EXECUTABLE_ENV} must name a trusted absolute Azahar executable')
    for candidate in _INSTALLED_EXECUTABLES:
        executable = compat.app_executable(candidate)
        if compat.is_executable(executable):
            return executable
    raise FileNotFoundError(f'Azahar not found; {_INSTALL_HINT} or set {_EXECUTABLE_ENV}')


def _program_files(executable: Path):
    """The Azahar program files to link into a per-game copy, as (relative name, path)."""
    folder = executable.parent
    found = {executable.name: executable}
    for pattern in _PROGRAM_FILES:
        for path in folder.glob(pattern):
            if path.is_file() and not path.is_symlink():
                found.setdefault(path.relative_to(folder).as_posix(), path)
    return sorted(found.items())


def launch(rom: Path, game_id: str, save_dir: Path) -> subprocess.Popen:
    """Launch an already verified local image and return the emulator process.

    The caller keeps the ROM available while it is running and reaps the
    child. Reuse the same save root and game ID to retain the profile (system
    save data, extdata and settings) across launches.
    """
    if not isinstance(game_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', game_id):
        raise ValueError('Invalid Nintendo 3DS game ID')

    executable = _find_executable()

    rom = rom.resolve()
    if not rom.is_file():
        raise FileNotFoundError(f'ROM is not a regular file: {rom}')
    if rom.suffix.lower() not in _ROM_SUFFIXES:
        raise ValueError('Unsupported ROM format; use a supported .cci, .3ds or .3dsx image')

    namespace = save_dir.resolve() / 'azahar'
    profile = namespace / game_id
    if compat.MACOS:
        # Azahar for macOS uses a "user" folder in its working directory
        # (portable mode); without one, ~/Library/Application Support/Azahar
        # for every game.
        user = user_directory(profile)
        if any(compat.is_link(path) for path in (namespace, profile, user, user / 'config')):
            raise ValueError('Azahar profile roots must not be symlinks')
        user.mkdir(mode=0o700, parents=True, exist_ok=True)
        _seed_controls(profile)
        return compat.popen([executable, rom], cwd=profile)
    if compat.WINDOWS:
        # Azahar for Windows has no option for its user folder: it uses a "user"
        # folder beside azahar.exe (portable mode), else %APPDATA%\Azahar for
        # every game. Each game runs a linked copy of Azahar inside its profile.
        user = user_directory(profile)
        roots = [namespace, profile, user, user / 'config']
        if any(compat.is_link(path) for path in roots):
            raise ValueError('Azahar profile roots must not be symlinks')
        user.mkdir(mode=0o700, parents=True, exist_ok=True)
        compat.private_install(_program_files(executable), profile)
        _seed_controls(profile)
        return compat.popen([profile / executable.name, rom], cwd=profile)

    env = dict(os.environ)
    roots = [namespace, profile, profile / 'user']  # Linux portable mode precedes XDG.
    for kind in ('DATA', 'CONFIG', 'CACHE'):
        directory = profile / kind.lower()
        env[f'XDG_{kind}_HOME'] = str(directory)
        roots.extend((directory, directory / 'azahar-emu'))
    if any(path.is_symlink() for path in roots):
        raise ValueError('Azahar profile roots must not be symlinks')
    profile.mkdir(mode=0o700, parents=True, exist_ok=True)
    _seed_controls(profile)
    return subprocess.Popen([executable, rom], cwd=profile, env=env)
