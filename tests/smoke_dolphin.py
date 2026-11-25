"""Native Dolphin startup smoke. Run on a disposable X11 display with xwininfo."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from dolphin_backend import launch
from smoke_ds import Display, command, eventually


def close_window(window):
    import ctypes as c

    class ClientMessage(c.Structure):
        _fields_ = [('type', c.c_int), ('serial', c.c_ulong), ('send_event', c.c_int),
                    ('display', c.c_void_p), ('window', c.c_ulong), ('message_type', c.c_ulong),
                    ('format', c.c_int), ('data', c.c_long * 5)]

    display = Display()
    try:
        display.x.XInternAtom.argtypes = [c.c_void_p, c.c_char_p, c.c_int]
        display.x.XInternAtom.restype = c.c_ulong
        display.x.XSendEvent.argtypes = [c.c_void_p, c.c_ulong, c.c_int, c.c_long, c.c_void_p]
        display.x.XFlush.argtypes = [c.c_void_p]
        atom = lambda name: display.x.XInternAtom(display.handle, name, 0)
        event = (c.c_long * 24)()
        msg = ClientMessage.from_buffer(event)
        msg.type, msg.display, msg.window, msg.format = 33, display.handle, int(window), 32
        msg.message_type, msg.data[0] = atom(b'WM_PROTOCOLS'), atom(b'WM_DELETE_WINDOW')
        if not display.x.XSendEvent(display.handle, int(window), 0, 0, c.byref(event)):
            raise RuntimeError('Could not send a normal window close event')
        display.x.XFlush(display.handle)
    finally:
        display.close()


def main():
    if not os.environ.get('DISPLAY'):
        raise RuntimeError('A dedicated X11 display is required')
    with tempfile.TemporaryDirectory(prefix='rp-dolphin-') as tmp:
        directory = Path(tmp)
        if len(sys.argv) != 2:
            raise SystemExit('Pass the path to the 240p Test Suite GameCube homebrew ISO')
        rom = Path(sys.argv[1]).resolve()
        with launch(rom, 'gcn-original-test', directory / 'saves') as process:
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError(f'Dolphin exited early: {process.returncode}')
                    windows = subprocess.check_output(['xwininfo', '-root', '-tree'], text=True)
                    match = re.search(r'^\s+(0x[0-9a-f]+) "[^"\n]*(?:JIT64|FPS:|VPS:|240p Test Suite)[^"\n]*"', windows, re.M)
                    if match:
                        break
                    time.sleep(.1)
                else:
                    raise RuntimeError('Dolphin emulation window not found:\n' + windows)
                window = str(int(match.group(1), 16))
                display = Display()
                try:
                    eventually(lambda: display.pixel(window) != '#000000', True, 'rendered a nonblack pixel')
                finally:
                    display.close()
                close_window(window)
                if process.wait(timeout=10) != 0:
                    raise RuntimeError(f'Dolphin exit: {process.returncode}')
                print(f'Dolphin rendered {rom.name} and closed cleanly')
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()


if __name__ == '__main__':
    main()
