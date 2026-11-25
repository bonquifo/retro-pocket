import unittest

from controls import KEYS, LAYOUT, MOUSE, active_buttons, pad_rects


class ControlsTest(unittest.TestCase):
    def test_default_keyboard_mapping(self):
        self.assertEqual(active_buttons({'left', 'x', 'return'}, {}), {'left', 'a', 'start'})
        self.assertEqual(active_buttons({'q', 'w', 'right shift', 'z'}, {}), {'l', 'r', 'select', 'b'})
        self.assertEqual(active_buttons({'a', 's'}, {}), set())  # Y/X on DS and 3DS, unused here.
        self.assertEqual(set(KEYS.values()), {'up', 'down', 'left', 'right', 'a', 'b', 'start', 'select', 'l', 'r'})

    def test_mouse_and_keyboard_contribute_independently(self):
        self.assertEqual(active_buttons({'z', 'x'}, {1: 'left', 2: 'start'}), {'a', 'b', 'left', 'start'})
        self.assertEqual(active_buttons({'x'}, {1: 'a'}), {'a'})
        self.assertEqual(MOUSE, {2: 'a', 3: 'b'})

    def test_clickable_pad_covers_the_gameboy_controls(self):
        buttons = pad_rects(640, 540)
        self.assertEqual(set(buttons), set(KEYS.values()))
        for name, (x, y, w, h) in buttons.items():
            with self.subTest(button=name):
                self.assertTrue(0 <= x < x+w <= 640 and 365 <= y < y+h <= 540)
        for a, (x, y, w, h) in buttons.items():
            for b, (u, v, p, q) in buttons.items():
                if a != b:
                    self.assertTrue(x+w <= u or u+p <= x or y+h <= v or v+q <= y, (a, b))


class SharedLayoutTest(unittest.TestCase):
    def test_every_emulator_gets_the_same_keys(self):
        import re

        import azahar_backend
        import ds
        from controls import qt_keycode, sdl_keycode

        expected = dict(a='x', b='z', x='s', y='a', l='q', r='w', start='return', select='right shift',
                        up='up', down='down', left='left', right='right')
        self.assertEqual({k: LAYOUT[k] for k in expected}, expected)
        self.assertEqual(len(set(LAYOUT.values())), len(LAYOUT))  # No key drives two buttons.
        targets = dict(pair.split(':') for pair in ds.keymap().split(','))
        joypad = {'a': 'b1', 'b': 'b0', 'x': 'b4', 'y': 'b3', 'l': 'b6', 'r': 'b7', 'start': 'b8',
                  'select': 'b5', 'right': 'x+', 'left': 'x-', 'up': 'y-', 'down': 'y+'}
        self.assertEqual(targets, {str(sdl_keycode(LAYOUT[b])): t for b, t in joypad.items()})
        ini = azahar_backend._apply_controls('')
        for button in ('a', 'b', 'x', 'y', 'l', 'r', 'start', 'select'):
            code = re.search(rf'button_{button}="code:(\d+),', ini).group(1)
            self.assertEqual(int(code), qt_keycode(LAYOUT[button]), button)
        stick = re.search(r'circle_pad="([^"]+)"', ini).group(1)
        for direction in ('up', 'down', 'left', 'right'):
            self.assertIn(f'{direction}:code$0{qt_keycode(LAYOUT[direction])}$1', stick)
