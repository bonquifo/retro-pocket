"""Updating an installed build from GitHub releases (updater.py), with local feeds and archives."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import support
import updater


def build_info(version, kind='windows', asset='Retro-Pocket-Windows.zip'):
    return json.dumps({'version': version, 'kind': kind, 'asset': asset, 'repository': 'someone/retro-pocket'})


def windows_zip(path, version, folder='Retro Pocket', extra=()):
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(f'{folder}/app.py', 'print("new")\n')
        archive.writestr(f'{folder}/build-info.json', build_info(version))
        archive.writestr(f'{folder}/roms/README.txt', 'dumps go here')
        for name, data in extra:
            archive.writestr(name, data)
    return path


def feed(path, tag, archive, digest=None, **changes):
    data = archive.read_bytes()
    release = {'tag_name': tag, 'draft': False, 'prerelease': False, 'html_url': 'https://example.invalid/release',
               'assets': [{'name': archive.name, 'size': len(data), 'browser_download_url': archive.as_uri(),
                           'digest': digest or 'sha256:' + hashlib.sha256(data).hexdigest()}]}
    release.update(changes)
    path.write_text(json.dumps(release))
    return path


class VersionTest(unittest.TestCase):
    def test_versions_order_releases_and_later_commits(self):
        parse = updater.parse_version
        self.assertEqual(parse('v1.2.3'), (1, 2, 3, 0))
        self.assertEqual(parse('1.2.3-4-gabc1234'), (1, 2, 3, 4))
        self.assertLess(parse('1.2.3'), parse('1.2.3-1-gabcdef0'))
        self.assertLess(parse('1.2.3-9-gabcdef0'), parse('1.2.4'))
        self.assertLess(parse('1.9.0'), parse('1.10.0'))
        for bad in ('', '1.2', 'v1.2.3.4', '1.2.3-beta', None, 'latest'):
            self.assertIsNone(parse(bad), bad)


class InstallationTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_each_system_replaces_its_own_root_and_keeps_its_roms(self):
        folder = self.root / 'Retro Pocket'
        folder.mkdir()
        (folder / 'build-info.json').write_text(build_info('1.0.0'))
        build = updater.installation(folder)
        self.assertEqual((build.version, build.kind, build.root, build.preserve), ('1.0.0', 'windows', folder, ('roms',)))
        self.assertEqual(build.repository, 'someone/retro-pocket')

        linux = self.root / 'retro-pocket'
        linux.mkdir()
        (linux / 'build-info.json').write_text(build_info('1.0.0', 'linux', 'Retro-Pocket-Linux.tar.gz'))
        self.assertEqual(updater.installation(linux).preserve, ('roms', '.venv'))

        app = self.root / 'Retro Pocket (Intel).app' / 'Contents' / 'Resources' / 'app'
        app.mkdir(parents=True)
        (app / 'build-info.json').write_text(build_info('1.0.0', 'macos', 'Retro-Pocket-macOS-Intel.zip'))
        mac = updater.installation(app)
        self.assertEqual((mac.root.name, mac.preserve), ('Retro Pocket (Intel).app', ()))

    def test_source_checkouts_and_broken_build_info_dont_update(self):
        self.assertIsNone(updater.installation(self.root))  # No build-info.json: a checkout
        for info in ('not json', '[]', build_info('one'), build_info('1.0.0', 'amiga'),
                     build_info('1.0.0', asset='../evil.zip')):
            with self.subTest(info=info):
                (self.root / 'build-info.json').write_text(info)
                self.assertIsNone(updater.installation(self.root))
        app = self.root / 'NotAnApp' / 'Contents' / 'Resources' / 'app'
        app.mkdir(parents=True)
        (app / 'build-info.json').write_text(build_info('1.0.0', 'macos'))
        self.assertIsNone(updater.installation(app))


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.archive = windows_zip(self.root / 'Retro-Pocket-Windows.zip', '1.1.0')
        self.build = updater.Installation('1.0.0', 'windows', 'Retro-Pocket-Windows.zip', 'someone/retro-pocket',
                                          self.root / 'install' / 'Retro Pocket', ('roms',))
        self.feed = self.root / 'feed.json'
        self.enterContext(patch.dict(os.environ, {updater.FEED_ENV: str(self.feed)}))

    def test_a_newer_release_with_this_systems_file_is_offered(self):
        feed(self.feed, 'v1.1.0', self.archive)
        release = updater.latest(self.build)
        self.assertEqual((release.version, release.asset, release.size), ('1.1.0', self.archive.name,
                                                                          self.archive.stat().st_size))
        self.assertEqual(release.sha256, hashlib.sha256(self.archive.read_bytes()).hexdigest())

    def test_same_older_unfinished_or_foreign_releases_are_not(self):
        for tag, changes in (('v1.0.0', {}), ('v0.9.0', {}), ('v1.1.0', {'prerelease': True}),
                             ('v1.1.0', {'draft': True}), ('nightly', {}),
                             ('v1.1.0', {'assets': []})):
            with self.subTest(tag=tag, changes=changes):
                feed(self.feed, tag, self.archive, **changes)
                self.assertIsNone(updater.latest(self.build))

    def test_a_release_without_a_published_digest_is_refused(self):
        feed(self.feed, 'v1.1.0', self.archive, digest='md5:abc')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            updater.latest(self.build)

    def test_real_releases_must_come_from_the_builds_own_repository_over_https(self):
        data = {'tag_name': 'v1.1.0', 'assets': [{
            'name': self.build.asset, 'size': 10, 'digest': 'sha256:' + '0' * 64,
            'browser_download_url': 'https://evil.example/Retro-Pocket-Windows.zip'}]}
        with patch.dict(os.environ, {updater.FEED_ENV: ''}), \
                patch('updater._latest_json', return_value=json.dumps(data)):
            with self.assertRaisesRegex(ValueError, 'outside someone/retro-pocket'):
                updater.latest(self.build)
            with self.assertRaisesRegex(ValueError, 'insecure'):
                updater._open('http://github.com/x', 5)

    def test_download_is_checked_against_size_and_sha256(self):
        feed(self.feed, 'v1.1.0', self.archive)
        release = updater.latest(self.build)
        seen = []
        path = updater.download(release, self.root / 'downloads', lambda done, total: seen.append((done, total)))
        self.assertEqual(path.read_bytes(), self.archive.read_bytes())
        self.assertEqual(seen[-1], (release.size, release.size))
        tampered = release.__class__(**{**release.__dict__, 'sha256': '0' * 64})
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            updater.download(tampered, self.root / 'other')
        self.assertEqual(list((self.root / 'other').iterdir()), [])  # Nothing half-written is left


class StageTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / 'install' / 'Retro Pocket').mkdir(parents=True)
        self.build = updater.Installation('1.0.0', 'windows', 'Retro-Pocket-Windows.zip', 'someone/retro-pocket',
                                          self.root / 'install' / 'Retro Pocket', ('roms',))
        self.release = updater.Release('1.1.0', 'v1.1.0', self.build.asset, 'file:', 1, '0' * 64, '')

    def test_update_is_unpacked_beside_the_installation_and_checked(self):
        archive = windows_zip(self.root / 'Retro-Pocket-Windows.zip', '1.1.0')
        new_root = updater.stage(self.build, self.release, archive)
        self.assertEqual(new_root.parent, updater.staging_folder(self.build))
        self.assertEqual(new_root.parent.parent, self.build.root.parent)  # Same drive: the swap is a rename
        self.assertEqual((new_root / 'app.py').read_text(), 'print("new")\n')

    def test_wrong_version_system_or_unsafe_archives_are_refused_and_cleaned_up(self):
        cases = {
            'wrong version': windows_zip(self.root / 'a.zip', '1.0.5'),
            'two folders': windows_zip(self.root / 'b.zip', '1.1.0', extra=[('Other/file', 'x')]),
            'escape': windows_zip(self.root / 'c.zip', '1.1.0', extra=[('../escaped', 'x')]),
        }
        linux = self.root / 'd.zip'
        with zipfile.ZipFile(linux, 'w') as archive:
            archive.writestr('retro-pocket/app.py', '')
            archive.writestr('retro-pocket/build-info.json', build_info('1.1.0', 'linux'))
        cases['other system'] = linux
        for problem, archive in cases.items():
            with self.subTest(problem=problem):
                with self.assertRaises(ValueError):
                    updater.stage(self.build, self.release, archive)
                self.assertFalse(updater.staging_folder(self.build).exists())
        self.assertFalse((self.root / 'escaped').exists())

    def test_linux_tarballs_are_unpacked_with_their_permissions(self):
        build = updater.Installation('1.0.0', 'linux', 'Retro-Pocket-Linux.tar.gz', 'x/y',
                                     self.root / 'install' / 'retro-pocket', ('roms', '.venv'))
        build.root.mkdir()
        archive = self.root / 'Retro-Pocket-Linux.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            for name, data, mode in (('retro-pocket/app.py', b'', 0o644), ('retro-pocket/setup.sh', b'#!/bin/sh\n', 0o755),
                                     ('retro-pocket/build-info.json', build_info('1.1.0', 'linux', build.asset).encode(), 0o644)):
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), mode
                tar.addfile(info, io.BytesIO(data))
        new_root = updater.stage(build, self.release.__class__(**{**self.release.__dict__, 'asset': build.asset}), archive)
        if os.name != 'nt':
            self.assertTrue(os.access(new_root / 'setup.sh', os.X_OK))
        self.assertTrue((new_root / 'app.py').is_file())


class ApplyTest(unittest.TestCase):
    """The real helper of this system (PowerShell on Windows, sh elsewhere) swaps the folders."""

    def test_helper_swaps_in_the_new_version_and_keeps_the_roms(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        kind = 'windows' if support.WINDOWS else 'linux'
        install = root / 'Retro Pocket'
        (install / 'roms').mkdir(parents=True)
        (install / 'roms' / 'my game.gb').write_bytes(b'game')
        (install / 'app.py').write_text('old')
        build = updater.Installation('1.0.0', kind, 'asset', 'x/y', install, ('roms',))
        new_root = updater.staging_folder(build) / 'Retro Pocket'
        (new_root / 'roms').mkdir(parents=True)
        (new_root / 'roms' / 'README.txt').write_text('new readme')
        (new_root / 'app.py').write_text('new')
        if kind == 'linux':
            (new_root / 'setup.sh').write_text('#!/bin/sh\necho set up\n')
            (new_root / 'setup.sh').chmod(0o755)
        running = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(1.5)'])  # The "library"
        log = root / 'data' / 'update.log'
        updater.apply(build, new_root, log, relaunch=False, pid=running.pid)
        running.wait(timeout=30)
        deadline = time.monotonic() + 120
        while 'updated' not in (log.read_text(errors='replace') if log.is_file() else ''):
            self.assertLess(time.monotonic(), deadline, log.read_text() if log.is_file() else 'no log')
            self.assertNotIn('FAILED', log.read_text() if log.is_file() else '')
            time.sleep(0.2)
        self.assertEqual((install / 'app.py').read_text(), 'new')
        self.assertEqual((install / 'roms' / 'my game.gb').read_bytes(), b'game')  # Carried over
        self.assertFalse(updater.staging_folder(build).exists())
        self.assertFalse(updater.old_folder(build).exists())


class UpdatesTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.build = updater.Installation('1.0.0', 'windows', 'Retro-Pocket-Windows.zip', 'x/y',
                                          self.root / 'Retro Pocket', ('roms',))
        self.release = updater.Release('1.1.0', 'v1.1.0', self.build.asset, 'https://x', 5, '0' * 64, 'https://page')

    def wait(self, updates, state):
        deadline = time.monotonic() + 10
        while updates.state != state and time.monotonic() < deadline:
            time.sleep(0.02)
        return updates.state

    def test_checks_at_most_once_a_day_and_remembers_the_answer(self):
        now = [1_000_000.0]
        with patch('updater.latest', return_value=self.release) as latest, \
                patch.dict(os.environ, {updater.FEED_ENV: '', updater.DISABLE_ENV: ''}):
            first = updater.Updates(self.root, self.build, clock=lambda: now[0])
            first.start()
            self.assertEqual(self.wait(first, 'available'), 'available')
            second = updater.Updates(self.root, self.build, clock=lambda: now[0] + 3600)
            second.start()
            self.assertEqual(self.wait(second, 'available'), 'available')
            self.assertEqual(second.release, self.release)
            self.assertEqual(latest.call_count, 1)  # The second start used the saved answer
            now[0] += updater.CHECK_EVERY + 1
            third = updater.Updates(self.root, self.build, clock=lambda: now[0])
            third.start()
            self.wait(third, 'available')
            self.assertEqual(latest.call_count, 2)

    def test_can_be_turned_off_and_is_off_for_source_checkouts(self):
        with patch('updater.latest') as latest:
            self.assertFalse(updater.Updates(self.root, None).enabled)
            self.assertFalse(updater.Updates(self.root, self.build, enabled=False).enabled)
            with patch.dict(os.environ, {updater.DISABLE_ENV: '1'}):
                self.assertFalse(updater.Updates(self.root, self.build).enabled)
            latest.assert_not_called()

    def test_next_start_reports_how_the_update_went(self):
        updates = updater.Updates(self.root, self.build, enabled=False)
        updates.pending_file.write_text(json.dumps({'version': '1.0.0'}))
        updates.start()
        self.assertEqual(updates.message, 'Updated to Retro Pocket 1.0.0.')
        updates.pending_file.write_text(json.dumps({'version': '9.0.0'}))
        updates.start()
        self.assertIn("couldn't be installed", updates.message)
        self.assertFalse(updates.pending_file.exists())


class LibraryButtonTest(unittest.TestCase):
    def test_update_button_downloads_then_restarts(self):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        import pygame
        from app import App

        game = {'id': 'red', 'title': 'Pokémon Red', 'platform': 'GB', 'year': 1998, 'unavailable': 'x'}
        app = App(type('Catalogue', (), {'games': [game]})())
        self.addCleanup(pygame.quit)
        release = updater.Release('1.1.0', 'v1.1.0', 'a.zip', 'https://x', 5, '0' * 64, 'https://page')
        app.updates.release, app.updates.state = release, 'available'
        app.draw()
        self.assertIn('Update to 1.1.0', app.actions)
        with patch.object(app.updates, 'can_install', return_value=True), patch.object(app.updates, 'install') as install:
            app.actions['Update to 1.1.0'][1]()
        install.assert_called_once()
        app.updates.state = 'ready'
        app.update()
        app.draw()
        self.assertIn('ready', app.status)
        with patch.object(app.updates, 'finish') as finish:
            app.actions['Restart to update'][1]()
        finish.assert_called_once_with(relaunch=True)
        self.assertFalse(app.running)  # The window closes; the helper installs the update
