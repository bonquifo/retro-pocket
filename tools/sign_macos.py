#!/usr/bin/env python3
"""Sign a macOS build with a Developer ID, have Apple notarize it, and staple the ticket.

    python tools/sign_macos.py dist/Retro-Pocket-macOS-Apple-Silicon.zip

Runs on a Mac (codesign, notarytool and stapler come with macOS and Xcode's
command line tools). The zip tools/build_macos.py made is replaced by the
signed, notarized one, so macOS opens the app straight away: Gatekeeper
accepts it as "Notarized Developer ID", even offline (the ticket is stapled).

Every program and library inside is signed with the hardened runtime and a
secure timestamp, inside out: libraries and programs first, then nested
bundles (the emulators' frameworks and apps) from the deepest, then the app.
Programs keep the entitlements their authors gave them (ares has some), plus
what the emulators and Python need under the hardened runtime: JIT and
unsigned executable memory (the emulators' recompilers, ctypes callbacks)
and libraries signed by others (such as a Vulkan driver). Entitlements a
Developer ID program can't have (debugging, provisioning-profile ones) go.

Credentials (CI passes its secrets in the environment):
  MACOS_CERTIFICATE_P12        Developer ID Application certificate and key: a .p12, base64
  MACOS_CERTIFICATE_PASSWORD   its password; it goes into a temporary keychain, deleted afterwards
  NOTARY_KEY                   App Store Connect API key for notarytool: the .p8 file's text
  NOTARY_KEY_ID, NOTARY_ISSUER_ID
On your own Mac, instead: --identity (a Developer ID Application identity in
your keychain) and --notary-profile (saved with `xcrun notarytool
store-credentials`). See README.md, "Signing the Mac apps".
"""
import argparse
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bundle  # noqa: E402
import build_macos  # noqa: E402

# Granted to every program, on top of its own entitlements.
ENTITLEMENTS = {
    'com.apple.security.cs.allow-jit': True,  # The emulators' recompilers (MAP_JIT)
    'com.apple.security.cs.allow-unsigned-executable-memory': True,  # Recompilers on Intel; ctypes callbacks
    'com.apple.security.cs.disable-library-validation': True,  # A Vulkan driver or plug-in signed by others
}
# Not allowed in Developer ID programs (get-task-allow: debugging), or needing a provisioning profile.
DROPPED = ('com.apple.security.get-task-allow', 'com.apple.developer.', 'com.apple.application-identifier',
           'keychain-access-groups')
BUNDLE_SUFFIXES = ('.app', '.framework', '.appex', '.xpc', '.bundle', '.plugin')
APPLE_CAS = ('https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer',
             'https://www.apple.com/certificateauthority/DeveloperIDCA.cer')
MH_EXECUTE = 2


def macho_type(path: Path):
    """The Mach-O file type of a file (2: program, 6: library, 8: loadable bundle), or None."""
    with open(path, 'rb') as file:
        head = file.read(64)
        if len(head) < 32:
            return None
        magic, = struct.unpack_from('>I', head, 0)
        if magic in (0xcafebabe, 0xcafebabf):  # Universal: the first architecture's header
            count, = struct.unpack_from('>I', head, 4)
            if not 0 < count < 10:  # Java class files share the magic number
                return None
            offset, = struct.unpack_from('>Q' if magic == 0xcafebabf else '>I', head, 16)
            file.seek(offset)
            head = file.read(32)
            if len(head) < 32:
                return None
        if head[:4] not in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe'):
            return None
        return struct.unpack_from('<I', head, 12)[0]


def is_bundle(path: Path):
    return (path.suffix in BUNDLE_SUFFIXES and path.is_dir() and not path.is_symlink()
            and any((path / name).exists() for name in ('Contents/Info.plist', 'Resources/Info.plist', 'Versions')))


def bundle_program(path: Path):
    """An app-like bundle's main program (Contents/MacOS/<CFBundleExecutable>), or None."""
    try:
        name = plistlib.loads((path / 'Contents' / 'Info.plist').read_bytes()).get('CFBundleExecutable')
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    program = path / 'Contents' / 'MacOS' / name if isinstance(name, str) and name else None
    return program if program and program.is_file() and not program.is_symlink() else None


def bundle_main(path: Path):
    """The file a bundle's own signature covers: an app's program, a framework's library (resolved)."""
    if path.suffix == '.framework':
        library = path / path.stem  # A link into Versions/Current
        return library.resolve() if library.is_file() else None
    program = bundle_program(path)
    return program.resolve() if program else None


