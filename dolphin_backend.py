"""Launch Dolphin on a raw image already verified and staged by the worker."""

import os
from pathlib import Path
import re
import subprocess

import compat


if compat.WINDOWS:
    # Dolphin's Windows builds are portable folders (Dolphin-x64); keep one in
    # emulators\dolphin, or install it under Program Files.
    _INSTALLED_EXECUTABLES = tuple(
        directory / 'Dolphin.exe'
        for directory in (compat.EMULATORS / 'dolphin', compat.EMULATORS / 'Dolphin-x64',
                          *(root / 'Dolphin' for root in compat.program_files()),
                          *(root / 'Dolphin-x64' for root in compat.program_files())))
    _X11_EXECUTABLES = ()
    _INSTALL_HINT = 'extract Dolphin into emulators\\dolphin'
    _POINTER_DEVICE = 'DInput/0/Keyboard Mouse'
else:
    _INSTALLED_EXECUTABLES = (Path('/usr/games/dolphin-emu'), Path('/usr/bin/dolphin-emu'))
    _X11_EXECUTABLES = (Path('/usr/games/dolphin-emu-nogui'), Path('/usr/bin/dolphin-emu-nogui'))
    _INSTALL_HINT = 'install dolphin-emu'
    _POINTER_DEVICE = 'XInput2/0/Virtual core pointer'


# Upright Wii Remote for local Battle Revolution. Dolphin's built-in first
# GameCube pad profile already supplies a complete keyboard mapping.
_WII_REMOTE = f"""[Wiimote1]
Device = {_POINTER_DEVICE}
Source = 1
Extension = None
Buttons/A = X | `Click 1`
Buttons/B = Z | `Click 3`
Buttons/1 = `1`
Buttons/2 = `2`
Buttons/- = Q
Buttons/+ = E
Buttons/Home = Return
D-Pad/Up = Up
D-Pad/Down = Down
D-Pad/Left = Left
D-Pad/Right = Right
IR/Up = `Cursor Y-`
IR/Down = `Cursor Y+`
IR/Left = `Cursor X-`
IR/Right = `Cursor X+`
Shake/X = `Click 2`
Shake/Y = `Click 2`
Shake/Z = `Click 2`
"""


def _seed_wii_remote(directory: Path) -> None:
    config = directory / 'Config'
    config.mkdir(mode=0o700, exist_ok=True)
    try:
        with (config / 'WiimoteNew.ini').open('x', encoding='utf-8') as output:
            output.write(_WII_REMOTE)
    except FileExistsError:
        pass  # Keep the player's controller changes across launches.


def _find_executable() -> Path:
    override = os.environ.get('RETRO_POCKET_DOLPHIN')
    if override is not None:
        path = Path(override)
        if compat.is_executable(path):
            return path
        raise FileNotFoundError('RETRO_POCKET_DOLPHIN must be an absolute path to an executable file')
    for path in _INSTALLED_EXECUTABLES:
        if compat.is_executable(path):
            return path
    raise FileNotFoundError(f'Dolphin not found; {_INSTALL_HINT} or set RETRO_POCKET_DOLPHIN')


def launch(rom: Path, game_id: str, save_dir: Path) -> subprocess.Popen:
    """Start Dolphin; the caller owns the process and the staged image lifetime."""
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', game_id):
        raise ValueError('Invalid Dolphin game ID')
    x11_override = os.environ.get('RETRO_POCKET_DOLPHIN_NOGUI')
    x11 = None
    if compat.WINDOWS:
        pass  # No X11 frontend: Dolphin.exe in batch mode.
    elif x11_override is not None:
        x11 = Path(x11_override)
        if not compat.is_executable(x11):
            raise FileNotFoundError('RETRO_POCKET_DOLPHIN_NOGUI must point to an absolute executable')
        if not os.environ.get('DISPLAY'):
            raise OSError('Dolphin’s native X11 frontend requires a graphical X11 or XWayland session')
    elif os.environ.get('DISPLAY') and 'RETRO_POCKET_DOLPHIN' not in os.environ:
        x11 = next((p for p in _X11_EXECUTABLES if compat.is_executable(p)), None)
    executable = x11 or _find_executable()
    directory = save_dir.resolve() / game_id
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if game_id.startswith('wii-'):
        _seed_wii_remote(directory)
    frontend = '--platform=x11' if x11 else '--batch'
    return compat.popen([executable, frontend, '--user', str(directory), '--exec', str(rom.resolve())])
