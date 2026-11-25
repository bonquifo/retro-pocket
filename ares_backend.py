"""Start ares (the Nintendo 64 emulator on macOS) for one game, with its own settings.

n64.py verifies and stages the ROM, then calls start(). ares takes its
settings file on the command line and writes cartridge saves beside the ROM:

    saves/<game>/<game>.z64           the verified ROM (placed by the worker)
    saves/<game>/<game>.eeprom ...    the cartridge save, written by ares
    saves/<game>/ares/settings.bml    this game's ares settings
"""
from pathlib import Path
import subprocess

import compat
from controls import C_KEYS, DPAD_KEYS, LAYOUT

SYSTEM = 'Nintendo 64'

# ares has no default keyboard bindings. Bindings name a key by its position
# in ares's macOS (Quartz) keyboard list: ruby/input/keyboard/quartz.cpp.
_QUARTZ_KEYS = {
    'escape': 0, '1': 22, '2': 23, 'a': 40, 'f': 45, 'g': 46, 'h': 47, 'i': 48, 'j': 49, 'k': 50,
    'l': 51, 'q': 56, 's': 58, 't': 59, 'w': 62, 'x': 63, 'z': 65,
    'up': 92, 'down': 93, 'left': 94, 'right': 95, 'return': 97, 'right shift': 100,
}
_KEYBOARD = '0x1/0'  # ares's keyboard device, button group

# ares's virtual gamepad as it drives an N64 controller (desktop-ui/emulator/
# nintendo-64.cpp): A = South, B = West, Z = R-Trigger, C buttons = right
# stick, analog stick = left stick. The keys match the Linux and Windows N64
# layout (n64.py): stick on the arrows, D-pad and C buttons on the 3DS keys,
# and Z on the shared Y key (A).
_PAD = {
    'A..South': LAYOUT['a'], 'X..West': LAYOUT['b'], 'R-Trigger': LAYOUT['y'],
    'L-Bumper': LAYOUT['l'], 'R-Bumper': LAYOUT['r'], 'Start': LAYOUT['start'],
    'Pad.Up': DPAD_KEYS['up'], 'Pad.Down': DPAD_KEYS['down'],
    'Pad.Left': DPAD_KEYS['left'], 'Pad.Right': DPAD_KEYS['right'],
    'L-Up': LAYOUT['up'], 'L-Down': LAYOUT['down'], 'L-Left': LAYOUT['left'], 'L-Right': LAYOUT['right'],
    'R-Up': C_KEYS['up'], 'R-Down': C_KEYS['down'], 'R-Left': C_KEYS['left'], 'R-Right': C_KEYS['right'],
}


def binding(key):
    return f'{_KEYBOARD}/{_QUARTZ_KEYS[key]}'


def settings_text():
    """A first settings.bml: the shared keyboard layout, and Esc to quit as on Linux.

    ares fills in every other setting with its defaults and rewrites the file,
    so later changes made in ares are kept.
    """
    lines = ['VirtualPad1']
    lines += [f'  {name}: {binding(key)}' for name, key in _PAD.items()]
    lines += ['Hotkey', f'  QuitEmulator: {binding("escape")}']
    return '\n'.join(lines) + '\n'


def settings_file(directory: Path) -> Path:
    return directory / 'ares' / 'settings.bml'


def start(executable: Path, staged: Path, directory: Path) -> subprocess.Popen:
    """Run ares on the verified ROM ``staged`` with this game's own settings."""
    settings = settings_file(directory)
    if compat.is_link(settings.parent) or settings.is_symlink():
        raise ValueError('ares settings must not be a symlink')
    settings.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with settings.open('x', encoding='utf-8') as output:
            output.write(settings_text())
    except FileExistsError:
        pass  # Keep the player's settings, controls included, across launches.
    return compat.popen([executable, '--system', SYSTEM, '--no-file-prompt',
                         '--settings-file', str(settings), str(staged)], cwd=directory)
