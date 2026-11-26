"""Opt-in native SDL2 smoke: PYTHONPATH=. python tests/smoke_mini.py.

Use an isolated 24-bit X11 display, xdotool, libX11 and RETRO_POCKET_POKEMINI.
The original MINX test cartridge is generated here; no ROM or BIOS downloads.
"""

from pathlib import Path
import tempfile

from mini import launch
from smoke_ds import Display, command, eventually


def make_rom():
    """Write 0x42 to EEPROM on A; show a different LCD pattern on restart."""
    rom = bytearray(0x4000)
    rom[0x2100:0x2105] = b'MN\xf3\xfd\x00'  # JMP $2202
    rom[0x21a4:0x21bc] = b'NINTENDORPSMRetroSmoke  '
    pc = 0x2202

    def emit(*data):
        nonlocal pc
        rom[pc:pc + len(data)] = bytes(data)
        pc += len(data)

    def move(reg, value):
        emit(0xDD, reg, value)  # MOV [N+reg], immediate; FreeBIOS sets N=$20

    def jump(opcode, target):
        offset = target - pc - 1
        assert -128 <= offset <= 127
        emit(opcode, offset & 255)

    def pins(value):
        move(0x61, value)

    def send(value):
        for bit in range(7, -1, -1):
            sda = 4 if value & (1 << bit) else 0
            pins(sda)
            pins(sda | 8)
        pins(0)
        move(0x60, 8)  # release SDA for ACK
        pins(8)
        pins(0)
        move(0x60, 12)

    def address_zero():
        pins(12)
        move(0x60, 12)
        pins(8)  # START while SCL high
        send(0xA0)
        send(0)
        send(0)

    def paint():
        # Fill 768 bytes of VRAM with A: column-major 8-pixel stripes.
        emit(0xC6, 0x00, 0x10, 0xC5, 0x00, 0x03)  # X=$1000, HL=$300
        loop = pc
        emit(0x60, 0x92, 0x99)  # MOV [X],A; INC X; DEC HL
        jump(0xE7, loop)

    move(0x80, 8)  # enable LCD copy from VRAM
    move(0x81, 1)
    address_zero()
    pins(4)
    pins(12)
    pins(8)  # repeated START
    send(0xA1)
    move(0x60, 8)  # release SDA and read the high bit of byte zero
    pins(8)
    emit(0x44, 0x61, 0x96, 4)  # MOV A,[N+$61]; TST A,4
    emit(0xB0, 0)  # blank EEPROM bit=1: white
    emit(0xE7, 3, 0xB0, 0xFF)  # saved bit=0: black
    paint()
    wait = pc
    emit(0x44, 0x52, 0x96, 1)  # active-low A button
    jump(0xE7, wait)
    address_zero()
    send(0x42)
    pins(0)
    pins(8)
    pins(12)  # STOP
    emit(0xB0, 0x55)
    paint()
    jump(0xF1, pc)
    return bytes(rom)


class MiniDisplay(Display):
    def pixel_pair(self, window):
        image = self.x.XGetImage(self.handle, int(window), 48, 48, 1, 8, -1, 2)
        if not image:
            raise RuntimeError('Could not sample PokeMini LCD')
        try:
            return tuple(self.x.XGetPixel(image, 0, y) for y in (0, 4))
        finally:
            self.x.XDestroyImage(image)


def exercise(display, rom, save_dir, press):
    with launch(rom, 'mini-smoke', save_dir) as process:
        try:
            window = command('xdotool', 'search', '--sync', '--onlyvisible', '--pid', str(process.pid))
            command('xdotool', 'windowfocus', '--sync', window)

            def lcd():
                pixels = display.pixel_pair(window)
                return tuple(sum(p >> shift & 255 for shift in (0, 8, 16)) > 400 for p in pixels)

            eventually(lcd, (press, press), 'boot LCD')
            if press:
                command('xdotool', 'keydown', 'x')
                try:
                    eventually(lambda: len(set(lcd())), 2, 'A press paints stripes')
                finally:
                    command('xdotool', 'keyup', 'x')
            process.terminate()  # SDL turns SIGTERM into SDL_QUIT on this build.
            if process.wait(timeout=5) != 0:
                raise AssertionError(f'Unclean SDL shutdown: {process.returncode}')
        finally:
            if process.poll() is None:
                process.kill()


def main():
    with tempfile.TemporaryDirectory(prefix='rp-mini-') as temp:
        saves = Path(temp) / 'saves literal;path'
        display = MiniDisplay()
        try:
            rom = make_rom()
            exercise(display, rom, saves, True)
            data = (saves / 'mini-smoke.eep').read_bytes()
            assert len(data) == 8192 and data[0] == 0x42, 'Expected guest-written 8 KiB EEPROM'
            exercise(display, rom, saves, False)
        finally:
            display.close()
    print('PokeMini booted, responded to A, and restored guest EEPROM on restart')


if __name__ == '__main__':
    main()
