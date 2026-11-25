"""Opt-in smoke test for the distro desmume-cli SDL frontend.

Run from the project root with `PYTHONPATH=. python tests/smoke_ds.py` on an
isolated X11 display (e.g. Xvfb). Requires xdotool, libX11 and GNU ARM binutils
(arm-none-eabi-as and arm-none-eabi-objcopy on PATH). No BIOS or ROM downloads.
"""

import ctypes as C
from pathlib import Path
import struct
import subprocess
import tempfile
import time

from ds import launch


# Original ARM code. ARM7 relays the pen bit; ARM9 paints a framebuffer based
# on KEYINPUT and the relayed pen bit. A also writes a byte to cartridge EEPROM.
SOURCE = '''
.syntax unified
.arm
.section .arm7,"ax"
    ldr r0, =0x04000136       @ EXTKEYIN: active-low pen bit (ARM7 only)
    ldr r1, =0x023ff000       @ shared main RAM
1:  ldrh r2, [r0]
    strh r2, [r1]
    b 1b
    .ltorg
.section .arm9,"ax"
    ldr r0, =0x04000304       @ POWCNT1: LCD, main 2D, main screen on top
    ldr r1, =0x8003
    strh r1, [r0]
    ldr r0, =0x04000240       @ VRAM A in LCDC mode
    mov r1, #0x80
    strb r1, [r0]
    ldr r0, =0x04000000       @ DISPCNT: display VRAM A directly
    mov r1, #0x20000
    str r1, [r0]

    ldr r7, =0x040001a0       @ cartridge backup SPI control/data
    bl read_save             @ 1-byte address + 1 reply lets DeSmuME autodetect
    bl read_save
    cmp r0, #0x42
    moveq r8, #1
    movne r8, #0

    ldr r1, =0x04000130       @ KEYINPUT: active-low A on bit 0
    ldr r2, =0x023ff000
    mov r9, #0
loop:
    ldr r3, =0x7c00          @ idle: blue
    cmp r8, #0
    ldrne r3, =0x03ff        @ saved: yellow
    ldrh r4, [r2]
    tst r4, #0x40
    ldreq r3, =0x03e0        @ pen: green
    ldrh r4, [r1]
    tst r4, #1
    bne paint
    cmp r9, #0
    bleq write_save
    mov r9, #1
    mov r3, #0x1f           @ A: red
paint:
    ldr r5, =0x06800000
    ldr r6, =0x06818000      @ 256 * 192 * 2 bytes
1:  strh r3, [r5], #2
    cmp r5, r6
    bne 1b
    b loop

read_save:
    mov r12, lr
    ldr r0, =0xa040          @ enable SPI, hold chip select
    strh r0, [r7]
    mov r0, #3              @ READ
    bl spi
    mov r0, #0              @ address
    bl spi
    mov r10, #0xa000         @ clear hold before sending the final byte
    strh r10, [r7]
    mov r0, #0              @ dummy byte to read reply
    bl spi
    mov r10, #0
    strh r10, [r7]
    bx r12
write_save:
    mov r12, lr
    mov r0, #0xa000
    strh r0, [r7]
    mov r0, #6              @ WREN
    bl spi
    mov r0, #0
    strh r0, [r7]
    ldr r0, =0xa040
    strh r0, [r7]
    mov r0, #2              @ WRITE
    bl spi
    mov r0, #0              @ address
    bl spi
    mov r0, #0xa000
    strh r0, [r7]
    mov r0, #0x42           @ data
    bl spi
    mov r0, #0
    strh r0, [r7]
    bx r12
spi:
    strb r0, [r7, #2]
1:  ldrh r0, [r7]
    tst r0, #0x80
    bne 1b
    ldrb r0, [r7, #2]
    bx lr
    .ltorg
'''


def command(*args):
    return subprocess.check_output(args, text=True, timeout=10).strip()


def crc16(data):
    crc = 0xffff
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xa001 if crc & 1 else 0)
    return crc


