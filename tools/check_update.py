#!/usr/bin/env python3
"""End-to-end update test: an older copy of a build updates itself to that build.

    python tools/check_update.py dist/Retro-Pocket-Windows.zip      # or a macOS zip, or the Linux tarball

The build is unpacked as an installation that says it is version 0.0.1,
with a file in its ROM folder (and, on Linux, its Python environment set
up). A feed in the format of GitHub's release API offers the build as the
newest release, with its real size and SHA-256 and a file: address. The old
copy then runs `app.py --update`, the same download, check, stage and
hand-over a user's update goes through, and this waits for the helper to
finish and checks that:

  - the installation now is the new version, and starts (--version)
  - the ROM folder (and Linux's Python environment) came along
  - the helper left no staging or old folders behind and logged no failure
  - with --signed (macOS): the updated app's Developer ID signature and
    stapled notarization ticket are intact, as macOS checks them

CI runs it on every build of all four versions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import updater  # noqa: E402

OLD_VERSION = '0.0.1'


def kind_of(archive: Path):
    if archive.name.endswith('.tar.gz'):
        return 'linux'
    return 'macos' if 'macOS' in archive.name else 'windows'


def command(kind, root: Path, *arguments):
    """Run the installed copy's app.py the way that system starts it."""
    app = updater.app_folder(kind, root) / 'app.py'
    if kind == 'windows':
        return [str(root / 'python' / 'python.exe'), str(app), *arguments]
    if kind == 'macos':
        return [str(root / 'Contents' / 'MacOS' / 'RetroPocket'), *arguments]
    return [str(root / '.venv' / 'bin' / 'python'), str(app), *arguments]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('archive', type=Path)
    parser.add_argument('--timeout', type=int, default=600, help='seconds to wait for the helper')
    parser.add_argument('--signed', action='store_true',
                        help="macOS: the updated app's signature and notarization ticket must hold")
    args = parser.parse_args(argv)
    archive = args.archive.resolve()
    kind = kind_of(archive)
    work = Path(tempfile.mkdtemp(prefix='retro-pocket-update-check-'))
    data = work / 'data'
    install = work / 'install'
    install.mkdir()
    print(f'{kind}: installing {archive.name} as version {OLD_VERSION} in {install}')
    (updater._untar if kind == 'linux' else updater._unzip)(archive, install)
    root = next(install.iterdir())
    info_path = updater.app_folder(kind, root) / updater.BUILD_INFO
    info = json.loads(info_path.read_text(encoding='utf-8'))
    new_version = info['version']
    info_path.write_text(json.dumps(dict(info, version=OLD_VERSION)), encoding='utf-8')

    carried = []
    if kind != 'macos':
        marker = root / 'roms' / 'my game.gb'
        marker.write_bytes(b'not really a game')
        carried.append(Path('roms') / 'my game.gb')
    if kind == 'linux':
        subprocess.run([str(root / 'setup.sh')], check=True)
        (root / '.venv' / 'marker').write_text('kept')
        carried.append(Path('.venv') / 'marker')

    payload = archive.read_bytes()
    feed = work / 'feed.json'
    feed.write_text(json.dumps({
        'tag_name': f'v{new_version}', 'draft': False, 'prerelease': False,
        'html_url': 'https://github.com/bonquifo/retro-pocket/releases',
        'assets': [{'name': archive.name, 'size': len(payload), 'browser_download_url': archive.as_uri(),
                    'digest': 'sha256:' + hashlib.sha256(payload).hexdigest()}],
    }), encoding='utf-8')
    del payload
    env = dict(os.environ, **{updater.FEED_ENV: str(feed)})

    print(f'{kind}: updating {OLD_VERSION} -> {new_version} with the old copy\'s --update')
    result = subprocess.run(command(kind, root, '--update', '--data-dir', str(data)), env=env,
                            capture_output=True, text=True, timeout=600)
    print(result.stdout, result.stderr, sep='\n')
    if result.returncode:
        raise SystemExit(f'--update failed with exit status {result.returncode}')

    log = data / 'logs' / 'update.log'
    build = updater.Installation(OLD_VERSION, kind, archive.name, updater.DEFAULT_REPOSITORY, root)
    leftovers = (updater.staging_folder(build), updater.old_folder(build))
    deadline = time.monotonic() + args.timeout
    while True:
        text = log.read_text(encoding='utf-8', errors='replace') if log.is_file() else ''
        current = updater.installation(updater.app_folder(kind, root))
        if 'FAILED' in text:
            raise SystemExit(f'The helper failed:\n{text}')
        if current and current.version == new_version and 'updated' in text \
                and not any(path.exists() for path in leftovers):
            break
        if time.monotonic() > deadline:
            raise SystemExit(f'The update did not finish in {args.timeout} s. Log:\n{text}')
        time.sleep(1)
    print(f'helper log:\n{text}')

    for item in carried:
        if not (root / item).is_file():
            raise SystemExit(f'{item} was not carried over to the new version')
    version = subprocess.run(command(kind, root, '--version'), capture_output=True, text=True, timeout=120)
    if new_version not in version.stdout:
        raise SystemExit(f'the updated copy reports {version.stdout!r} {version.stderr!r}')
    signed = ''
    if args.signed:  # The update unpacks and moves the app itself: nothing in it may change
        for argv, expect in ((['/usr/bin/codesign', '--verify', '--deep', '--strict', '--verbose=2', str(root)],
                              'satisfies its Designated Requirement'),
                             (['/usr/bin/xcrun', 'stapler', 'validate', str(root)], 'worked')):
            result = subprocess.run(argv, capture_output=True, text=True)
            if result.returncode or expect not in result.stdout + result.stderr:
                raise SystemExit(f'the updated copy fails {Path(argv[0]).name} {argv[1]}:\n'
                                 f'{(result.stdout + result.stderr).strip()[-2000:]}')
        signed = '; signature and notarization ticket intact'
    print(f'{kind}: updated to {new_version}; {", ".join(map(str, carried)) or "nothing"} carried over; '
          f'{version.stdout.strip()}{signed}')
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
