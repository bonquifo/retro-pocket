#!/usr/bin/env python3
"""Check a finished Retro Pocket build from the inside, with the build's own Python.

    <build's python> tools/verify_build.py --app-dir DIR --arch x86_64|arm64 [options]

DIR holds the build's app.py. The checks use the build's code, Python,
pygame-ce and emulators, as playing a game would:

  - Python runs as the expected CPU architecture, and imports the build's code
  - the catalogue loads; app.py starts and prints its help
  - pygame-ce opens a window (SDL's dummy driver, or a real one with --window)
  - the mGBA core loads and emulates a test cartridge, and saves
  - each system's emulator is found and built for this CPU
  - --network: box art downloads over HTTPS and matches its pinned digest
  - --run-emulators: the emulators start (from per-game copies, as Play makes
    them) and report their version or usage; on macOS, Apple's code
    signatures are checked too
  - --launcher PATH: the build's own launcher starts app.py (--help)

Exits 1 if any check fails. CI runs it on every build (.github/workflows).
"""
import argparse
import importlib
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import traceback

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
EXPECTED_PYGAME = '2.5.7'


def cpu():
    machine = platform.machine().lower()
    return {'amd64': 'x86_64', 'aarch64': 'arm64'}.get(machine, machine)


class Checks:
    def __init__(self):
        self.failed = []

    def run(self, name, check):
        try:
            detail = check()
        except Exception as exc:  # Every check reports; none stops the others.
            self.failed.append(name)
            print(f'FAIL {name}: {exc}')
            traceback.print_exc(limit=3)
            return None
        print(f'ok   {name}' + (f': {detail}' if detail else ''))
        return detail


def run_program(argv, expect, cwd=None, any_status=False, timeout=90):
    result = subprocess.run([str(a) for a in argv], cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, errors='replace', timeout=timeout)
    output = (result.stdout + result.stderr).strip()
    if (result.returncode and not any_status) or expect.lower() not in output.lower() or not output:
        raise RuntimeError(f'exit {result.returncode}; output: {output[-600:]!r}')
    return output.splitlines()[0][:100] if output else ''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--app-dir', type=Path, required=True, help="the build's folder holding app.py")
    parser.add_argument('--arch', choices=('x86_64', 'arm64'), required=True)
    parser.add_argument('--optional', action='append', default=[], choices=('ds', 'n64', '3ds'),
                        help='a system whose emulator may be missing (Linux: Azahar is not packaged)')
    parser.add_argument('--network', action='store_true', help='also download one box art image')
    parser.add_argument('--run-emulators', action='store_true', help='also start each emulator')
    parser.add_argument('--window', action='store_true', help="open a real window, not SDL's dummy one")
    parser.add_argument('--launcher', type=Path, help="the build's launcher, run with --help")
    args = parser.parse_args(argv)

    app_dir = args.app_dir.resolve()
    if not args.window:
        os.environ['SDL_VIDEODRIVER'] = 'dummy'
    os.environ['SDL_AUDIODRIVER'] = 'dummy'
    sys.path[:0] = [str(app_dir), str(TOOLS), str(REPO / 'tests')]
    scratch = Path(tempfile.mkdtemp(prefix='retro-pocket-check-'))
    checks = Checks()
    print(f'Checking {app_dir} with Python {platform.python_version()} at {sys.executable}')

    def python():
        if cpu() != args.arch:
            raise RuntimeError(f'Python runs as {cpu()}, expected {args.arch}')
        return f'{cpu()}, Python {platform.python_version()}'
    checks.run('python', python)

    def code():
        import compat
        if compat.APP_DIR != app_dir:
            raise RuntimeError(f'imported Retro Pocket from {compat.APP_DIR}, not the build')
        return 'Windows' if compat.WINDOWS else 'macOS' if compat.MACOS else 'Linux'
    checks.run('build code', code)

    def catalogue():
        from library import Library
        library = Library(root=scratch / 'data', rom_dir=scratch / 'roms')
        playable = sum(1 for game in library.games if 'unavailable' not in game)
        if playable < 50:
            raise RuntimeError(f'only {playable} playable games')
        return f'{len(library.games)} games, {playable} playable'
    checks.run('catalogue', catalogue)

    checks.run('app.py --help', lambda: run_program([sys.executable, app_dir / 'app.py', '--help'], 'usage'))
    if args.launcher:
        checks.run('launcher', lambda: run_program([args.launcher, '--help'], 'usage'))

    def window():
        import pygame as pg
        if pg.version.ver != EXPECTED_PYGAME:
            raise RuntimeError(f'pygame-ce {pg.version.ver}, expected {EXPECTED_PYGAME}')
        pg.display.init()
        pg.font.init()
        try:
            from viewport import open_window, render_text
            window = open_window('Retro Pocket check', (320, 240))
            surface = window.get_surface()
            surface.fill('#121820')
            surface.blit(render_text(pg.font.Font(None, 23), 'Retro Pocket', '#f2f6fc'), (10, 10))
            window.flip()
            size, driver = surface.get_size(), pg.display.get_driver()
            window.destroy()
        finally:
            pg.quit()
        return f'pygame-ce {pg.version.ver}, SDL {".".join(map(str, pg.get_sdl_version()))}, {driver} {size}'
    checks.run('pygame window', window)

    def mgba():
        from core import Core, locate_core
        from install_emulators import architectures
        from test_core import gba_rom
        path = locate_core()
        if args.arch not in architectures(path):
            raise RuntimeError(f'{path} is built for {sorted(architectures(path))}')
        core = Core(gba_rom(), path, scratch / 'saves')
        try:
            for _ in range(4):
                frame = core.run(set())
            if frame is None or frame[2][:3] != b'\xff\x00\x00':
                raise RuntimeError('the test cartridge did not draw its red pixel')
            core.save()
        finally:
            core.close()
        return f'{path}: {frame[0]}x{frame[1]} frames'
    checks.run('mGBA core', mgba)

    programs = {}
    for system, module in (('ds', 'ds'), ('n64', 'n64'), ('3ds', 'azahar_backend')):
        def find(system=system, module=module):
            from install_emulators import architectures
            backend = importlib.import_module(module)
            try:
                program = backend._find_executable()
            except FileNotFoundError:
                if system in args.optional:
                    return 'not installed (optional here)'
                raise
            built_for = architectures(program)
            if built_for and args.arch not in built_for:
                raise RuntimeError(f'{program} is built for {sorted(built_for)}')
            programs[system] = program
            return f'{program} ({", ".join(sorted(built_for)) or "script"})'
        checks.run(f'{system.upper()} emulator', find)

    if args.network:
        def box_art():
            import covers
            art = covers.BoxArt(scratch / 'covers')
            game_id = next(iter(art.index))
            art._download(game_id)
            path = art.path({'id': game_id})
            if path is None:
                raise RuntimeError('the download did not match covers-index.json')
            return f'{game_id}: {path.stat().st_size} bytes over HTTPS, digest matches'
        checks.run('box art download', box_art)

    if args.run_emulators:
        run_emulators(checks, programs, scratch, args.arch)

    print('\nRESULT:', f'{len(checks.failed)} failed: {", ".join(checks.failed)}' if checks.failed
          else 'all checks passed')
    return 1 if checks.failed else 0