def make_rom(root):
    asm = root / 'smoke.s'
    obj = root / 'smoke.o'
    asm.write_text(SOURCE)
    command('arm-none-eabi-as', '-march=armv4t', '-o', obj, asm)
    rom = bytearray(128 * 1024)
    rom[:16] = b'RP DS SMOKE\0####'
    for cpu, header, offset, load in (
        (9, 0x20, 0x4000, 0x02000000), (7, 0x30, 0x5000, 0x03800000),
    ):
        binary = root / f'arm{cpu}.bin'
        command('arm-none-eabi-objcopy', '-O', 'binary', '-j', f'.arm{cpu}', obj, binary)
        payload = binary.read_bytes()
        rom[offset:offset + len(payload)] = payload
        struct.pack_into('<4I', rom, header, offset, load, load, len(payload))
    struct.pack_into('<2I', rom, 0x80, 0x6000, 0x4000)  # ROM used size, header size
    struct.pack_into('<H', rom, 0x15e, crc16(rom[:0x15e]))
    return bytes(rom)


def eventually(probe, expected, message):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        actual = probe()
        if actual == expected:
            return
        time.sleep(0.03)
    raise AssertionError(f'{message}: expected {expected!r}, got {actual!r}')


class Display:
    def __init__(self):
        x = self.x = C.CDLL('libX11.so.6')
        for name, result, args in (
            ('XOpenDisplay', C.c_void_p, [C.c_char_p]),
            ('XCloseDisplay', C.c_int, [C.c_void_p]),
            ('XGetImage', C.c_void_p, [C.c_void_p, C.c_ulong, C.c_int, C.c_int,
                                      C.c_uint, C.c_uint, C.c_ulong, C.c_int]),
            ('XGetPixel', C.c_ulong, [C.c_void_p, C.c_int, C.c_int]),
            ('XDestroyImage', C.c_int, [C.c_void_p]),
        ):
            fn = getattr(x, name)
            fn.restype, fn.argtypes = result, args
        self.handle = x.XOpenDisplay(None)
        if not self.handle:
            raise RuntimeError('Run this smoke test on a dedicated X11 display')

    def pixel(self, window):
        # Xvfb uses a 24-bit TrueColor visual, so pixel layout is 0xRRGGBB.
        image = self.x.XGetImage(self.handle, int(window), 128, 96, 1, 1, -1, 2)
        if not image:
            raise RuntimeError('Could not sample the emulator framebuffer')
        try:
            return f'#{self.x.XGetPixel(image, 0, 0):06x}'
        finally:
            self.x.XDestroyImage(image)

    def close(self):
        self.x.XCloseDisplay(self.handle)


def exercise(display, rom, save_dir, expected):
    with launch(rom, 'synthetic-ds', save_dir) as proc:
        try:
            window = command('xdotool', 'search', '--sync', '--onlyvisible', '--pid', str(proc.pid))
            command('xdotool', 'windowfocus', '--sync', window)
            pixel = lambda: display.pixel(window)
            eventually(pixel, expected, 'initial framebuffer')
            if expected == '#0000ff':
                command('xdotool', 'keydown', 'x')
                eventually(pixel, '#ff0000', 'default X key produces DS A')
                command('xdotool', 'keyup', 'x')
                eventually(pixel, expected, 'releasing X restores idle framebuffer')
                command('xdotool', 'mousemove', '--window', window, '128', '288', 'mousedown', '1')
                eventually(pixel, '#00ff00', 'lower-screen mouse press produces pen down')
                command('xdotool', 'mouseup', '1')
                eventually(pixel, expected, 'pen release restores idle framebuffer')
            command('xdotool', 'key', 'Escape')
            if proc.wait(timeout=10) != 0:
                raise AssertionError(f'DeSmuME exited with {proc.returncode}')
        finally:
            if proc.poll() is None:
                proc.kill()


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        rom = make_rom(root)
        save_dir = root / 'persistent saves'
        display = Display()
        try:
            exercise(display, rom, save_dir, '#0000ff')
            save = save_dir / 'desmume' / 'synthetic-ds.dsv'
            if save.read_bytes()[:1] != b'\x42':
                raise AssertionError(f'Cartridge byte not saved in {save}')
            exercise(display, rom, save_dir, '#ffff00')
        finally:
            display.close()
    print('DeSmuME launched, keyboard and touch changed the framebuffer, and EEPROM survived restart')


if __name__ == '__main__':
    main()
