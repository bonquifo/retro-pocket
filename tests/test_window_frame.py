import gc
import os
import unittest
from unittest.mock import patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import pygame as pg

from viewport import EDGE, GRIP, WindowFrame


class FakeWindow:
    """The pg.Window attributes WindowFrame uses, without a display."""
    def __init__(self):
        self.position, self.size, self.borderless = (100, 80), (840, 620), False
        self.minimum_size = (384, 280)


def press(pos, button=1):
    return pg.event.Event(pg.MOUSEBUTTONDOWN, button=button, pos=pos)


def motion(pos):
    return pg.event.Event(pg.MOUSEMOTION, pos=pos, rel=(0, 0), buttons=(1, 0, 0))


def release(pos):
    return pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=pos)


class WindowFrameTest(unittest.TestCase):
    def setUp(self):
        pg.init()
        self.addCleanup(pg.quit)
        self.window = FakeWindow()
        self.frame = WindowFrame(self.window)
        self.mouse = self.enterContext(patch('pygame.mouse.get_pos', return_value=(500, 500)))

    def drag(self, start, by, draggable=lambda pos: False):
        """Press at a window point, move the pointer by `by` on screen, release."""
        x, y = self.window.position
        used = self.frame.handle(press(start), draggable)
        self.mouse.return_value = (x + start[0] + by[0], y + start[1] + by[1])  # Screen coordinates
        self.frame.handle(motion(start), draggable)
        self.frame.handle(release(start), draggable)
        return used

    def test_dragging_the_top_bar_moves_the_window(self):
        self.assertTrue(self.drag((300, 20), (40, -30), draggable=lambda pos: pos[1] < 100))
        self.assertEqual(self.window.position, (140, 50))
        self.assertEqual(self.window.size, (840, 620))

    def test_clicks_elsewhere_are_left_to_the_app(self):
        self.assertFalse(self.drag((300, 300), (40, 40), draggable=lambda pos: pos[1] < 100))
        self.assertEqual(self.window.position, (100, 80))

    def test_edges_and_grip_resize_and_respect_the_minimum(self):
        self.assertTrue(self.drag((839 - GRIP // 2, 619 - GRIP // 2), (200, 100)))  # Bottom-right grip
        self.assertEqual(self.window.size, (1040, 720))
        self.assertTrue(self.drag((EDGE // 2, 300), (-60, 0)))                     # Left edge grows left
        self.assertEqual((self.window.position, self.window.size), ((40, 80), (1100, 720)))
        self.drag((500, EDGE // 2), (0, 5000))                                     # Top edge: clamped
        self.assertEqual(self.window.size[1], 280)
        self.assertEqual(self.window.position[1], 80 + 720 - 280)

    def test_f11_and_double_click_toggle_full_screen_and_restore(self):
        f11 = pg.event.Event(pg.KEYDOWN, key=pg.K_F11, mod=0)
        with patch('pygame.display.get_desktop_sizes', return_value=[(1920, 1080)]):
            self.assertTrue(self.frame.handle(f11))
            self.assertEqual((self.window.position, self.window.size, self.window.borderless),
                             ((0, 0), (1920, 1080), True))
            self.assertIsNone(self.frame.zone((0, 0)))  # No resizing or moving in full screen
            self.frame.handle(f11)
            self.assertEqual((self.window.position, self.window.size, self.window.borderless),
                             ((100, 80), (840, 620), False))
            top = lambda pos: pos[1] < 100
            self.frame.handle(press((300, 20)), top)
            self.frame.handle(release((300, 20)), top)
            self.frame.handle(press((300, 20)), top)
            self.assertTrue(self.frame.fullscreen)


class SearchFieldTest(unittest.TestCase):
    def setUp(self):
        gc.collect()

    def test_field_clear_button_and_clicking_away(self):
        from app import App, SEARCH_RECT
        games = [{'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998},
                 {'id': 'emerald', 'title': 'Pokémon Emerald', 'platform': 'GBA', 'year': 2005}]
        app = App(type('Catalogue', (), {'games': games})(), show_all=True)
        self.addCleanup(pg.quit)
        r = app.viewport

        def click(point):
            pos = (r.x + point[0] * r.w // 840, r.y + point[1] * r.h // 620)
            app.event(press(pos))
            app.event(release(pos))

        app.draw()
        self.assertNotIn('search:clear', app.actions)
        click(SEARCH_RECT.center)
        self.assertTrue(app.searching)
        app.event(pg.event.Event(pg.TEXTINPUT, text='emer'))
        app.draw()
        self.assertEqual([g['id'] for g in app.visible], ['emerald'])
        click(app.actions['tile:0'][0].center)      # Clicking away ends typing, keeps the filter.
        self.assertFalse(app.searching)
        self.assertEqual(app.query, 'emer')
        app.draw()
        click(app.actions['search:clear'][0].center)
        self.assertEqual((app.query, app.searching), ('', False))
        self.assertEqual(len(app.visible), 2)
        app.draw()
        self.assertIn('fullscreen', app.actions)


if __name__ == '__main__':
    unittest.main()
