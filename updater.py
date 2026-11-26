"""Keep an installed Retro Pocket up to date from its GitHub releases.

The Windows, macOS and Linux builds carry build-info.json (written by
tools/build_*.py): their version, their system, and which release file is
theirs. At most once a day the library asks GitHub for the latest release;
if it is newer, the library offers to update. A source checkout has no
build-info.json and updates with git instead.

Installing an update never touches saves, settings or ROMs:

  1. download: this build's file from the release, checked against the
     size and SHA-256 that GitHub publishes for it;
  2. stage: unpacked next to the installation (same drive, so the swap is a
     rename) and checked to be the expected version for the same system;
  3. apply: once the library has quit, a small helper (PowerShell on
     Windows, sh elsewhere) puts the old version aside (as a hidden
     ".<name>.old" folder), moves the new one into place, carries the ROM
     folder (and Linux's Python environment) over, removes the old version
     and starts the new one. If a step fails, the old version is put back;
     the next start says what happened.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile

import compat

BUILD_INFO = 'build-info.json'
DEFAULT_REPOSITORY = 'bonquifo/retro-pocket'
# A file holding a release in the format of GitHub's API, used instead of
# GitHub (the update tests use it with file: download URLs).
FEED_ENV = 'RETRO_POCKET_UPDATE_FEED'
DISABLE_ENV = 'RETRO_POCKET_NO_UPDATE_CHECK'
CHECK_EVERY = 24 * 3600
KINDS = {'windows', 'macos', 'linux'}
_VERSION = re.compile(r'v?(\d+)\.(\d+)\.(\d+)(?:-(\d+)-g[0-9a-f]+)?')
_REPOSITORY = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9._-]+')
_ASSET = re.compile(r'[A-Za-z0-9._-]+')


def parse_version(text):
    """(major, minor, patch, commits since that release) for "1.2.3", "v1.2.3" or "1.2.3-4-gabc1234"."""
    match = _VERSION.fullmatch(str(text).strip()) if text is not None else None
    if match is None:
        return None
    major, minor, patch, ahead = match.groups()
    return int(major), int(minor), int(patch), int(ahead or 0)


@dataclass(frozen=True)
class Installation:
    version: str
    kind: str              # windows, macos or linux
    asset: str             # This build's file name in a release
    repository: str        # owner/name on GitHub
    root: Path             # What an update replaces: the folder, or the macOS .app
    preserve: tuple = ()   # Items in root carried over to the new version


def installation(app_dir=None):
    """This build, or None when running from source (or the build info is unusable)."""
    app_dir = Path(app_dir or compat.APP_DIR)
    try:
        info = json.loads((app_dir / BUILD_INFO).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(info, dict):
        return None
    kind, version, asset = info.get('kind'), info.get('version'), info.get('asset')
    if kind not in KINDS or parse_version(version) is None or not isinstance(asset, str) \
            or not _ASSET.fullmatch(asset):
        return None
    repository = info.get('repository')
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        repository = DEFAULT_REPOSITORY
    if kind == 'macos':
        root = app_dir.parents[2]  # X.app/Contents/Resources/app
        if root.suffix != '.app' or app_dir.parent.name != 'Resources':
            return None
        preserve = ()  # The ROM folder is ~/Retro Pocket/roms, outside the app
    else:
        root = app_dir
        preserve = ('roms', '.venv') if kind == 'linux' else ('roms',)
    return Installation(version, kind, asset, repository, root, preserve)


@dataclass(frozen=True)
class Release:
    version: str      # "1.2.3"
    tag: str          # "v1.2.3"
    asset: str
    url: str
    size: int
    sha256: str
    page: str         # The release's web page


def _check_url(url):
    if os.environ.get(FEED_ENV):
        return  # A test feed may use file: URLs
    if not url.startswith('https://'):
        raise ValueError(f'Refusing to download over an insecure connection: {url}')


def _open(url, timeout):
    _check_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'retro-pocket-updater',
                                                   'Accept': 'application/vnd.github+json'})
    return urllib.request.urlopen(request, timeout=timeout, context=compat.https_context())


def _latest_json(build):
    feed = os.environ.get(FEED_ENV)
    if feed:
        return Path(feed).read_text(encoding='utf-8')
    with _open(f'https://api.github.com/repos/{build.repository}/releases/latest', 20) as response:
        return response.read(4 * 1024 * 1024).decode('utf-8')


def latest(build):
    """The newest published release if it is newer than ``build`` and has a file for it, else None."""
    data = json.loads(_latest_json(build))
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name')
    version = parse_version(tag)
    testing = bool(os.environ.get(FEED_ENV))  # The update tests offer development builds too
    if version is None or (version[3] and not testing) or version <= parse_version(build.version):
        return None  # Not a plain release (vX.Y.Z), or not newer
    asset = next((a for a in data.get('assets') or () if isinstance(a, dict) and a.get('name') == build.asset), None)
    if asset is None:
        return None  # This release has no build for this system
    digest, size, url = str(asset.get('digest') or ''), asset.get('size'), asset.get('browser_download_url')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError(f'Release {tag} publishes no SHA-256 for {build.asset}')
    if type(size) is not int or not 0 < size <= 2 * 1024 ** 3 or not isinstance(url, str):
        raise ValueError(f'Release {tag} lists {build.asset} without a usable size or address')
    if not testing and not url.startswith(f'https://github.com/{build.repository}/releases/download/'):
        raise ValueError(f'Release {tag} points outside {build.repository}: {url}')
    return Release(tag[1:] if tag.startswith('v') else tag, tag, build.asset, url, size, digest[7:],
                   str(data.get('html_url') or f'https://github.com/{build.repository}/releases/latest'))


def download(release, folder: Path, progress=None) -> Path:
    """Fetch the release file into ``folder``, checked against its published size and SHA-256."""
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / release.asset
    partial = target.with_name(target.name + '.part')
    digest, received = hashlib.sha256(), 0
    try:
        with _open(release.url, 60) as response, open(partial, 'wb') as output:
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if received > release.size:
                    raise ValueError('The download is larger than the release says')
                digest.update(chunk)
                output.write(chunk)
                if progress:
                    progress(received, release.size)
        if received != release.size or digest.hexdigest() != release.sha256:
            raise ValueError("The download doesn't match the size and SHA-256 published with the release")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


# ----- Unpacking -------------------------------------------------------------

def _safe(name):
    path = PurePosixPath(name.replace('\\', '/'))
    if not name or path.is_absolute() or '..' in path.parts or ':' in name:
        raise ValueError(f'Unsafe name in the update: {name}')
    return path


def _inside(path, link):
    return '..' not in PurePosixPath(posixpath.normpath(str(path.parent / link))).parts and not link.startswith('/')


def _unzip(archive: Path, target: Path):
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            path = _safe(info.filename)
            destination = target.joinpath(*path.parts)
            unix = info.external_attr >> 16 if info.create_system == 3 else 0
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if stat.S_ISLNK(unix):
                link = bundle.read(info).decode('utf-8')
                if not _inside(path, link):
                    raise ValueError(f'Link leaves the update: {path} -> {link}')
                os.symlink(link, destination)
                continue
            with bundle.open(info) as source, open(destination, 'wb') as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            if os.name != 'nt' and stat.S_IMODE(unix):
                destination.chmod(stat.S_IMODE(unix))


def _untar(archive: Path, target: Path):
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        for member in members:
            path = _safe(member.name)
            if not (member.isfile() or member.isdir()) and not (member.issym() and _inside(path, member.linkname)):
                raise ValueError(f'Unexpected entry in the update: {member.name}')
        if hasattr(tarfile, 'data_filter'):
            bundle.extractall(target, members, filter='data')
        else:  # Python before 3.11.4: the members were checked above
            bundle.extractall(target, members)


def app_folder(kind, root: Path) -> Path:
    """Where a build of ``kind`` keeps app.py and build-info.json."""
    return root / 'Contents' / 'Resources' / 'app' if kind == 'macos' else root


def staging_folder(build) -> Path:
    return build.root.parent / f'.{build.root.name}.update'


def old_folder(build) -> Path:
    """Where the helper puts the installed version aside during the swap (hidden, and only ever ours)."""
    return build.root.parent / f'.{build.root.name}.old'


def stage(build, release, archive: Path) -> Path:
    """Unpack the update beside the installation and check it; returns the new version's root."""
    staging = staging_folder(build)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        (_untar if archive.name.endswith('.tar.gz') else _unzip)(archive, staging)
        roots = [path for path in staging.iterdir()]
        if len(roots) != 1 or not roots[0].is_dir():
            raise ValueError('The update has an unexpected layout')
        new_root = roots[0]
        info = json.loads((app_folder(build.kind, new_root) / BUILD_INFO).read_text(encoding='utf-8'))
        if (info.get('version'), info.get('kind'), info.get('asset')) != (release.version, build.kind, build.asset):
            raise ValueError(f"The update isn't Retro Pocket {release.version} for this system")
        if not (app_folder(build.kind, new_root) / 'app.py').is_file():
            raise ValueError('The update has no app.py')
    except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError):
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return new_root


