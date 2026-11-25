"""Worker process: isolate native emulator crashes from the catalogue."""
import argparse
from pathlib import Path
import signal
import shutil
import sys
import tempfile
import traceback

import compat
from library import Library

ROOT = Path(__file__).resolve().parent
SNAPSHOT_PREFIX = 'rp-launch-'


def cleanup_stale_snapshots(saves):
    """Call under the title lock; skip any snapshot whose owner still runs.

    The owner is the worker's process group (POSIX) or process (Windows).
    """
    for candidate in saves.glob(SNAPSHOT_PREFIX + '*'):
        marker = candidate / '.owner'
        if compat.is_link(candidate) or not candidate.is_dir() or marker.is_symlink():
            continue
        try:
            owner = int(marker.read_text(encoding='ascii'))
            if owner <= 1 or compat.owner_alive(owner):
                continue
        except (OSError, ValueError):
            continue
        try:
            shutil.rmtree(candidate)
        except OSError as exc:
            print(f'Could not clean abandoned launch files: {exc}', file=sys.stderr)


def run_game(library, game_id, core=None):
    game = next((g for g in library.games if g['id'] == game_id), None)
    if game is None:
        raise ValueError('Game is not in the catalogue')
    platform = game['platform']
    if not library.path(game).is_file():
        library.scan(only=game_id)  # Cached digests make this a stat call.
        if not library.source(game).is_file():
            # The ROM-folder file was removed, or no longer matches after a change.
            # Shown on screen, so it says what went wrong without saying where games are kept.
            raise ValueError("This game's file is missing, or has changed or been damaged, so its "
                             'size or digest no longer matches the catalogue')
    saves = library.root / 'saves' / game_id
    saves.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (saves / '.playing.lock').open('ab') as lock:
        try:
            compat.lock_exclusive(lock)
        except BlockingIOError:
            raise ValueError('This game is already running in another Retro Pocket window') from None
        # Verification streams the image through a 1 MiB buffer, and the
        # emulator gets a hard link to the checked file (a streamed copy only
        # across filesystems), so no launch path holds or copies the image.
        if platform in {'NDS', 'N64', 'Mini'}:
            if platform == 'NDS':
                from ds import launch
            elif platform == 'N64':
                from n64 import launch
            else:
                from mini import launch
            # These emulators name save files after the ROM: keep a stable name.
            placed = library.place(game, saves.resolve() / library.staged_name(game))
            process = launch(placed, game_id, saves)
        else:
            # Per-launch snapshot link: the emulator keeps the verified file
            # even if the original is renamed or replaced while it runs.
            cleanup_stale_snapshots(saves)
            # A file still open after the emulator exits (Windows can't delete those)
            # is left for the next launch's cleanup.
            with tempfile.TemporaryDirectory(prefix=SNAPSHOT_PREFIX, dir=saves,
                                             ignore_cleanup_errors=True) as temporary:
                directory = Path(temporary)
                (directory / '.owner').write_text(str(compat.launch_owner()), encoding='ascii')
                stage = library.place(game, directory / library.staged_name(game))
                if platform in {'GB', 'GBC', 'GBA'}:
                    from core import locate_core  # Avoids loading pygame in the worker
                    process = compat.popen([sys.executable, '-u', ROOT / 'handheld_player.py',
                                            stage, locate_core(core), saves, game['title'],
                                            '--platform', platform])
                elif platform in {'GCN', 'Wii'}:
                    from dolphin_backend import launch
                    process = launch(stage, game_id, saves)
                elif platform == '3DS':
                    from azahar_backend import launch
                    process = launch(stage, game_id, saves)
                else:
                    raise ValueError(f'No launch integration for {platform}')
                return wait(process)
        return wait(process)


def wait(process):
    code = process.wait()
    if code < 0:
        print(f'RETRO_POCKET_ERROR: Emulator stopped on {signal.Signals(-code).name}', file=sys.stderr)
        return 128 - code
    if code > 0 and (reason := compat.exit_reason(code)):
        # A Windows exception code: name it, and exit with a status every system can carry.
        print(f'RETRO_POCKET_ERROR: Emulator stopped on {reason}', file=sys.stderr)
        return 1
    if code > 0:
        print(f'Emulator process returned status {code}', file=sys.stderr)
    return code if code <= 255 else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--core')
    parser.add_argument('--rom-dir', type=Path)
    parser.add_argument('game')
    args = parser.parse_args()
    try:
        return run_game(Library(root=args.data_dir, rom_dir=args.rom_dir), args.game, args.core)
    except Exception as exc:
        traceback.print_exc()
        print(f'RETRO_POCKET_ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
