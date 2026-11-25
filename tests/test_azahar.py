import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import support
from support import WINDOWS
from library import Library

# An Azahar stand-in (a real child process, not an emulator or a mock of
# Popen). Like Azahar, it keeps its data in the XDG directories on Linux, and
# on Windows in the "user" folder beside its program if there is one (portable
# mode), else in %APPDATA%\Azahar. It counts its runs there and reports what it saw.
STAND_IN = r'''
import json, os, sys
from pathlib import Path
if os.name == 'nt':
    portable = Path(sys.argv[0]).resolve().parent / 'user'
    data = portable if portable.is_dir() else Path(os.environ['APPDATA']) / 'Azahar'
    where = {'user': str(data)}
else:
    where = {k: os.environ[k] for k in ('XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME')}
    data = Path(where['XDG_DATA_HOME']) / 'azahar-emu'
data.mkdir(parents=True, exist_ok=True)
save = data / 'guest-marker'
count = int(save.read_text()) + 1 if save.exists() else 1
save.write_text(str(count))
report = {'argv': sys.argv[1:], 'cwd': os.getcwd(), 'where': where, 'count': count}
Path('child-report.json').write_text(json.dumps(report))
'''
# The usual per-user locations, which a launch must leave untouched.
ORDINARY = ('APPDATA',) if WINDOWS else ('XDG_DATA_HOME', 'XDG_CONFIG_HOME', 'XDG_CACHE_HOME')
# Directories that must not lead outside the profile.
PROFILE_ROOTS = ('user', 'user/config') if WINDOWS else ('data', 'config', 'cache', 'user')


class AzaharLaunchTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(stack)
        self.exe = support.program(self.root / 'Azahar stand-in', STAND_IN)
        self.rom = self.root / '-cart with spaces; $(literal).cci'
        self.rom.write_bytes(b'not a real cartridge')
        self.saves = self.root / 'my saves'
        self.enterContext(patch.dict(os.environ, {'RETRO_POCKET_AZAHAR': str(self.exe)}))

    def reject_launch(self, rom, game_id, error, message):
        from azahar_backend import launch

        with patch('azahar_backend.subprocess.Popen') as popen:
            with self.assertRaisesRegex(error, message):
                launch(rom, game_id, self.saves)
            popen.assert_not_called()

    def run_child(self, game_id='3ds-example'):
        from azahar_backend import launch

        child = launch(Path(os.path.relpath(self.rom)), game_id, self.saves)
        self.assertIsInstance(child, subprocess.Popen)
        try:
            self.assertEqual(child.wait(timeout=10), 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
        return json.loads((self.saves / 'azahar' / game_id / 'child-report.json').read_text())

    def test_passes_absolute_rom_as_one_positional_argument(self):
        seen = self.run_child()
        self.assertEqual(seen['argv'], [str(self.rom)])
        self.assertEqual(self.rom.read_bytes(), b'not a real cartridge')

    def test_uses_persistent_per_game_working_and_data_directories(self):
        ordinary = {name: str(self.root / f'usual-{name.lower()}') for name in ORDINARY}
        with patch.dict(os.environ, ordinary):
            first = self.run_child()
            second = self.run_child()
            other = self.run_child('3ds-other')
            self.assertEqual({k: os.environ[k] for k in ordinary}, ordinary)
        self.assertEqual([first['count'], second['count'], other['count']], [1, 2, 1])
        for game, seen in (('3ds-example', first), ('3ds-other', other)):
            profile = self.saves / 'azahar' / game
            self.assertEqual(Path(seen['cwd']).resolve(), profile.resolve())
            for location in seen['where'].values():
                self.assertTrue(Path(location).resolve().is_relative_to(profile.resolve()), location)
        for location in ordinary.values():
            self.assertFalse(Path(location).exists())

    def test_rejects_traversal_game_ids_before_creating_saves(self):
        for game_id in ('../escape', str(self.root / 'escape'), '3ds/escape', '..', '', '3ds\\escape'):
            with self.subTest(game_id=game_id):
                self.reject_launch(self.rom, game_id, ValueError, 'game ID')
        self.assertFalse(self.saves.exists())

    def test_requires_explicit_trusted_absolute_executable(self):
        for value in ('', self.exe.name, str(self.rom), str(self.root / 'missing')):
            with self.subTest(value=value), patch.dict(os.environ, {
                'RETRO_POCKET_AZAHAR': value, 'PATH': str(self.root),
            }):
                self.reject_launch(self.rom, '3ds-example', FileNotFoundError,
                                   'RETRO_POCKET_AZAHAR')
        self.assertFalse(self.saves.exists())

    def test_rejects_nonfile_rom_before_creating_saves(self):
        directory = self.root / 'directory.cci'
        directory.mkdir()
        for rom in (directory, self.root / 'missing.cci'):
            with self.subTest(rom=rom):
                self.reject_launch(rom, '3ds-example', FileNotFoundError, 'ROM')
        self.assertFalse(self.saves.exists())

    def test_does_not_install_cia_packages(self):
        package = self.rom.rename(self.rom.with_suffix('.cia'))
        self.reject_launch(package, '3ds-example', ValueError, 'ROM format')
        self.assertFalse(self.saves.exists())

    def test_refuses_linked_profile_roots(self):
        outside = self.root / 'outside'
        outside.mkdir()
        profile = self.saves / 'azahar' / '3ds-example'
        for path in (profile.parent, profile, *(profile / part for part in PROFILE_ROOTS)):
            with self.subTest(path=path):
                path.parent.mkdir(parents=True, exist_ok=True)
                support.directory_link(path, outside)
                try:
                    self.reject_launch(self.rom, '3ds-example', ValueError, 'profile')
                finally:
                    support.remove_link(path)
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(WINDOWS, 'Windows Azahar runs in portable mode from a per-game copy')
    def test_windows_profile_is_a_linked_portable_copy_of_azahar(self):
        from azahar_backend import config_file

        (self.root / 'Qt6Core.dll').write_bytes(b'library')
        (self.root / 'qt.conf').write_text('[Paths]\nPrefix = .\n')
        (self.root / 'plugins' / 'platforms').mkdir(parents=True)
        (self.root / 'plugins' / 'platforms' / 'qwindows.dll').write_bytes(b'plugin')
        (self.root / 'notes.txt').write_text('not part of the program')
        seen = self.run_child()
        profile = self.saves / 'azahar' / '3ds-example'
        self.assertEqual(Path(seen['where']['user']).resolve(), (profile / 'user').resolve())
        for name in (self.exe.name, 'Qt6Core.dll', 'qt.conf', 'plugins/platforms/qwindows.dll'):
            self.assertTrue(os.path.samefile(profile / name, self.root / name), name)  # Hard links
        self.assertFalse((profile / 'notes.txt').exists())
        self.assertIn('[Controls]', config_file(profile).read_text())


class AzaharAutodetectTests(unittest.TestCase):
    def test_autodetection_only_uses_fixed_paths(self):
        from azahar_backend import launch

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = support.program(root / 'azahar', 'import sys; sys.exit(0)\n')
            rom = root / 'game.3ds'
            rom.write_bytes(b'x')
            with patch.dict(os.environ, support.minimal_env(PATH=root), clear=True):
                with patch('azahar_backend._INSTALLED_EXECUTABLES', ()):
                    with self.assertRaisesRegex(FileNotFoundError, 'Azahar not found'):
                        launch(rom, '3ds-x', root / 'saves')
                self.assertFalse((root / 'saves').exists())
                with patch('azahar_backend._INSTALLED_EXECUTABLES', (root / 'missing', exe)):
                    self.assertEqual(launch(rom, '3ds-x', root / 'saves').wait(timeout=10), 0)


PROMOTED = {'3ds-x', '3ds-y', '3ds-omega-ruby', '3ds-alpha-sapphire',
            '3ds-sun', '3ds-moon', '3ds-ultra-moon'}


class AzaharCatalogueTests(unittest.TestCase):
    def test_verified_3ds_titles_are_playable_and_others_stay_catalogue_only(self):
        with tempfile.TemporaryDirectory() as root:
            library = Library(root=Path(root))
            games = {game['id']: game for game in library.games if game['platform'] == '3DS'}
            self.assertLessEqual(PROMOTED, set(games))
            for game_id, game in games.items():
                with self.subTest(game=game_id):
                    self.assertNotIn('download', game)
                    if game_id in PROMOTED:
                        self.assertNotIn('unavailable', game)
                        self.assertTrue(game['variants'])
                        self.assertEqual(library.path(game), Path(root) / f'{game_id}.3ds')
                    else:
                        self.assertEqual(game['variants'], [])
                        for action in (library.path, library.load,
                                       lambda row: library.import_rom(row, Path('not opened'))):
                            with self.assertRaises(ValueError):
                                action(game)

    def test_import_and_stage_verify_large_3ds_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            data = b'NCSD' * (1024 * 1024 + 3)
            game = dict(id='3ds-test', title='Test', year=2013, platform='3DS',
                        variants=[dict(label='USA', size=len(data), sha1=hashlib.sha1(data).hexdigest())])
            catalog = d / 'catalog.json'
            catalog.write_text(json.dumps([game]))
            library = Library(d / 'data', catalog)
            dump = d / 'dump.3ds'
            dump.write_bytes(data)
            self.assertEqual(library.import_rom(game, dump), d / 'data' / '3ds-test.3ds')
            stage = library.stage(game, d / 'stage' / '3ds-test.3ds')
            self.assertEqual(stage.read_bytes(), data)
            dump.write_bytes(data[:-1] + b'!')
            with self.assertRaisesRegex(ValueError, 'digest'):
                library.import_rom(game, dump)


class AzaharWorkerTests(unittest.TestCase):
    def test_worker_launches_azahar_on_a_verified_snapshot(self):
        import emulator_worker

        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            data = b'3ds image bytes'
            game = dict(id='3ds-test', title='Test', year=2013, platform='3DS',
                        variants=[dict(label='USA', size=len(data), sha1=hashlib.sha1(data).hexdigest())])
            catalog = d / 'catalog.json'
            catalog.write_text(json.dumps([game]))
            library = Library(d / 'data', catalog)
            dump = d / 'dump.3ds'
            dump.write_bytes(data)
            library.import_rom(game, dump)
            exe = support.program(d / 'azahar', (
                'import sys\nfrom pathlib import Path\n'
                'rom = Path(sys.argv[1])\n'
                'Path("seen.txt").write_text(f"{rom.name} {rom.read_bytes().decode()}")\n'))
            with patch.dict(os.environ, {'RETRO_POCKET_AZAHAR': str(exe)}):
                self.assertEqual(emulator_worker.run_game(library, '3ds-test'), 0)
            saves = d / 'data' / 'saves' / '3ds-test'
            self.assertEqual((saves / 'azahar' / '3ds-test' / 'seen.txt').read_text(),
                             '3ds-test.3ds 3ds image bytes')
            self.assertEqual(list(saves.glob(emulator_worker.SNAPSHOT_PREFIX + '*')), [])


class AzaharControlsTest(unittest.TestCase):
    def test_controls_are_seeded_once_and_user_remaps_survive(self):
        import azahar_backend

        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp)
            ini = azahar_backend.config_file(profile)
            ini.parent.mkdir(parents=True)
            ini.write_text('[Controls]\nprofile=0\nprofiles\\1\\button_a="code:65,engine:keyboard"\n'
                           'profiles\\1\\button_a\\default=true\nprofiles\\size=1\n\n[UI]\nkeep=1\n')
            azahar_backend._seed_controls(profile)
            text = ini.read_text()
            self.assertIn('profiles\\1\\button_a="code:88,engine:keyboard"\nprofiles\\1\\button_a\\default=false', text)
            self.assertNotIn('code:65,engine:keyboard"\nprofiles\\1\\button_a\\default=true', text)
            self.assertEqual(text.count('profiles\\size='), 1)
            self.assertTrue(text.endswith('[UI]\nkeep=1\n'))
            ini.write_text('[Controls]\nprofiles\\1\\button_a="code:75,engine:keyboard"\n')  # Remapped in Azahar.
            azahar_backend._seed_controls(profile)
            self.assertIn('code:75', ini.read_text())

    def test_symlinked_config_is_refused(self):
        import azahar_backend

        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp)
            ini = azahar_backend.config_file(profile)
            ini.parent.mkdir(parents=True)
            support.symlink(self, ini, profile / 'elsewhere')
            with self.assertRaises(ValueError):
                azahar_backend._seed_controls(profile)
            self.assertFalse((profile / 'elsewhere').exists())
