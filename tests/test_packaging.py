"""The emulator installer's archive handling and the macOS app build's checks, with synthetic files."""
import io
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import build_linux  # noqa: E402
import bundle  # noqa: E402
import build_macos  # noqa: E402
import build_windows  # noqa: E402
import install_emulators  # noqa: E402
import tarfile  # noqa: E402

ARM64, X86_64 = 0x0100000c, 0x01000007


def macho(cpu, signed=True):
    """A minimal 64-bit Mach-O header with one load command (a code signature, or a UUID)."""
    command = struct.pack('<IIII', 0x1d if signed else 0x1b, 16, 0, 0)
    return struct.pack('<IIIIIIII', 0xfeedfacf, cpu, 0, 2, 1, len(command), 0, 0) + command + bytes(64)


def universal(*slices):
    header = struct.pack('>II', 0xcafebabe, len(slices))
    offset, body, table = 4096, b'', b''
    for cpu, data in slices:
        table += struct.pack('>iiIII', cpu, 0, offset + len(body), len(data), 12)
        body += data
    return (header + table).ljust(4096, b'\0') + body


def unix_zip(entries):
    """entries: (name, data, mode, is_link)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data, mode, link in entries:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = ((stat.S_IFLNK if link else stat.S_IFREG) | mode) << 16
            archive.writestr(info, data)
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


class ArchiveTest(unittest.TestCase):
    def test_single_top_folder_is_removed_unless_it_is_the_app(self):
        folder = unix_zip([('azahar-macos/Azahar.app/Contents/MacOS/azahar', b'x', 0o755, False),
                           ('azahar-macos/README', b'r', 0o644, False)])
        self.assertEqual([str(e.path) for e in install_emulators.entries(folder)],
                         ['Azahar.app/Contents/MacOS/azahar', 'README'])
        app = unix_zip([('melonDS.app/Contents/MacOS/melonDS', b'x', 0o755, False),
                        ('melonDS.app/Contents/Info.plist', b'p', 0o644, False)])
        entries = install_emulators.entries(app)
        self.assertEqual(str(entries[0].path), 'melonDS.app/Contents/MacOS/melonDS')
        self.assertEqual(entries[0].mode, 0o755)

    def test_links_are_kept_inside_the_package_and_unsafe_names_refused(self):
        framework = 'ares.app/Contents/Frameworks/SDL3.framework'
        ok = unix_zip([(f'{framework}/Versions/A/SDL3', b'lib', 0o755, False),
                       (f'{framework}/Versions/Current', b'A', 0o755, True),
                       (f'{framework}/SDL3', b'Versions/Current/SDL3', 0o755, True)])
        links = {str(e.path): e.link for e in install_emulators.entries(ok) if e.link}
        self.assertEqual(links[f'{framework}/SDL3'], 'Versions/Current/SDL3')
        for bad in ([('x.app/link', b'../../../etc', 0o755, True)], [('x.app/link', b'/etc/passwd', 0o755, True)],
                    [('../escape', b'x', 0o644, False)], [('C:/windows', b'x', 0o644, False)]):
            with self.subTest(bad=bad[0][:2]), self.assertRaises(ValueError):
                install_emulators.entries(unix_zip(bad))

    def test_architectures_of_windows_and_mac_programs(self):
        pe = bytearray(512)
        pe[:2] = b'MZ'
        struct.pack_into('<I', pe, 0x3C, 0x80)
        pe[0x80:0x86] = b'PE\0\0' + struct.pack('<H', 0x8664)
        self.assertEqual(install_emulators.header_architectures(bytes(pe)), {'x86_64'})
        self.assertEqual(install_emulators.header_architectures(macho(ARM64)), {'arm64'})
        fat = universal((X86_64, macho(X86_64)), (ARM64, macho(ARM64)))
        self.assertEqual(install_emulators.header_architectures(fat[:4096]), {'x86_64', 'arm64'})
        self.assertEqual(install_emulators.header_architectures(b'#!/bin/sh\n'), set())

    def test_every_platform_pins_its_releases(self):
        for platform, packages in install_emulators.PLATFORMS.items():
            for name, package in packages.items():
                with self.subTest(platform=platform, package=name):
                    if name == 'mgba':
                        self.assertIsNone(package.sha256)  # Nightly only: checked by architecture instead
                        self.assertIsNotNone(package.arch)
                    else:
                        self.assertRegex(package.sha256, '^[0-9a-f]{64}$')
                        self.assertGreater(package.size, 0)
                    self.assertTrue(package.url.startswith('https://'))
        self.assertEqual(set(install_emulators.PLATFORMS['macos-arm64']), {'mgba', 'melonds', 'ares', 'azahar'})


class MacBuildCheckTest(unittest.TestCase):
    def build(self, files, arch='arm64'):
        """A minimal app zip; files: name -> (data, mode)."""
        target = build_macos.TARGETS[arch]
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = tmp / 'app.zip'
        out = build_macos.AppZip(path, 'Retro Pocket.app')
        for name, (data, mode) in files.items():
            if mode == 'link':
                out.link(name, data)
            else:
                out.file(name, data, mode)
        out.close()
        return path, target

    def complete(self, **changes):
        files = {name: (b'#!/bin/sh\n' if executable else b'data', 0o755 if executable else 0o644)
                 for name, executable in build_macos.REQUIRED.items()}
        files['Contents/MacOS/python3.12'] = (macho(ARM64), 0o755)
        files.update(changes)
        return files

    def test_a_complete_app_passes(self):
        build_macos.verify(*self.build(self.complete()))

    def test_problems_a_mac_would_hit_are_reported(self):
        cases = {
            'missing': self.complete(**{'Contents/MacOS/RetroPocket': None}),
            'not executable': self.complete(**{'Contents/MacOS/RetroPocket': (b'#!/bin/sh\n', 0o644)}),
            'no arm64 code': self.complete(**{'Contents/Resources/app/emulators/x.dylib': (macho(X86_64), 0o755)}),
            'unsigned arm64': self.complete(**{'Contents/Resources/lib.so': (macho(ARM64, signed=False), 0o755)}),
            'broken link': self.complete(**{'Contents/Frameworks/X.framework/X': ('Versions/Current/X', 'link')}),
        }
        for problem, files in cases.items():
            with self.subTest(problem=problem):
                files = {name: value for name, value in files.items() if value is not None}
                with self.assertRaisesRegex(ValueError, problem):
                    build_macos.verify(*self.build(files))

    def test_universal_code_passes_for_both_architectures_and_intel_needs_no_signature(self):
        fat = universal((X86_64, macho(X86_64, signed=False)), (ARM64, macho(ARM64)))
        for arch in ('arm64', 'x86_64'):
            with self.subTest(arch=arch):
                build_macos.verify(*self.build(self.complete(**{
                    'Contents/MacOS/python3.12': (fat, 0o755)}), arch))

    def test_linux_tarball_has_runnable_scripts_and_no_windows_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = build_linux.build(Path(tmp))
            with tarfile.open(path) as tar:
                members = {m.name.split('/', 1)[1]: m for m in tar.getmembers()}
        for script in ('setup.sh', 'RetroPocket.sh'):
            self.assertEqual(members[script].mode & 0o777, 0o755, script)
        self.assertIn('ds_input_shim.c', members)  # The Linux DeSmuME keyboard fix is built at launch
        self.assertIn('roms/README.txt', members)
        self.assertNotIn('_win32.py', members)

    def test_windows_check_finds_missing_files_and_foreign_binaries(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = tmp / 'windows.zip'
        out = build_macos.AppZip(path, build_windows.FOLDER)
        arm = bytearray(512)
        arm[:2] = b'MZ'
        struct.pack_into('<I', arm, 0x3C, 0x80)
        arm[0x80:0x86] = b'PE\0\0' + struct.pack('<H', 0xAA64)  # 64-bit Arm
        out.file('python/python.exe', bytes(arm))
        out.close()
        with self.assertRaises(ValueError) as caught:
            build_windows.verify(path)
        self.assertIn('missing app.py', str(caught.exception))
        self.assertIn('not a 64-bit x86 Windows binary: python/python.exe', str(caught.exception))

    def test_bytecode_needs_no_timestamp(self):
        compiled = bundle.pyc(b'x = 1\n', 'x.py')
        if sys.version_info[:2] != (3, 12):
            self.assertIsNone(compiled)
        else:
            import importlib.util
            self.assertEqual(compiled[:4], importlib.util.MAGIC_NUMBER)
            self.assertEqual(struct.unpack('<I', compiled[4:8])[0], 1)  # Hash-based, not checked
