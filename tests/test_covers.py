import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest

os.environ['SDL_VIDEODRIVER'] = 'dummy'
import pygame as pg

import covers


class CoverTest(unittest.TestCase):
    def setUp(self):
        pg.display.init()
        pg.font.init()
        covers.clear_caches()
        self.addCleanup(pg.quit)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.game = {'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998}

    def test_games_without_art_get_a_plain_card(self):
        surface = covers.generated_cover('Pokémon Red', 'GB', (112, 112))
        self.assertEqual(surface.get_size(), (112, 112))
        self.assertEqual(surface.get_at((56, 2))[:3], pg.Color('#9d9a93')[:3])        # System stripe
        self.assertEqual(surface.get_at((4, 60))[:3], pg.Color(covers.CARD_FILL)[:3])
        for platform in ('NDS', '3DS', 'N64', 'Switch', 'Unknown'):
            covers.generated_cover('A very long title that has to wrap several times', platform, (112, 112))

    def test_own_picture_beats_generated_cover_and_data_dir_beats_rom_folder(self):
        rom = self.root / 'roms' / 'Pokemon - Red Version (USA, Europe) (SGB Enhanced).gb'
        rom.parent.mkdir()
        rom.write_bytes(b'rom')
        self.assertIsNone(covers.find_cover(self.game, self.root / 'data', rom))
        beside = rom.with_suffix('.png')
        picture = pg.Surface((60, 80))
        picture.fill('#00ff00')
        pg.image.save(picture, beside)
        self.assertEqual(covers.find_cover(self.game, self.root / 'data', rom), beside)
        surface = covers.cover(self.game, (112, 128), beside)
        self.assertEqual(surface.get_size(), (96, 128))  # 60x80 scaled to fit, aspect kept
        self.assertEqual(surface.get_at((48, 64))[:3], (0, 255, 0))
        mine = self.root / 'data' / 'covers' / 'red.jpg'
        mine.parent.mkdir(parents=True)
        pg.image.save(picture, mine)
        self.assertEqual(covers.find_cover(self.game, self.root / 'data', rom), mine)

    def test_unreadable_picture_falls_back_to_generated_cover(self):
        broken = self.root / 'red.png'
        broken.write_bytes(b'not a png')
        surface = covers.cover(self.game, (112, 128), broken)
        self.assertEqual(surface.get_at((4, 60))[:3], pg.Color(covers.CARD_FILL)[:3])

    def test_oversized_picture_is_ignored(self):
        huge = self.root / 'data' / 'covers' / 'red.png'
        huge.parent.mkdir(parents=True)
        with huge.open('wb') as f:
            f.truncate(covers.MAX_IMAGE_BYTES + 1)
        self.assertIsNone(covers.find_cover(self.game, self.root / 'data'))


class BoxArtTest(unittest.TestCase):
    URL = 'https://raw.githubusercontent.com/libretro-thumbnails/Nintendo_-_Game_Boy/abc/Named_Boxarts/Red.png'

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.art = b'\x89PNG fake art bytes'
        self.served = {self.URL: self.art}
        self.fetched = []
        self.index = self.root / 'covers-index.json'
        self.write_index({'red': {'url': self.URL, 'size': len(self.art),
                                  'sha256': hashlib.sha256(self.art).hexdigest()}})
        self.game = {'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998}

    def write_index(self, covers_):
        self.index.write_text(json.dumps({'covers': covers_}))

    def opener(self, url):
        self.fetched.append(url)
        return io.BytesIO(self.served[url])

    def box_art(self, **kwargs):
        return covers.BoxArt(self.root / 'cache', self.index, opener=self.opener, **kwargs)

    def wait(self, art):
        """Until the background download finishes or fails (2 s at most)."""
        for _ in range(200):
            if art._done or art.failures:
                return
            threading.Event().wait(0.01)

    def test_downloads_pinned_art_once_and_verifies_it(self):
        art = self.box_art()
        self.assertIsNone(art.path(self.game))
        art.request(self.game)
        art.request(self.game)  # Already queued: not fetched twice
        self.wait(art)
        self.assertEqual(art.drain(), ['red'])
        self.assertEqual(self.fetched, [self.URL])
        self.assertEqual(art.path(self.game).read_bytes(), self.art)
        self.assertEqual([p.name for p in art.cache_dir.iterdir()], ['red.png'])  # No temp files left
        # A later start uses the cached file without fetching.
        again = self.box_art()
        self.assertEqual(again.path(self.game).read_bytes(), self.art)
        again.request(self.game)
        self.assertEqual(self.fetched, [self.URL])

    def test_rejects_bytes_that_do_not_match_the_index(self):
        self.served[self.URL] = b'\x89PNG tampered bytes!'
        art = self.box_art()
        art.request(self.game)
        self.wait(art)
        self.assertEqual(art.drain(), [])
        self.assertTrue(art.failures)
        self.assertIsNone(art.path(self.game))
        self.assertFalse((art.cache_dir / 'red.png').exists())

    def test_damaged_cache_is_downloaded_again(self):
        (self.root / 'cache').mkdir()
        (self.root / 'cache' / 'red.png').write_bytes(b'damaged')
        art = self.box_art()
        self.assertIsNone(art.path(self.game))
        art.request(self.game)
        self.wait(art)
        self.assertEqual(art.path(self.game).read_bytes(), self.art)

    def test_disabled_or_unlisted_games_never_fetch(self):
        self.box_art(enabled=False).request(self.game)
        self.box_art().request({'id': 'blue', 'title': 'Pokémon Blue', 'platform': 'GB', 'year': 1998})
        self.assertEqual(self.fetched, [])

    def test_index_entries_outside_libretro_thumbnails_are_ignored(self):
        good = {'size': 1, 'sha256': '0' * 64}
        self.write_index({'a': dict(good, url='https://example.com/a.png'),
                          'b': dict(good, url=self.URL, size=covers.MAX_ART_BYTES + 1),
                          'c': dict(good, url=self.URL, sha256='xyz'),
                          '../d': dict(good, url=self.URL),
                          'e': dict(good, url=self.URL)})
        self.assertEqual(set(self.box_art().index), {'e'})

    def test_packaged_index_covers_every_playable_release(self):
        from library import Library
        art = covers.BoxArt(self.root / 'cache')
        playable = {g['id'] for g in Library(root=self.root / 'lib').games if 'unavailable' not in g}
        self.assertEqual(playable - set(art.index), set())
        self.assertLessEqual(set(art.index), {g['id'] for g in Library(root=self.root / 'lib').games})


if __name__ == '__main__':
    unittest.main()
