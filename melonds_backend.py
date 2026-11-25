"""Start melonDS (the Nintendo DS emulator on macOS) for one game, with its own settings.

ds.py verifies and stages the ROM, then calls start(). melonDS keeps its
settings (melonDS.toml) in a "portable" folder beside its program, or beside
melonDS.app on macOS, else in one folder for every game. Each game therefore
runs its own copy of melonDS, made of hard links, inside its save folder:

    saves/<game>/<game>.nds           the verified ROM (placed by the worker)
    saves/<game>/<game>.sav           the cartridge save, written by melonDS
    saves/<game>/melonds/melonDS.app  the game's linked copy of melonDS
    saves/<game>/melonds/portable/    its settings
"""
from pathlib import Path
import subprocess

import compat
from controls import LAYOUT, qt_keycode

# melonDS 1.1 ships with no keyboard mapping at all. Its buttons, in its own
# names, take the shared layout (controls.LAYOUT).
_BUTTONS = {'A': 'a', 'B': 'b', 'X': 'x', 'Y': 'y', 'L': 'l', 'R': 'r', 'Start': 'start', 'Select': 'select',
            'Up': 'up', 'Down': 'down', 'Left': 'left', 'Right': 'right'}
_ARROWS = {'up', 'down', 'left', 'right'}
_KEYPAD_MODIFIER = 0x20000000  # Qt sets it on arrow keys on macOS, and melonDS keeps it in the key
_RIGHT_MODIFIER = 1 << 31       # melonDS's mark for the right-hand Shift, Ctrl or Alt key
_SETTINGS = 'melonDS.toml'


def key_value(key, macos=None):
    """The number melonDS stores for a controls.LAYOUT key name."""
    macos = compat.MACOS if macos is None else macos
    value = qt_keycode(key)
    if key == 'right shift':
        value |= _RIGHT_MODIFIER
    elif key in _ARROWS and macos:
        value |= _KEYPAD_MODIFIER
    return value - (1 << 32) if value >= 1 << 31 else value  # A signed 32-bit int, as melonDS writes it


def settings_text(macos=None):
    """A first melonDS.toml: the keyboard layout for the first emulator instance."""
    lines = ['[Instance0.Keyboard]']
    lines += [f'{name} = {key_value(LAYOUT[button], macos)}' for name, button in _BUTTONS.items()]
    return '\n'.join(lines) + '\n'


def _program_files(executable: Path):
    """The files making up melonDS: its app bundle on macOS, else the program alone."""
    bundle = compat.bundle_of(executable)
    if bundle is None:
        return [(executable.name, executable)], Path(executable.name)
    files = sorted((path.relative_to(bundle.parent).as_posix(), path) for path in bundle.rglob('*')
                   if path.is_file() and not path.is_symlink())
    return files, executable.relative_to(bundle.parent)


def profile_folder(directory: Path) -> Path:
    return directory / 'melonds'


def start(executable: Path, staged: Path, directory: Path) -> subprocess.Popen:
    """Run this game's own copy of melonDS on the verified ROM ``staged``."""
    profile = profile_folder(directory)
    portable = profile / 'portable'
    if compat.is_link(profile) or compat.is_link(portable):
        raise ValueError('melonDS profile must not be a symlink')
    files, program = _program_files(executable)
    compat.private_install(files, profile)
    portable.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with (portable / _SETTINGS).open('x', encoding='utf-8') as output:
            output.write(settings_text())
    except FileExistsError:
        pass  # Keep the player's settings, controls included, across launches.
    return compat.popen([profile / program, str(staged)], cwd=profile)
