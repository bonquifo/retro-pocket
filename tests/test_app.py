import os
import unittest

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
try:
    import pygame
except ImportError:
    pygame = None

if pygame is not None:
    from app import App, locate_core


@unittest.skipIf(pygame is None, 'pygame-ce not installed')
class AppTest(unittest.TestCase):
    def setUp(self):
        # Collect windows left by earlier tests now: after pg.quit, SDL can
        # reuse a window handle, and a late finalizer would close this test's.
        import gc
        gc.collect()

    def test_force_close_requires_confirmation(self):
        from unittest.mock import Mock
        game = {'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998}
        app = App(type('Catalogue', (), {'games': [game]})())
        self.addCleanup(pygame.quit)
        app.session = Mock()
        app.force_close()
        app.session.request_stop.assert_not_called()
        self.assertIn('unsaved', app.status.lower())
        app.force_close()
        app.session.request_stop.assert_called_once_with(force=True)

    def test_unchanged_frames_are_not_re_presented(self):
        game = {'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998, 'unavailable': 'x'}
        app = App(type('Catalogue', (), {'games': [game]})())
        self.addCleanup(pygame.quit)
        class CountingWindow:
            def __init__(self, window):
                self.window, self.call_count = window, 0

            def __getattr__(self, name):
                return getattr(self.window, name)

            def flip(self):
                self.call_count += 1
                self.window.flip()

        flip = app.window = CountingWindow(app.window)
        app.draw()
        app.draw()
        self.assertEqual(flip.call_count, 1)
        app.status = 'Something changed'
        app.draw()
        self.assertEqual(flip.call_count, 2)
        app.event(pygame.event.Event(pygame.WINDOWEXPOSED))
        app.draw()
        self.assertEqual(flip.call_count, 3)
        flip.window.size = (1000, 700)
        app.draw()
        self.assertEqual(flip.call_count, 4)
        app.draw()
        self.assertEqual(flip.call_count, 4)

    def test_catalogue_only_search_cannot_import_or_play(self):
        class MixedLibrary:
            games = [{'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998},
                     {'id': 'violet', 'title': 'Pokémon Violet', 'platform': 'Switch', 'year': 2022,
                      'unavailable': 'No Switch backend'}]

        app = App(MixedLibrary(), show_all=True)
        try:
            app.draw()
            app.event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SLASH))
            app.event(pygame.event.Event(pygame.TEXTINPUT, text='violet'))
            app.event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN))
            self.assertEqual(app.game['id'], 'violet')
            app.draw()
            self.assertNotIn('Import ROM', app.actions)
            self.assertNotIn('Play', app.actions)
            app.play()
            self.assertEqual(app.status, 'No Switch backend')
        finally:
            pygame.quit()

    def test_catalogue_can_be_rendered_and_navigated_without_a_display(self):
        class EmptyLibrary:
            games = [{'id': 'red', 'title': 'Pokemon Red', 'platform': 'GB', 'year': 1998},
                     {'id': 'gold', 'title': 'Pokemon Gold', 'platform': 'GBC', 'year': 2000}]

        app = App(EmptyLibrary(), show_all=True)
        try:
            app.draw()
            app.event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN))
            self.assertEqual(app.game['id'], 'gold')
            app.draw()
        finally:
            pygame.quit()

    def test_short_numbers_match_titles_not_years_and_headings_count_games(self):
        class Library:
            games = [{'id': 's1', 'title': 'Pokémon Stadium', 'platform': 'N64', 'year': 2000},
                     {'id': 's2', 'title': 'Pokémon Stadium 2', 'platform': 'N64', 'year': 2001},
                     {'id': 'snap', 'title': 'Pokémon Snap', 'platform': 'N64', 'year': 1999}]

        app = App(Library(), show_all=True)
        self.addCleanup(pygame.quit)
        for query, expected in (('stadium 2', ['s2']), ('200', ['s1', 's2']),
                                ('1999', ['snap']), ('n64 199', ['snap'])):
            with self.subTest(query=query):
                app.query = query
                app.filter_games()
                self.assertEqual([g['id'] for g in app.visible], expected)
        texts = []
        original = app.text
        app.text = lambda text, *a, **k: (texts.append(text), original(text, *a, **k))
        app.query = 'snap'
        app.filter_games()
        app.draw()
        # One heading per system, with how many of its games are listed.
        self.assertIn('NINTENDO 64', texts)
        self.assertEqual(app.headers, [('Nintendo 64', 1, 0)])

    def test_status_says_playing_once_the_emulator_is_up(self):
        from unittest.mock import Mock, patch
        game = {'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998}
        library = type('Catalogue', (), {'games': [game], 'path': lambda self, g: Mock(is_file=lambda: True)})()
        app = App(library)
        self.addCleanup(pygame.quit)
        session = Mock()
        session.process.poll.return_value = None
        with patch('app.EmulatorSession.for_game', return_value=session), \
                patch('app.time.monotonic', return_value=100.0):
            app.play()
            app.update()
        self.assertIn('Opening', app.status)
        with patch('app.time.monotonic', return_value=105.0):
            app.update()
        self.assertEqual(app.status, 'Playing Pokémon Red. Close its window to come back here.')
        session.process.poll.return_value = 0
        app.update()
        self.assertEqual(app.status, 'Returned from emulator.')

    def test_games_are_split_into_categories_switched_by_tab_or_click(self):
        class Library:
            games = [{'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998},
                     {'id': 'snap', 'title': 'Pokémon Snap', 'platform': 'N64', 'year': 1999},
                     {'id': 'sm64', 'title': 'Super Mario 64', 'series': 'Mario', 'platform': 'N64', 'year': 1996}]

        app = App(Library(), show_all=True)
        self.addCleanup(pygame.quit)
        self.assertEqual(app.categories, ['Pokémon', 'Mario'])
        self.assertEqual([g['id'] for g in app.visible], ['red', 'snap'])
        app.event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, mod=0))
        self.assertEqual([g['id'] for g in app.visible], ['sm64'])
        # A search carries over: "64" finds Snap and Mario 64 in their own tabs.
        app.query = 'n64'
        app.filter_games()
        self.assertEqual([g['id'] for g in app.visible], ['sm64'])
        app.event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB, mod=pygame.KMOD_SHIFT))
        self.assertEqual([g['id'] for g in app.visible], ['snap'])
        app.query = ''
        app.filter_games()
        app.draw()
        rect, _ = app.actions['tab:Mario']
        r = app.viewport
        pos = (r.x + rect.centerx * r.w // 840, r.y + rect.centery * r.h // 620)
        app.event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos))
        self.assertEqual(app.category, 'Mario')

    def test_my_games_by_default_and_c_shows_the_full_catalogue(self):
        from unittest.mock import Mock
        owned = {'red', 'plat'}

        class Library:
            rom_dir = None
            games = [{'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998},
                     {'id': 'blue', 'title': 'Pokémon Blue', 'platform': 'GB', 'year': 1998},
                     {'id': 'plat', 'title': 'Pokémon Platinum', 'platform': 'NDS', 'year': 2009},
                     {'id': 'violet', 'title': 'Pokémon Violet', 'platform': 'Switch', 'year': 2022,
                      'unavailable': 'No Switch backend'}]
            def path(self, game):
                return Mock(is_file=lambda: False)
            def found(self, game):
                return Path('/roms/x') if game['id'] in owned else None

        from pathlib import Path
        app = App(Library())
        self.addCleanup(pygame.quit)
        self.assertEqual([g['id'] for g in app.visible], ['red', 'plat'])
        app.event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RIGHT, mod=0))
        app.event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c, mod=0))
        # Full catalogue keeps the selection and adds unowned and catalogue-only games.
        self.assertEqual([g['id'] for g in app.visible], ['red', 'blue', 'plat', 'violet'])
        self.assertEqual(app.game['id'], 'plat')
        app.draw()
        self.assertIn('view:all', app.actions)
        self.assertIn('Play', app.actions)
        # An unowned game offers no Play (or import): its ROM goes in the ROM folder.
        app.select(1)
        app.draw()
        self.assertNotIn('Play', app.actions)
        self.assertNotIn('Import ROM', app.actions)
        app.event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, mod=0))
        self.assertEqual(app.status, 'This game is not in your collection.')
        app.select(2)
        app.event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_c, mod=0))
        self.assertEqual([g['id'] for g in app.visible], ['red', 'plat'])
        # A game added to the ROM folder later joins the collection without restarting.
        owned.add('blue')
        app.refresh()
        self.assertEqual([g['id'] for g in app.visible], ['red', 'blue', 'plat'])
        self.assertEqual(app.game['id'], 'plat')

    def test_grid_is_grouped_by_system_and_arrows_move_in_two_dimensions(self):
        games = [{'id': f'gb{i}', 'title': f'GB {i}', 'platform': 'GB', 'year': 1998} for i in range(6)]
        games += [{'id': 'nds0', 'title': 'DS 0', 'platform': 'NDS', 'year': 2007}]
        games.insert(2, {'id': 'gba0', 'title': 'GBA 0', 'platform': 'GBA', 'year': 2003})
        app = App(type('Catalogue', (), {'games': games})(), show_all=True)
        self.addCleanup(pygame.quit)
        ids = [g['id'] for g in app.visible]
        self.assertEqual(ids, ['gb0', 'gb1', 'gb2', 'gb3', 'gb4', 'gb5', 'gba0', 'nds0'])
        self.assertEqual([h[:2] for h in app.headers],
                         [('Game Boy', 6), ('Game Boy Advance', 1), ('Nintendo DS', 1)])
        self.assertEqual(app.rows, [[0, 1, 2, 3], [4, 5], [6], [7]])
        key = lambda k: app.event(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0))
        key(pygame.K_RIGHT); key(pygame.K_RIGHT); key(pygame.K_RIGHT)
        self.assertEqual(app.game['id'], 'gb3')
        key(pygame.K_DOWN)   # Row below is shorter: its last tile
        self.assertEqual(app.game['id'], 'gb5')
        key(pygame.K_DOWN); key(pygame.K_DOWN)
        self.assertEqual(app.game['id'], 'nds0')
        key(pygame.K_DOWN)   # Nothing below
        self.assertEqual(app.game['id'], 'nds0')
        self.assertGreater(app.scroll, 0)  # The last row was scrolled into view
        top = app.tiles[app.index].top - app.scroll
        self.assertTrue(0 <= top and app.tiles[app.index].bottom - app.scroll <= 414)
        app.event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=10))
        self.assertEqual(app.scroll, 0)
        app.draw()
        self.assertIn('tile:0', app.actions)

    def test_empty_collection_explains_how_to_add_games(self):
        class Library:
            rom_dir = None
            games = [{'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998}]
            def path(self, game):
                from unittest.mock import Mock
                return Mock(is_file=lambda: False)
            def found(self, game):
                return None

        app = App(Library())
        self.addCleanup(pygame.quit)
        texts = []
        original = app.text
        app.text = lambda text, *a, **k: (texts.append(text), original(text, *a, **k))
        app.draw()
        self.assertEqual(app.visible, [])
        self.assertIn('No Pokémon games in your collection yet.', texts)

    def test_rom_folder_location_is_never_shown(self):
        import tempfile, threading, time
        from pathlib import Path
        from library import Library

        with tempfile.TemporaryDirectory() as tmp:
            roms = Path(tmp) / 'secret-rom-place'
            roms.mkdir()
            gate = threading.Event()
            real_scan = Library.scan

            def slow_scan(library, *args, **kwargs):
                gate.wait(5)
                return real_scan(library, *args, **kwargs)

            from unittest.mock import patch
            with patch.object(Library, 'scan', slow_scan):
                app = App(Library(root=Path(tmp) / 'data', rom_dir=roms))
                self.addCleanup(pygame.quit)
                shown = [app.status]
                gate.set()
                deadline = time.monotonic() + 10
                while app.scanning and time.monotonic() < deadline:
                    time.sleep(.01)
                app.update()
                shown.append(app.status)
                texts = []
                original = app.text
                app.text = lambda text, *a, **k: (texts.append(text), original(text, *a, **k))
                original_wrapped = app.wrapped
                app.wrapped = lambda text, *a, **k: (texts.append(text), original_wrapped(text, *a, **k))[1]
                app.draw()
        self.assertFalse(app.scanning)
        self.assertEqual(shown, ['Loading your games…', ''])
        self.assertFalse([text for text in texts + shown if 'secret-rom-place' in text or tmp in text])
        self.assertFalse([text for text in texts + shown if 'ROM' in text])  # Nor that a ROM folder exists

    def test_missing_explicit_core_is_not_silently_replaced(self):
        with self.assertRaisesRegex(OSError, 'mGBA'):
            locate_core('/nonexistent/or/broken/core.so')