def can_replace(build) -> bool:
    """Whether this user may replace the installation (not in a read-only or system folder)."""
    probe = build.root.parent / f'.{build.root.name}.write-test-{os.getpid()}'
    try:
        probe.mkdir()
        probe.rmdir()
    except OSError:
        return False
    return os.access(build.root, os.W_OK)


def cleanup(build):
    """Remove what an earlier update left behind, if it isn't in use."""
    for leftover in (old_folder(build), staging_folder(build)):
        if leftover.exists() and not compat.is_link(leftover):
            shutil.rmtree(leftover, ignore_errors=True)


# ----- Applying --------------------------------------------------------------

_SHELL = r'''#!/bin/sh
# Retro Pocket update helper: swaps in the staged version once the library has quit.
# Arguments: PID ROOT NEW LOG KIND RELAUNCH [ITEM TO CARRY OVER ...]
pid=$1 root=$2 new=$3 log=$4 kind=$5 relaunch=$6
shift 6
exec >>"$log" 2>&1
echo "$(date): updating $root"
waited=0
while kill -0 "$pid" 2>/dev/null; do
  waited=$((waited + 1))
  if [ "$waited" -gt 1200 ]; then echo "FAILED: Retro Pocket did not quit"; exit 1; fi
  sleep 0.1
done
old="$(dirname "$root")/.$(basename "$root").old"
rm -rf "$old"
if ! mv "$root" "$old"; then echo "FAILED: could not move the installed version aside"; exit 1; fi
if ! mv "$new" "$root"; then
  mv "$old" "$root"
  echo "FAILED: could not put the new version in place; the installed version was kept"
  exit 1
fi
for item in "$@"; do
  if [ -e "$old/$item" ] || [ -L "$old/$item" ]; then rm -rf "$root/$item"; mv "$old/$item" "$root/$item"; fi
done
rmdir "$(dirname "$new")" 2>/dev/null
if [ "$kind" = macos ]; then /usr/bin/xattr -dr com.apple.quarantine "$root" 2>/dev/null; fi
if [ "$kind" = linux ]; then "$root/setup.sh" || echo "setup.sh failed: run it again by hand"; fi
rm -rf "$old"
echo "$(date): updated"
if [ "$relaunch" = 1 ]; then
  if [ "$kind" = macos ]; then exec /usr/bin/open "$root"; else exec "$root/RetroPocket.sh"; fi
fi
'''

