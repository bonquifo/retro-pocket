"""Run smoke_real.py with the locally extracted Xvfb test dependencies."""
import os
from pathlib import Path
import subprocess
import sys


def main(d, libraries, core):
    env = dict(os.environ, LD_LIBRARY_PATH=f'{d}/root/usr/lib/x86_64-linux-gnu:{libraries}',
               PATH=f'{d}/root/usr/bin:{os.environ["PATH"]}', SDL_VIDEODRIVER='x11', SDL_AUDIODRIVER='dummy')
    command = ['bwrap', '--unshare-pid', '--die-with-parent', '--ro-bind', '/', '/',
               '--dev-bind', '/dev', '/dev', '--bind', '/tmp', '/tmp', '--ro-bind', '/usr/bin', '/mnt',
               '--ro-bind', f'{d}/shim', '/usr/bin', f'{d}/root/usr/bin/Xvfb', '-displayfd', '1',
               '-screen', '0', '1024x768x24', '-nolisten', 'tcp', '-fp', 'built-ins']
    with subprocess.Popen(command, env=env, stdout=subprocess.PIPE, text=True) as xserver:
        try:
            display = xserver.stdout.readline().strip()
            if not display.isdigit():
                raise RuntimeError('Xvfb did not return a display number')
            env['DISPLAY'] = ':' + display
            subprocess.run([sys.executable, Path(__file__).with_name('smoke_real.py'), core],
                           check=True, env=env, timeout=40)
        finally:
            if xserver.poll() is None:
                xserver.terminate()


if __name__ == '__main__':
    main(*sys.argv[1:])
