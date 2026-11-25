import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from library import Library


def title(id, platform='GB', **kwargs):
    return dict(id=id, title=id, platform=platform, year=2000, **kwargs)


class ExpandedLibrary(unittest.TestCase):
    def test_disc_images_keep_extension_required_by_dolphin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / 'test.json'
            games = [title(p.lower(), p, variants=[dict(label='test', size=21, sha1='0' * 40)])
                     for p in ('GCN', 'Wii')]
            catalog.write_text(json.dumps(games))
            library = Library(root / 'cache', catalog)
            for game in games:
                self.assertEqual(library.path(game).suffix, '.iso')

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'no FIFOs in the filesystem on this platform')
    def test_import_rejects_fifo_without_waiting_for_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = Library(root / 'cache')
            fifo = root / 'not-a-cartridge'
            os.mkfifo(fifo)
            # The legacy blocking open is exercised from a subprocess with a timeout.
            import subprocess
            import sys
            script = ('from library import Library; from pathlib import Path; import sys; '
                      'lib = Library(Path(sys.argv[2])); lib.import_rom(lib.games[0], Path(sys.argv[1]))')
            job = subprocess.run([sys.executable, '-c', script, str(fifo), str(library.root)],
                                 capture_output=True, text=True, timeout=2)
            self.assertNotEqual(job.returncode, 0)
            self.assertIn('regular file', job.stderr)

    def test_nds_is_verified_and_cached_using_the_nds_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = b'original test fixture'
            game = title('ds', 'NDS', variants=[dict(label='test', size=len(data), sha1=hashlib.sha1(data).hexdigest())])
            catalog = root / 'test.json'
            catalog.write_text(json.dumps([game]))
            library = Library(root / 'cache', catalog)
            original = root / 'cart.nds'
            original.write_bytes(data)
            self.assertEqual(library.import_rom(game, original).suffix, '.nds')
            self.assertEqual(library.load(game), data)

    def test_catalog_only_game_has_no_cache_path_or_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            game = title('switch-title', 'Switch', variants=[], unavailable='No Switch backend')
            catalog = root / 'test.json'
            catalog.write_text(json.dumps([game]))
            library = Library(root / 'cache', catalog)
            self.assertEqual(library.games, [game])
            for method, args in ((library.path, (game,)), (library.load, (game,)), (library.import_rom, (game, root / 'cart'))):
                with self.assertRaisesRegex(ValueError, 'No Switch backend'):
                    method(*args)

    def test_merge_in_fixed_order_and_reject_duplicates(self):
        from library import _load_catalogs
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            primary = root / 'catalog.json'
            primary.write_text('[{"id":"first"}]')
            (root / 'catalog-z.json').write_text('[{"id":"last"}]')
            (root / 'catalog-a.json').write_text('[{"id":"second"}]')
            self.assertEqual([g['id'] for g in _load_catalogs(primary, True)], ['first', 'second', 'last'])
            self.assertEqual(_load_catalogs(primary, False), [{'id':'first'}])
            entry = title('first', 'Switch', variants=[], unavailable='No backend')
            primary.write_text(json.dumps([entry]))
            (root / 'catalog-a.json').write_text(json.dumps([entry]))
            with self.assertRaisesRegex(ValueError, 'Duplicate catalog game ID'):
                Library(root / 'cache', None, base_catalog=primary)

    def test_empty_catalog_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog = root / 'test.json'
            catalog.write_text('[]')
            with self.assertRaisesRegex(ValueError, 'empty'):
                Library(root / 'cache', catalog)
