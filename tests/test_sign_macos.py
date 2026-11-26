"""tools/sign_macos.py's plan: what is signed, in which order, with which entitlements; its zip."""
import os
from pathlib import Path
import plistlib
import shutil
import stat
import struct
import sys
import tempfile
import unittest

import support

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import sign_macos  # noqa: E402
import updater  # noqa: E402

WINDOWS = os.name == 'nt'


def posix_links(folder: Path):
    """Whether symlinks work as in a Mac app: Windows can't follow 'Versions/Current/X' (forward slashes)."""
    return not WINDOWS and support.can_symlink(folder)


def macho(filetype, cpu=0x0100000c):
    """A 64-bit Mach-O header (no load commands) of the given file type."""
    return struct.pack('<IIIIIIII', 0xfeedfacf, cpu, 0, filetype, 0, 0, 0, 0) + b'\0' * 64


def universal(filetype):
    """A universal file whose first architecture (at offset 4096) has ``filetype``."""
    header = struct.pack('>II', 0xcafebabe, 2) + struct.pack('>IIIII', 0x01000007, 3, 4096, 96, 12) \
        + struct.pack('>IIIII', 0x0100000c, 0, 8192, 96, 14)
    return header.ljust(4096, b'\0') + macho(filetype, 0x01000007).ljust(4096, b'\0') + macho(filetype)


def write(path: Path, data: bytes, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)
    return path


def app_bundle(path: Path, program: str, data: bytes):
    write(path / 'Contents' / 'Info.plist', plistlib.dumps({'CFBundleExecutable': program}))
    return write(path / 'Contents' / 'MacOS' / program, data, 0o755)


class MachOTypeTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)

    def type_of(self, data):
        return sign_macos.macho_type(write(self.folder / 'file', data))

    def test_types(self):
        self.assertEqual(self.type_of(macho(2)), sign_macos.MH_EXECUTE)
        self.assertEqual(self.type_of(macho(6)), 6)
        self.assertEqual(self.type_of(universal(8)), 8)  # Read from the first architecture's header

    def test_not_mach_o(self):
        self.assertIsNone(self.type_of(b'#!/bin/sh\necho hello\n' * 4))
        self.assertIsNone(self.type_of(b'\xca\xfe\xba\xbe\x00\x00\x00\x34' + b'\0' * 64))  # A Java class
        self.assertIsNone(self.type_of(b'\xcf\xfa\xed\xfe'))  # Too short


class PlanTest(unittest.TestCase):
    """The order codesign needs: inside out, and a bundle's main file only with its bundle."""

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.app = app = self.folder / 'Retro Pocket (Apple Silicon).app'
        write(app / 'Contents' / 'Info.plist', plistlib.dumps({'CFBundleExecutable': 'RetroPocket'}))
        write(app / 'Contents' / 'MacOS' / 'RetroPocket', b'#!/bin/sh\nexec python3.12 app.py\n', 0o755)
        self.python = write(app / 'Contents' / 'MacOS' / 'python3.12', macho(2), 0o755)
        self.extension = write(app / 'Contents/Resources/python/lib/python3.12/lib-dynload/_ssl.so', macho(8))
        write(app / 'Contents/Resources/app/app.py', b'print("hello")\n')
        emulators = app / 'Contents/Resources/app/emulators'
        self.melonds = emulators / 'melonds' / 'melonDS.app'
        app_bundle(self.melonds, 'melonDS', universal(2))
        self.azahar = emulators / 'azahar' / 'Azahar.app'
        app_bundle(self.azahar, 'azahar', macho(2))
        self.plugin = write(self.azahar / 'Contents/PlugIns/platforms/libqcocoa.dylib', macho(6))
        self.framework = self.azahar / 'Contents/Frameworks/QtCore.framework'
        self.qtcore = write(self.framework / 'Versions/A/QtCore', macho(6))
        if posix_links(self.folder):
            (self.framework / 'Versions/Current').symlink_to('A', target_is_directory=True)
            (self.framework / 'QtCore').symlink_to('Versions/Current/QtCore')
        else:  # No symlinks here: the library at the framework's top instead
            self.qtcore.unlink()
            self.qtcore = write(self.framework / 'QtCore', macho(6))

    def test_order(self):
        steps = sign_macos.plan(self.app)
        self.assertEqual(steps.libraries, sorted([self.extension, self.plugin]))
        self.assertEqual(steps.programs, [self.python])  # The emulators' programs go with their apps
        self.assertEqual(steps.bundles[0], self.framework)  # Deepest first
        self.assertEqual(set(steps.bundles[1:]), {self.azahar, self.melonds})
        self.assertNotIn(self.app, steps.bundles)
        self.assertEqual(sign_macos.bundle_main(self.framework), self.qtcore.resolve())
        self.assertEqual(sign_macos.bundle_main(self.azahar), (self.azahar / 'Contents/MacOS/azahar').resolve())

    def test_bundles_need_their_layout(self):
        write(self.app / 'Contents/Resources/app/notes.bundle', b'just a file named like a bundle\n')
        (self.app / 'Contents/Resources/app/empty.app').mkdir()
        self.assertNotIn('notes.bundle', [path.name for path in sign_macos.plan(self.app).bundles])
        self.assertNotIn('empty.app', [path.name for path in sign_macos.plan(self.app).bundles])