@dataclass
class Plan:
    libraries: list   # Signed as they are
    programs: list    # Each with its entitlements
    bundles: list     # Nested bundles, deepest first; each signs its main file (an app's with its entitlements)
    app: Path         # Last


def plan(app: Path) -> Plan:
    """What to sign, in order. codesign signs a bundle's main file as the bundle, so those wait for theirs."""
    libraries, programs, bundles = [], [], []
    for folder, folders, files in os.walk(app):  # Symlinked folders are listed, never entered
        base = Path(folder)
        bundles += [base / name for name in folders if is_bundle(base / name)]
        for name in files:
            path = base / name
            if path.is_symlink():
                continue
            kind = macho_type(path)
            if kind == MH_EXECUTE:
                programs.append(path)
            elif kind is not None:
                libraries.append(path)
    mains = {bundle_main(nested) for nested in bundles} - {None}
    bundles.sort(key=lambda path: (-len(path.relative_to(app).parts), str(path)))
    return Plan(sorted(p for p in libraries if p.resolve() not in mains),
                sorted(p for p in programs if p.resolve() not in mains), bundles, app)


def entitlements_for(upstream: dict) -> dict:
    kept = {key: value for key, value in upstream.items() if not key.startswith(DROPPED)}
    return {**kept, **ENTITLEMENTS}


def _run(argv, attempts=1, **kwargs):
    """Run a tool; retry when Apple's timestamp or notary service is briefly unavailable."""
    for attempt in range(1, attempts + 1):
        result = subprocess.run([str(a) for a in argv], capture_output=True, text=True, **kwargs)
        if result.returncode == 0 or attempt == attempts:
            return result
        print(f'  {Path(argv[0]).name} failed (attempt {attempt}): {result.stderr.strip()[-300:]}; retrying')
        time.sleep(15 * attempt)


def _check(result, what):
    if result.returncode:
        raise RuntimeError(f'{what} failed (exit {result.returncode}):\n{(result.stdout + result.stderr).strip()[-3000:]}')
    return result


def current_entitlements(path: Path) -> dict:
    result = subprocess.run(['/usr/bin/codesign', '-d', '--entitlements', '-', '--xml', str(path)],
                            capture_output=True)
    start = result.stdout.find(b'<?xml')
    if result.returncode or start < 0:
        return {}  # Unsigned, or signed without entitlements
    return plistlib.loads(result.stdout[start:])