def run_emulators(checks, programs, scratch, arch):
    import compat

    if compat.MACOS:
        if 'ds' in programs:  # A per-game copy of melonDS.app, as Play makes it
            def melonds():
                import melonds_backend
                files, program = melonds_backend._program_files(programs['ds'])
                compat.private_install(files, scratch / 'melonds')
                return run_program([scratch / 'melonds' / program, '--help'], 'usage')
            checks.run('melonDS starts (per-game copy)', melonds)
        if 'n64' in programs:
            # It prints only its version, such as "v148".
            checks.run('ares starts', lambda: run_program(
                [programs['n64'], '--settings-file', scratch / 'ares-settings.bml', '--version'], ''))
        if '3ds' in programs:
            def azahar():
                (scratch / 'azahar' / 'user').mkdir(parents=True)  # Portable mode, as for a game
                # -v: Azahar's command-line check takes short options only (--version is the Qt window's).
                return run_program([programs['3ds'], '-v'], 'azahar', cwd=scratch / 'azahar')
            checks.run('Azahar starts', azahar)

        def codesign(*arguments):
            result = subprocess.run(['/usr/bin/codesign', '--verify', *map(str, arguments)],
                                    capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(f'{arguments[-1]}: {(result.stdout + result.stderr).strip()[-800:]}')

        def signatures():
            checked = []
            for program in programs.values():
                target = compat.bundle_of(program) or program
                codesign('--deep', '--strict', target)
                checked.append(target.name)
            if arch == 'arm64':  # Apple Silicon runs only signed code; Intel code may be unsigned
                from core import locate_core
                for target in (Path(sys.executable), Path(locate_core())):
                    codesign(target)
                    checked.append(target.name)
            return ', '.join(checked)
        checks.run('code signatures', signatures)
    elif compat.WINDOWS:
        if 'n64' in programs:
            checks.run('Mupen64Plus starts', lambda: run_program([programs['n64'], '--help'], 'usage',
                                                                 any_status=True))
        if '3ds' in programs:
            def azahar():  # A per-game copy, as Play makes it (portable mode)
                import azahar_backend
                profile = scratch / 'azahar'
                (profile / 'user').mkdir(parents=True)
                compat.private_install(azahar_backend._program_files(programs['3ds']), profile)
                return run_program([profile / programs['3ds'].name, '-v'], 'azahar')
            checks.run('Azahar starts (per-game copy)', azahar)


if __name__ == '__main__':
    raise SystemExit(main())