class EntitlementsTest(unittest.TestCase):
    def test_kept_added_and_dropped(self):
        upstream = {
            'com.apple.security.cs.disable-library-validation': True,  # ares has these two
            'com.apple.security.cs.allow-unsigned-executable-memory': True,
            'com.apple.security.device.audio-input': True,
            'com.apple.security.get-task-allow': True,  # A debug build's: notarization refuses it
            'com.apple.developer.team-identifier': 'ABCDE12345',  # Needs a provisioning profile
            'com.apple.application-identifier': 'ABCDE12345.dev.example',
        }
        result = sign_macos.entitlements_for(upstream)
        self.assertEqual(result, {**sign_macos.ENTITLEMENTS, 'com.apple.security.device.audio-input': True})
        self.assertTrue(result['com.apple.security.cs.allow-jit'])
        self.assertEqual(sign_macos.entitlements_for({}), sign_macos.ENTITLEMENTS)


class ZipTest(unittest.TestCase):
    """The signed app's zip unpacks, through the updater, to exactly the same files."""

    def test_round_trip(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        app = folder / 'signed' / 'Retro Pocket (Intel).app'
        files = {
            'Contents/Info.plist': (plistlib.dumps({'CFBundleExecutable': 'RetroPocket'}), 0o644),
            'Contents/MacOS/RetroPocket': (b'#!/bin/sh\n', 0o755),
            'Contents/MacOS/python3.12': (macho(2, 0x01000007), 0o755),
            'Contents/_CodeSignature/CodeResources': (b'<plist/>', 0o644),
            'Contents/Resources/app/emulators/ares/ares.app/Contents/MacOS/ares': (universal(2), 0o755),
        }
        for name, (data, mode) in files.items():
            write(app / name, data, mode)
        links = posix_links(folder)
        if links:
            framework = app / 'Contents/Frameworks/Example.framework'
            write(framework / 'Versions/A/Example', macho(6))
            (framework / 'Versions/Current').symlink_to('A', target_is_directory=True)
            (framework / 'Example').symlink_to('Versions/Current/Example')
        archive = folder / 'Retro-Pocket-macOS-Intel.zip'
        sign_macos.zip_app(app, archive)
        unpacked = folder / 'unpacked'
        updater._unzip(archive, unpacked)
        copy = unpacked / app.name
        for name, (data, mode) in files.items():
            self.assertEqual((copy / name).read_bytes(), data, name)
            if not WINDOWS:
                self.assertEqual(stat.S_IMODE((copy / name).stat().st_mode), mode, name)
        if links:
            self.assertEqual(os.readlink(copy / 'Contents/Frameworks/Example.framework/Versions/Current'), 'A')
            self.assertEqual((copy / 'Contents/Frameworks/Example.framework/Example').read_bytes(), macho(6))
        self.assertFalse(archive.with_name(archive.name + '.part').exists())


if __name__ == '__main__':
    unittest.main()
