"""One keyboard layout shared by every handheld Retro Pocket launches.

Keys are pygame/SDL key names. The integrated mGBA player reads them
directly; ds.py and azahar_backend.py translate them into each emulator's
own config format so the same key presses the same button everywhere.
"""

LAYOUT = {
    'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right',
    'a': 'x', 'b': 'z', 'x': 's', 'y': 'a',
    'l': 'q', 'r': 'w', 'zl': '1', 'zr': '2',
    'start': 'return', 'select': 'right shift',
}
# Systems with an analog stick (3DS, N64) put the stick on the arrows, so
# their D-pad and second stick (3DS C-stick, N64 C buttons) need keys of
# their own. Both systems use these same keys.
DPAD_KEYS = {'up': 't', 'down': 'g', 'left': 'f', 'right': 'h'}
C_KEYS = {'up': 'i', 'down': 'k', 'left': 'j', 'right': 'l'}
HANDHELD_BUTTONS =('up', 'down', 'left', 'right', 'a', 'b', 'l', 'r', 'start', 'select')
KEYS = {LAYOUT[button]: button for button in HANDHELD_BUTTONS}
MOUSE = {2: 'a', 3: 'b'}

# SDL2 keycodes (DeSmuME) and Qt key codes (Azahar) for the keys above.
SDL_KEYCODES = {'up': 0x40000052, 'down': 0x40000051, 'left': 0x40000050, 'right': 0x4000004F,
                'return': 13, 'right shift': 0x400000E5}
QT_KEYCODES = {'up': 0x01000013, 'down': 0x01000015, 'left': 0x01000012, 'right': 0x01000014,
               'return': 0x01000004, 'right shift': 0x01000020}  # Qt has one Shift key.


def sdl_keycode(key):
    return SDL_KEYCODES.get(key) or ord(key)


def qt_keycode(key):
    return QT_KEYCODES.get(key) or ord(key.upper())


def active_buttons(held_keys, held_mouse):
    return {KEYS[key] for key in held_keys if key in KEYS} | set(held_mouse.values())


def pad_rects(width, height):
    cx, cy = width // 2, height - 149
    return {
        'up': (cx-222, cy, 46, 34), 'left': (cx-272, cy+38, 46, 34),
        'down': (cx-222, cy+76, 46, 34), 'right': (cx-172, cy+38, 46, 34),
        'l': (cx-111, cy, 43, 34), 'r': (cx+68, cy, 43, 34),
        'select': (cx-93, cy+76, 76, 34), 'start': (cx+17, cy+76, 76, 34),
        'b': (cx+145, cy+60, 49, 41), 'a': (cx+220, cy+25, 49, 41),
    }