_POWERSHELL = r'''# Retro Pocket update helper: swaps in the staged version once the library has quit.
param([int]$ProcessId, [string]$Root, [string]$New, [string]$Log, [string[]]$Preserve = @(), [switch]$Relaunch)
$ErrorActionPreference = 'Stop'
function Note([string]$Text) { Add-Content -LiteralPath $Log -Value ('{0:u} {1}' -f (Get-Date), $Text) }
function Retry([scriptblock]$Step) {
  # A file can stay locked for a moment after its program quits (antivirus scans, too).
  for ($i = 1; $i -le 60; $i++) { try { & $Step; return $true } catch { Start-Sleep -Milliseconds 500 } }
  return $false
}
try {
  Note "updating $Root"
  $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
  if ($process -and -not $process.WaitForExit(120000)) { Note 'FAILED: Retro Pocket did not quit'; exit 1 }
  $old = Join-Path (Split-Path $Root -Parent) ('.' + (Split-Path $Root -Leaf) + '.old')
  if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Recurse -Force }
  if (-not (Retry { Rename-Item -LiteralPath $Root -NewName (Split-Path $old -Leaf) })) {
    Note 'FAILED: the installed version is still in use'; exit 1
  }
  if (-not (Retry { Move-Item -LiteralPath $New -Destination $Root })) {
    Rename-Item -LiteralPath $old -NewName (Split-Path $Root -Leaf)
    Note 'FAILED: could not put the new version in place; the installed version was kept'; exit 1
  }
  foreach ($item in $Preserve) {
    $from = Join-Path $old $item
    if (Test-Path -LiteralPath $from) {
      $to = Join-Path $Root $item
      if (Test-Path -LiteralPath $to) { Remove-Item -LiteralPath $to -Recurse -Force }
      Move-Item -LiteralPath $from -Destination $to
    }
  }
  Remove-Item -LiteralPath (Split-Path $New -Parent) -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $old -Recurse -Force -ErrorAction SilentlyContinue
  Note 'updated'
  if ($Relaunch) {
    Start-Process -FilePath (Join-Path $Root 'python\pythonw.exe') -WorkingDirectory $Root `
      -ArgumentList ('"' + (Join-Path $Root 'app.py') + '"')
  }
} catch { Note "FAILED: $_"; exit 1 }
'''


