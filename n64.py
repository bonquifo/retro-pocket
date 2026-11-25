"""Launch the Nintendo 64 emulator with an already-verified cartridge.

Mupen64Plus on Linux and Windows; ares on macOS (ares_backend.py), where
Mupen64Plus has no self-contained build.
"""

import os
from pathlib import Path
import re
import subprocess
import tempfile

import compat
from controls import C_KEYS, DPAD_KEYS, LAYOUT
from ds import _require_placed


if compat.MACOS:
    EMULATOR, OVERRIDE_ENV = 'ares', 'RETRO_POCKET_ARES'
    _INSTALLED_EXECUTABLES = tuple(folder / 'ares.app'
                                   for folder in (compat.EMULATORS / 'ares', *compat.applications()))
    _INSTALL_HINT = 'run setup.command to install ares'
elif compat.WINDOWS:
    EMULATOR, OVERRIDE_ENV = 'Mupen64Plus', 'RETRO_POCKET_MUPEN64PLUS'
    # The official Windows bundle (setup.cmd installs it): the console
    # frontend beside mupen64plus.dll, its plugins and its data files.
    _INSTALLED_EXECUTABLES = tuple(
        directory / 'mupen64plus-ui-console.exe'
        for directory in (compat.EMULATORS / 'mupen64plus',
                          *(root / 'Mupen64Plus' for root in compat.program_files())))
    _INSTALL_HINT = 'run setup.cmd to install mupen64plus'
else:
    EMULATOR, OVERRIDE_ENV = 'Mupen64Plus', 'RETRO_POCKET_MUPEN64PLUS'
    _INSTALLED_EXECUTABLES = (Path('/usr/games/mupen64plus'), Path('/usr/bin/mupen64plus'))
    _INSTALL_HINT = 'install mupen64plus-ui-console and its plugins'
# The video plugin the Linux QA used (Ubuntu's default); the bundle has it too.
_VIDEO_PLUGIN = 'mupen64plus-video-glide64mk2'

# The shared layout (controls.LAYOUT): A/B on X/Z, L/R on Q/W, Start on Enter.
# Like the 3DS circle pad, the stick takes the arrows, so the D-pad and C
# buttons take the 3DS D-pad and C-stick keys.
#
# The Z trigger takes the shared Y key (A). The N64 has no Y button, so the
# key is free. It sits above B, next to A, so the left hand can hold Z while
# pressing A or B (Mario 64's crouch-jumps, long jump, slide kick). The 3DS
# ZL/ZR keys (1/2) are out of reach, and they are Mupen's save-slot keys.
_BUTTONS = {
    'A Button': LAYOUT['a'], 'B Button': LAYOUT['b'], 'Z Trig': LAYOUT['y'],
    'L Trig': LAYOUT['l'], 'R Trig': LAYOUT['r'], 'Start': LAYOUT['start'],
    **{f'DPad {d[0].upper()}': key for d, key in DPAD_KEYS.items()},
    **{f'C Button {d[0].upper()}': key for d, key in C_KEYS.items()},
}
# The input plugin stores keys as SDL 1.2 keysyms: ASCII for letters.
_SDL1_KEYSYMS = {'up': 273, 'down': 274, 'right': 275, 'left': 276, 'return': 13}
# Mupen's default hotkeys on f and g would fire with the D-pad.
_UNBOUND_HOTKEYS = ('Fast Forward', 'Gameshark')


def _keysym(key: str) -> int:
    return _SDL1_KEYSYMS.get(key) or ord(key)


def _gamepad_connected() -> bool:
    return compat.gamepad_connected()


def control_settings(gamepad: bool) -> list[str]:
    """Mupen64Plus --set values for the shared keyboard layout.

    With a gamepad connected, player 1 keeps Mupen's automatic gamepad
    configuration; the keyboard layout applies when there is none.
    """
    settings = [f'CoreEvents[Kbd Mapping {name}]=0' for name in _UNBOUND_HOTKEYS]
    if gamepad:
        return settings
    section = 'Input-SDL-Control1'
    values = {
        # Without a version the plugin discards the section and reverts to its defaults.
        'version': '2.000000', 'mode': '0', 'device': '-1', 'name': 'Keyboard',
        'plugged': 'True', 'plugin': '2', 'mouse': 'False',
        **{name: f'key({_keysym(key)})' for name, key in _BUTTONS.items()},
        'X Axis': f"key({_keysym(LAYOUT['left'])},{_keysym(LAYOUT['right'])})",
        'Y Axis': f"key({_keysym(LAYOUT['up'])},{_keysym(LAYOUT['down'])})",
    }
    return settings + [f'{section}[{name}]={value}' for name, value in values.items()]


def _find_executable() -> Path:
    override = os.environ.get(OVERRIDE_ENV)
    if override is not None:
        executable = compat.app_executable(override)
        if compat.is_executable(executable):
            return executable
        raise FileNotFoundError(f'{OVERRIDE_ENV} must be an absolute path to an executable file')
    for candidate in _INSTALLED_EXECUTABLES:
        executable = compat.app_executable(candidate)
        if compat.is_executable(executable):
            return executable
    raise FileNotFoundError(f'{EMULATOR} not found; {_INSTALL_HINT}, or set {OVERRIDE_ENV}')


def _bundle_arguments(executable: Path) -> list[str]:
    """Windows: name the bundle's core, plugin and data folders.

    The console frontend otherwise looks for them relative to the working
    directory, which is the game's save folder.
    """
    if not compat.WINDOWS:
        return []
    bundle = executable.parent
    arguments = ['--plugindir', str(bundle), '--datadir', str(bundle)]
    if (bundle / 'mupen64plus.dll').is_file():
        arguments += ['--corelib', str(bundle / 'mupen64plus.dll')]
    if (bundle / f'{_VIDEO_PLUGIN}.dll').is_file():
        arguments += ['--gfx', _VIDEO_PLUGIN]
    return arguments


def launch(rom: bytes | Path, game_id: str, save_dir: Path) -> subprocess.Popen:
    """Stage catalog-verified Z64 bytes in the caller's per-title save directory.

    The caller verifies the ROM digest, supplies a private directory for this
    title, and owns the returned process. Its stdout and stderr are inherited.
    """
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', game_id):
        raise ValueError('Invalid Nintendo 64 game ID')
    executable = _find_executable()
    directory = save_dir.resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    staged = directory / f'{game_id}.z64'
    if isinstance(rom, Path):
        _require_placed(rom, staged)
    else:
        output = tempfile.NamedTemporaryFile(dir=directory, delete=False)
        temporary = Path(output.name)
        try:
            with output:
                output.write(rom)
            temporary.replace(staged)
        finally:
            temporary.unlink(missing_ok=True)

    if compat.MACOS:
        import ares_backend  # Saves beside the ROM, in this save folder
        return ares_backend.start(executable, staged, directory)

    # --configdir alone does not relocate native cartridge saves or states.
    settings = [f'Core[SaveSRAMPath]={directory}', f'Core[SaveStatePath]={directory}',
                *control_settings(_gamepad_connected())]
    return compat.popen([
        executable, '--configdir', str(directory),
        *(arg for setting in settings for arg in ('--set', setting)),
        *_bundle_arguments(executable), str(staged),
    ])
