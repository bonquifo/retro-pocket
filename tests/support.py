"""Cross-platform test helpers: stand-in emulator programs, symlinks and PATH decoys."""
import io
import os
from pathlib import Path
import shutil
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import compat  # noqa: E402

WINDOWS = compat.WINDOWS
MACOS = compat.MACOS
LINUX = sys.platform.startswith('linux')


def _launcher():
    """pip's console launcher stub (distlib t64.exe): the way pip builds pip.exe."""
    import pip
    stub = Path(pip.__file__).parent / '_vendor' / 'distlib' / 't64.exe'
    if not stub.is_file():
        raise unittest.SkipTest('pip\'s distlib launcher (t64.exe) is needed for stand-in programs')
    return stub.read_bytes()


def program(path, source: str) -> Path:
    """A real executable stand-in that runs Python ``source``; returns its path.

    POSIX: a ``#!python`` script. Windows: an .exe (``.exe`` is appended to
    the name), a launcher stub followed by a zip with __main__.py, which is
    what CreateProcess needs. Arguments, exit status and output pass through.
    """
    path = Path(path)
    if not WINDOWS:
        path.write_text(f'#!{sys.executable}\n{source}', encoding='utf-8')
        path.chmod(0o700)
        return path
    if path.suffix.lower() != '.exe':
        path = path.with_name(path.name + '.exe')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('__main__.py', source)
    interpreter = f'"{sys.executable}"' if ' ' in sys.executable else sys.executable
    path.write_bytes(_launcher() + f'#!{interpreter}\n'.encode() + archive.getvalue())
    return path


def symlink(test: unittest.TestCase, link: Path, target: Path, directory=False):
    """Create a symlink, or skip the test where the OS doesn't allow it.

    Windows only lets administrators, or everyone in Developer Mode, create symlinks.
    """
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        if WINDOWS:
            test.skipTest(f'symlinks need Developer Mode or administrator rights on Windows ({exc})')
        raise


def can_symlink(directory: Path) -> bool:
    probe = directory / '.symlink-probe'
    try:
        probe.symlink_to(directory / 'missing')
    except OSError:
        return False
    probe.unlink()
    return True


def directory_link(link: Path, target: Path) -> None:
    """A link to a directory any user can make: a junction on Windows, a symlink elsewhere."""
    if WINDOWS:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def remove_link(link: Path) -> None:
    """Remove a symlink or junction, never what it points to."""
    if WINDOWS and not link.is_symlink():
        os.rmdir(link)  # A junction is removed like an empty directory.
    else:
        link.unlink()


def minimal_env(**values) -> dict:
    """A cleared environment for autodetection tests; Windows processes still need SystemRoot."""
    env = {key: str(value) for key, value in values.items()}
    if WINDOWS:
        env.setdefault('SystemRoot', os.environ.get('SystemRoot', r'C:\Windows'))
    return env


def decoy(path: Path, real: Path) -> Path:
    """An emulator of the same name somewhere on PATH, which autodetection must ignore."""
    if WINDOWS:
        path = path.with_name(path.name + '.exe')
        shutil.copyfile(real, path)
    else:
        path.symlink_to(real)
    return path


def no_executable(path: Path) -> Path:
    """A file that exists but is not a program on this platform."""
    path.touch()
    return path


def env_path(*directories) -> str:
    return os.pathsep.join(str(d) for d in directories)