def apply(build, new_root: Path, log: Path, relaunch=True, pid=None) -> subprocess.Popen:
    """Start the helper that installs ``new_root`` once process ``pid`` (this one) has exited."""
    pid = pid or os.getpid()
    log.parent.mkdir(parents=True, exist_ok=True)
    helpers = Path(tempfile.mkdtemp(prefix='retro-pocket-update-'))
    if compat.WINDOWS:
        script = helpers / 'update.ps1'
        script.write_text(_POWERSHELL, encoding='utf-8-sig')
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
        argv = [str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                '-ProcessId', str(pid), '-Root', str(build.root), '-New', str(new_root), '-Log', str(log)]
        if build.preserve:
            argv += ['-Preserve', ','.join(build.preserve)]
        if relaunch:
            argv.append('-Relaunch')
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:  # Outlive this process even if it runs in a job that ends with it.
            return subprocess.Popen(argv, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return subprocess.Popen(argv, creationflags=flags, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    script = helpers / 'update.sh'
    script.write_text(_SHELL, encoding='utf-8')
    argv = ['/bin/sh', str(script), str(pid), str(build.root), str(new_root), str(log), build.kind,
            '1' if relaunch else '0', *build.preserve]
    return subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ----- The library's view ------------------------------------------------------

class Updates:
    """Update state for the library window: checked in the background, at most once a day.

    ``state`` is idle, available, downloading, ready or failed; ``release``
    is the newer release, ``message`` says what happened last.
    """

    def __init__(self, data_dir, build=None, enabled=True, clock=time.time):
        self.build = build
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.enabled = bool(enabled and build is not None and self.data_dir is not None
                            and not os.environ.get(DISABLE_ENV))
        self.clock = clock
        self.state, self.release, self.message, self.progress = 'idle', None, '', 0.0
        self.new_root = None
        self._lock = threading.Lock()

    @property
    def cache_file(self):
        return self.data_dir / 'update-check.json'

    @property
    def pending_file(self):
        return self.data_dir / 'update-pending.json'

    @property
    def log_file(self):
        return self.data_dir / 'logs' / 'update.log'

    def start(self):
        """Report how an update from the previous run went, then check in the background."""
        if self.build is None or self.data_dir is None:
            return
        self.message = self._previous_update()
        cleanup(self.build)
        if self.enabled:
            threading.Thread(target=self._check, name='update-check', daemon=True).start()

    def _previous_update(self):
        try:
            pending = json.loads(self.pending_file.read_text(encoding='utf-8'))
            self.pending_file.unlink()
        except (OSError, ValueError):
            return ''
        target = pending.get('version') if isinstance(pending, dict) else None
        if target == self.build.version:
            return f'Updated to Retro Pocket {target}.'
        return f"The update to Retro Pocket {target} couldn't be installed. Log: {self.log_file}"

    def _check(self):
        now = self.clock()
        try:
            cached = json.loads(self.cache_file.read_text(encoding='utf-8'))
            if (cached.get('installed') == self.build.version and not os.environ.get(FEED_ENV)
                    and 0 <= now - cached.get('checked', 0) < CHECK_EVERY):
                release = Release(**cached['release']) if cached.get('release') else None
            else:
                raise ValueError('stale')
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            try:
                release = latest(self.build)
            except Exception as exc:  # Offline, or GitHub unreachable: try again next start.
                print(f'Update check failed: {exc}', file=sys.stderr)
                return
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                self.cache_file.write_text(json.dumps({
                    'checked': now, 'installed': self.build.version,
                    'release': asdict(release) if release else None}), encoding='utf-8')
            except OSError:
                pass
        with self._lock:
            if release is not None and self.state == 'idle':
                self.release, self.state = release, 'available'

    def can_install(self):
        return self.release is not None and can_replace(self.build)

    def install(self):
        """Download and stage the update in the background."""
        with self._lock:
            if self.state != 'available':
                return
            self.state, self.progress = 'downloading', 0.0
        threading.Thread(target=self._install, name='update-download', daemon=True).start()

    def _install(self):
        def progress(done, total):
            self.progress = done / total if total else 0.0
        try:
            folder = self.data_dir / 'updates'
            archive = download(self.release, folder, progress)
            try:
                self.new_root = stage(self.build, self.release, archive)
            finally:
                archive.unlink(missing_ok=True)
            self.state = 'ready'
        except Exception as exc:
            print(f'Update failed: {exc}', file=sys.stderr)
            self.message, self.state = f'Update failed: {exc}', 'failed'

    def finish(self, relaunch=True):
        """Hand over to the helper; the caller then quits."""
        self.pending_file.write_text(json.dumps({'version': self.release.version}), encoding='utf-8')
        return apply(self.build, self.new_root, self.log_file, relaunch=relaunch)