def sign(app: Path, identity: str, keychain=None):
    # Finder information or a quarantine mark would fail codesign --strict.
    _check(_run(['/usr/bin/xattr', '-cr', app]), 'clearing extended attributes')
    steps = plan(app)
    programs = steps.programs + [p for p in map(bundle_program, steps.bundles) if p and macho_type(p) == MH_EXECUTE]
    entitlements = {program: entitlements_for(current_entitlements(program)) for program in programs}
    common = ['--force', '--timestamp', '--options', 'runtime', '--sign', identity]
    if keychain:
        common += ['--keychain', keychain]
    with tempfile.TemporaryDirectory(prefix='retro-pocket-entitlements-') as folder:
        files = {}

        def entitlements_file(program):
            if program not in files:
                files[program] = Path(folder) / f'{len(files)}.plist'
                files[program].write_bytes(plistlib.dumps(entitlements[program]))
            return files[program]

        print(f'  signing {len(steps.libraries)} libraries, {len(steps.programs)} programs, '
              f'{len(steps.bundles)} nested bundles and the app')
        for start in range(0, len(steps.libraries), 40):
            chunk = steps.libraries[start:start + 40]
            _check(_run(['/usr/bin/codesign', *common, *chunk], attempts=3), 'signing libraries')
        for program in steps.programs:
            _check(_run(['/usr/bin/codesign', *common, '--entitlements', entitlements_file(program), program],
                        attempts=3), f'signing {program.relative_to(app)}')
        for nested in steps.bundles:  # Its main program is signed again with it: same entitlements
            program = bundle_program(nested)
            extra = ['--entitlements', entitlements_file(program)] if program in entitlements else []
            _check(_run(['/usr/bin/codesign', *common, *extra, nested], attempts=3),
                   f'signing {nested.relative_to(app)}')
        _check(_run(['/usr/bin/codesign', *common, app], attempts=3), f'signing {app.name}')
    _check(_run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', app]), 'codesign --verify')
    return steps


def _json(text):
    """notarytool's JSON output: the whole text, or its last line that is JSON."""
    for candidate in (text, *reversed(text.splitlines())):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {}


def notarize(app: Path, credentials, folder: Path):
    """Submit the app to Apple's notary service, wait for it, print its findings, staple the ticket."""
    submission = folder / f'{app.stem}-notarize.zip'
    _check(_run(['/usr/bin/ditto', '-c', '-k', '--keepParent', app, submission]), 'zipping for notarization')
    print(f'  notarizing ({submission.stat().st_size // (1024 * 1024)} MB; Apple usually takes a few minutes)')
    for attempt in range(1, 4):  # Again only if the upload itself failed (no submission id)
        result = _run(['/usr/bin/xcrun', 'notarytool', 'submit', submission, *credentials, '--wait',
                       '--timeout', '1h', '--output-format', 'json'])
        status = _json(result.stdout)
        if status.get('id') or attempt == 3:
            break
        print(f'  upload failed (attempt {attempt}): {(result.stdout + result.stderr).strip()[-300:]}; retrying')
        time.sleep(30 * attempt)
    if status.get('id'):
        log = _run(['/usr/bin/xcrun', 'notarytool', 'log', status['id'], *credentials], attempts=3)
        issues = _json(log.stdout).get('issues') or ([] if log.returncode == 0 else [log.stderr.strip()[-500:]])
        for issue in issues[:30]:
            print(f'  notary: {issue}')
    if status.get('status') != 'Accepted':
        raise RuntimeError(f'notarization: {status or (result.stdout + result.stderr).strip()[-2000:]}')
    print(f'  notarized: {status.get("id")}')
    _check(_run(['/usr/bin/xcrun', 'stapler', 'staple', app], attempts=3), 'stapling the ticket')
    _check(_run(['/usr/bin/xcrun', 'stapler', 'validate', app]), 'stapler validate')
    submission.unlink()


def gatekeeper(app: Path):
    """What Gatekeeper says about the app: 'accepted ... Notarized Developer ID' when all is well."""
    result = _run(['/usr/sbin/spctl', '--assess', '--type', 'execute', '--verbose=4', app])
    output = (result.stdout + result.stderr).strip()
    if result.returncode or 'accepted' not in output:
        raise RuntimeError(f'Gatekeeper rejects the app:\n{output}')
    return output


def zip_app(app: Path, zip_path: Path):
    """The app as a zip (bundle.Archive: Unix permissions and symlinks, no extended attributes)."""
    partial = zip_path.with_name(zip_path.name + '.part')
    out = bundle.Archive(partial, app.name)
    try:
        for folder, folders, files in os.walk(app):
            folders.sort()
            base = Path(folder)
            for name in sorted(folders) + sorted(files):
                path = base / name
                relative = path.relative_to(app).as_posix()
                if path.is_symlink():
                    out.link(relative, os.readlink(path))
                elif path.is_file():
                    out.file(relative, path.read_bytes(), stat.S_IMODE(path.lstat().st_mode))
    finally:
        out.close()
    partial.replace(zip_path)


class TemporaryKeychain:
    """A keychain holding just the Developer ID certificate, searched while signing, then deleted."""

    def __init__(self, folder: Path, p12_base64: str, password: str):
        self.path = folder / 'retro-pocket-signing.keychain-db'
        listed = _check(_run(['/usr/bin/security', 'list-keychains', '-d', 'user']), 'listing keychains')
        self.previous = [line.strip().strip('"') for line in listed.stdout.splitlines() if line.strip()]
        try:
            self._create(folder, p12_base64, password)
        except BaseException:
            self.close()
            raise

    def _create(self, folder, p12_base64, password):
        secret = secrets.token_urlsafe(24)
        for argv in (['create-keychain', '-p', secret, self.path],
                     ['set-keychain-settings', '-lut', '21600', self.path],
                     ['unlock-keychain', '-p', secret, self.path]):
            _check(_run(['/usr/bin/security', *argv]), f'security {argv[0]}')
        certificate = folder / 'certificate.p12'
        certificate.touch(0o600)
        certificate.write_bytes(base64.b64decode(''.join(p12_base64.split())))
        try:
            _check(_run(['/usr/bin/security', 'import', certificate, '-k', self.path, '-P', password,
                         '-f', 'pkcs12', '-T', '/usr/bin/codesign']), 'importing the certificate')
        finally:
            certificate.unlink()
        for url in APPLE_CAS:  # Apple's intermediate certificates, for the signature's chain
            authority = folder / url.rsplit('/', 1)[1]
            if _run(['/usr/bin/curl', '-fsSL', '--retry', '3', '-o', authority, url]).returncode == 0:
                _run(['/usr/bin/security', 'import', authority, '-k', self.path])
        _check(_run(['/usr/bin/security', 'set-key-partition-list', '-S', 'apple-tool:,apple:,codesign:', '-s',
                     '-k', secret, self.path]), 'allowing codesign to use the key')
        _check(_run(['/usr/bin/security', 'list-keychains', '-d', 'user', '-s', self.path, *self.previous]),
               'adding the keychain to the search list')
        found = _run(['/usr/bin/security', 'find-identity', '-v', '-p', 'codesigning', self.path]).stdout
        identities = re.findall(r'\b([0-9A-F]{40}) "Developer ID Application: [^"]*\(([A-Z0-9]+)\)"', found)
        if not identities:
            raise RuntimeError('MACOS_CERTIFICATE_P12 holds no "Developer ID Application" certificate with its key')
        self.identity, self.team = identities[0]

    def close(self):
        _run(['/usr/bin/security', 'list-keychains', '-d', 'user', '-s', *self.previous])
        _run(['/usr/bin/security', 'delete-keychain', self.path])


def notary_credentials(args, folder: Path):
    if os.environ.get('NOTARY_KEY'):
        key = folder / 'notary-key.p8'
        key.touch(0o600)
        key.write_text(os.environ['NOTARY_KEY'].strip() + '\n', encoding='utf-8')
        credentials = ['--key', key, '--key-id', os.environ.get('NOTARY_KEY_ID', '').strip()]
        issuer = os.environ.get('NOTARY_ISSUER_ID', '').strip()
        return credentials + (['--issuer', issuer] if issuer else [])  # An individual key has no issuer
    if args.notary_profile:
        return ['--keychain-profile', args.notary_profile]
    raise SystemExit('Notarizing needs NOTARY_KEY, NOTARY_KEY_ID and NOTARY_ISSUER_ID, or --notary-profile '
                     '(or --no-notarize to sign only)')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Sign a macOS build with a Developer ID and notarize it.')
    parser.add_argument('archive', type=Path, help='a zip from tools/build_macos.py; replaced by the signed one')
    parser.add_argument('--identity', help='a Developer ID Application identity in your keychain (name or SHA-1)')
    parser.add_argument('--notary-profile', help='notarytool credentials saved with store-credentials')
    parser.add_argument('--no-notarize', action='store_true', help='sign only')
    args = parser.parse_args(argv)
    if sys.platform != 'darwin':
        raise SystemExit('Signing needs a Mac (codesign, notarytool, stapler)')
    archive = args.archive.resolve()
    target = next((t for t in build_macos.TARGETS.values() if build_macos.zip_name(t) == archive.name), None)
    if target is None:
        raise SystemExit(f'{archive.name} is not a zip from tools/build_macos.py')
    folder = Path(tempfile.mkdtemp(prefix='retro-pocket-sign-'))
    keychain = None
    try:
        if os.environ.get('MACOS_CERTIFICATE_P12'):
            keychain = TemporaryKeychain(folder, os.environ['MACOS_CERTIFICATE_P12'],
                                         os.environ.get('MACOS_CERTIFICATE_PASSWORD', ''))
            identity, team = keychain.identity, keychain.team
        elif args.identity:
            identity, team = args.identity, '?'
        else:
            raise SystemExit('Signing needs MACOS_CERTIFICATE_P12 and MACOS_CERTIFICATE_PASSWORD, or --identity')
        credentials = None if args.no_notarize else notary_credentials(args, folder)
        unpacked = folder / 'app'
        _check(_run(['/usr/bin/ditto', '-x', '-k', archive, unpacked]), 'unpacking')
        app = next(unpacked.glob('*.app'))
        print(f'{app.name}: signing with the Developer ID of team {team}')
        sign(app, identity, keychain.path if keychain else None)
        if credentials:
            notarize(app, credentials, folder)
            # Only the source line: the origin line names the certificate's owner.
            print('  Gatekeeper: accepted, ' + ', '.join(line for line in gatekeeper(app).splitlines()
                                                       if line.startswith('source=')))
        zip_app(app, archive)
        build_macos.verify(archive, target)
        print(f'  {archive} ({archive.stat().st_size // (1024 * 1024)} MB, signed'
              f'{", notarized and stapled" if credentials else ""}, checked)')
    finally:
        if keychain:
            keychain.close()
        shutil.rmtree(folder, ignore_errors=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
