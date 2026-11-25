import os

import unittest
from unittest.mock import patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import pygame as pg

from app import App
from handheld_player import Player
from viewport import fit_rect, surface_point, window_start_size


class GeometryTest(unittest.TestCase):
    def test_letterbox_keeps_proportions_and_rejects_sidebar_clicks(self):
        bounds = fit_rect((840, 620), (1600, 620))
        self.assertEqual(bounds, pg.Rect(380, 0, 840, 620))
        self.assertIsNone(surface_point((189, 200), (1600, 620), (800, 620), bounds))
        self.assertEqual(surface_point((400, 310), (1600, 620), (800, 620), bounds), (800, 310))
        self.assertIsNone(surface_point((610, 200), (1600, 620), (800, 620), bounds))

    def test_starts_small_enough_to_fit_the_desktop(self):
        w, h = window_start_size((840, 620), (640, 480))
        self.assertLess(w, 640)
        self.assertLess(h, 480)
        self.assertAlmostEqual(w / h, 840 / 620, places=2)
        self.assertEqual(window_start_size((840, 620), (1920, 1080)), (840, 620))


class ResizeTest(unittest.TestCase):
    def setUp(self):
        import gc
        gc.collect()  # See test_app.AppTest.setUp

    def tearDown(self):
        pg.quit()

    def test_catalogue_clicks_follow_visual_coordinates_after_resize(self):
        class TestLibrary:
            games = [{'id': name, 'title': name, 'platform': 'GB', 'year': 2000} for name in ('first', 'second')]

        app = App(TestLibrary(), show_all=True)
        self.assertTrue(app.window.resizable)
        for size in ((1200, 520), (460, 600), (840, 620)):
            with self.subTest(size=size):
                app.window.size = size
                app.select(0)
                app.draw()
                self.assertEqual(app.presentation.get_rect().size, size)
                x, y = app.actions['tile:1'][0].center
                rect = app.viewport
                point = (rect.x + x * rect.w // 840, rect.y + y * rect.h // 620)
                outside = (0, 0)
                app.event(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=outside))
                self.assertEqual(app.game['id'], 'first')
                app.event(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=point))
                self.assertEqual(app.game['id'], 'second')

    def test_player_resizes_without_distorting_game_or_losing_input(self):
        class QuietCore:
            sample_rate = 32768
            audio = bytearray()

        with patch.dict(os.environ, SDL_AUDIODRIVER='retro-pocket-no-device-test'):
            player = Player(QuietCore(), 'Resize test')
        self.assertTrue(player.audio_status)
        self.assertTrue(player.window.resizable)
        for size in ((512, 365), (1440, 650), (650, 900), (384, 280)):
            with self.subTest(size=size):
                player.window.size = size
                player.frame = (160, 144, b'\xf0\x00\x20' * (160 * 144))
                player.draw(set())
                self.assertEqual(player.screen.get_size(), size)
                self.assertTrue(player.screen.get_rect().contains(player.picture))
                self.assertAlmostEqual(player.picture.w / player.picture.h, 160/144, places=2)
                self.assertEqual(player.screen.get_at(player.picture.center)[:3], (240, 0, 32))
                for name, rect in player.pads.items():
                    self.assertTrue(player.screen.get_rect().contains(rect))
                    self.assertFalse(rect.colliderect(player.picture))
                    player.handle_event(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=rect.center))
                    self.assertEqual(player.held_mouse, {1: name})
                    player.handle_event(pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=rect.center))
                self.assertFalse(player.handle_event(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=player.exit_rect.center)))


class PadLabelTest(unittest.TestCase):
    def setUp(self):
        import gc
        gc.collect()  # See test_app.AppTest.setUp

    def tearDown(self):
        pg.quit()

    def test_game_boy_hides_shoulders_and_dpad_arrows_are_drawn(self):
        class QuietCore:
            sample_rate = 32768
            audio = bytearray()

        for shoulders in (True, False):
            with self.subTest(shoulders=shoulders):
                player = Player(QuietCore(), 'Pad test', shoulders)
                self.assertEqual({'l', 'r'} <= set(player.pads), shoulders)
                self.assertEqual('Q/W' in player.help, shoulders)
                player.draw(set())
                # The arrow is drawn in ink at the button centre, not left as
                # a missing-glyph box in the button colour.
                for name in ('up', 'down', 'left', 'right'):
                    self.assertEqual(player.screen.get_at(player.pads[name].center)[:3], pg.Color('#f2f6fc')[:3])
