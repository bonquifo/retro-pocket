"""Opt-in native smoke: run on a dedicated 24-bit X11 display.

Requires Mupen64Plus (tested with Glide64mk2), mips-linux-gnu binutils, and
xdotool. Run with PYTHONPATH=. python tests/smoke_n64.py from the project root.
The fixture uses the emulator's HLE boot, not Nintendo boot code or a BIOS.
"""

import hashlib
from pathlib import Path
import tempfile

from n64 import launch
from smoke_ds import Display, command, eventually


# Mupen's PIF HLE copies the first 4 KiB of the cartridge to SP memory, then
# starts at offset 0x40. Everything here runs from there, no linker needed.
SOURCE = r'''
    .set noreorder
    .text
    .word 0x80371240, 0x0000000f, 0x80000400, 0
    .word 0x5250534d, 0x534d4f4b, 0, 0 # unlisted CRC words select the homebrew save type
    .ascii "RP N64 SMOKE        "
    .word 0, 0x0000004e
    .ascii "DEE\x30"          # DE homebrew ID, NTSC, 256 Kbit SRAM

    # Disable CPU interrupts; poll the SI rather than using a handler.
    mtc0 $zero, $12
    lui $s0, 0xa440           # VI
    lui $s1, 0xa460           # PI
    lui $s2, 0xa800           # cartridge SRAM domain
    lui $s3, 0xa480           # SI
    lui $s4, 0xa000           # uncached RDRAM

    # Three 320x240 RGBA8888 framebuffers (blue, red, green).
    lui $a0, 0xa010
    li $a1, 0x0000ffff
    bal fill
    nop
    lui $a0, 0xa018
    li $a1, 0xff0000ff
    bal fill
    nop
    lui $a0, 0xa020
    li $a1, 0x00ff00ff
    bal fill
    nop

    # Read SRAM through PI DMA (a CPU read on an undetected save bus
    # selects FlashRAM instead on Mupen64Plus).
    li $t0, 0x2000
    sw $t0, 0($s1)
    li $t0, 0x08000000
    sw $t0, 4($s1)
    li $t0, 3
    sw $t0, 12($s1)
    bal wait_pi
    nop
    lw $t0, 0x2000($s4)
    li $s5, 0x5250534d        # RPSM
    lui $s6, 0x0010
    bne $t0, $s5, video
    nop
    lui $s6, 0x0020
video:
    sw $s6, 4($s0)            # VI_ORIGIN
    li $t0, 320
    sw $t0, 8($s0)            # VI_WIDTH
    li $t0, 2
    sw $t0, 12($s0)           # VI_V_INTR
    li $t0, 0x03e52239
    sw $t0, 20($s0)           # VI_BURST
    li $t0, 525
    sw $t0, 24($s0)           # VI_V_SYNC
    li $t0, 0x0c15
    sw $t0, 28($s0)           # VI_H_SYNC
    li $t0, 0x0c150c15
    sw $t0, 32($s0)           # VI_LEAP
    li $t0, 0x006c02ec
    sw $t0, 36($s0)           # VI_H_START
    li $t0, 0x002501ff
    sw $t0, 40($s0)           # VI_V_START
    li $t0, 0x000e0204
    sw $t0, 44($s0)           # VI_V_BURST
    li $t0, 0x0200
    sw $t0, 48($s0)           # VI_X_SCALE
    li $t0, 0x0400
    sw $t0, 52($s0)           # VI_Y_SCALE
    li $t0, 0x020f
    sw $t0, 0($s0)            # VI_STATUS: RGBA8888, no AA

    # Joybus channel 0: transmit READ_CONTROLLER and receive four bytes.
    li $t1, 0x1fc007c0
poll:
    li $t0, 0x01040100
    sw $t0, 0x1000($s4)
    li $t0, 0x000000fe
    sw $t0, 0x1004($s4)
    li $t0, 1
    sw $t0, 0x103c($s4)       # PIF process command
    li $t0, 0x1000
    sw $t0, 0($s3)
    sw $t1, 16($s3)           # RDRAM -> PIF
    bal wait_si
    nop
    sw $t1, 4($s3)            # PIF -> RDRAM
    bal wait_si
    nop
    lbu $t0, 0x1003($s4)
    andi $t0, $t0, 0x80       # N64 A button
    beqz $t0, released
    move $t2, $s6
    sw $s5, 0($s2)            # Persist marker only on input
    lui $t2, 0x0018
released:
    sw $t2, 4($s0)
    b poll
    nop
wait_si:
    lw $t0, 24($s3)
    andi $t0, $t0, 3
    bnez $t0, wait_si
    nop
    jr $ra
    sw $zero, 24($s3)
wait_pi:
    lw $t0, 16($s1)
    andi $t0, $t0, 3
    bnez $t0, wait_pi
    nop
    jr $ra
    nop
fill:
    li $t0, 320*240
1:  sw $a1, 0($a0)
    addiu $t0, $t0, -1
    bnez $t0, 1b
    addiu $a0, $a0, 4
    jr $ra
    nop
'''


def make_rom(root):
    source, obj, binary = (root / name for name in ('smoke.s', 'smoke.o', 'smoke.bin'))
    source.write_text(SOURCE)
    command('mips-linux-gnu-as', '-EB', '-march=vr4300', '-o', obj, source)
    command('mips-linux-gnu-objcopy', '-O', 'binary', '-j', '.text', obj, binary)
    return binary.read_bytes().ljust(1024 * 1024, b'\x00')


def exercise(display, rom, save_dir, boot_color, press_a):
    with launch(rom, 'synthetic-n64', save_dir) as proc:
        try:
            window = command('xdotool', 'search', '--sync', '--onlyvisible', '--pid', str(proc.pid))
            command('xdotool', 'windowfocus', '--sync', window)

            def pixel():
                return display.pixel(window)

            eventually(pixel, boot_color, 'initial framebuffer')
            if press_a:
                # Default keyboard mapping: left Shift is N64 A.
                command('xdotool', 'keydown', 'Shift_L')
                try:
                    eventually(pixel, '#ff0000', 'N64 A press')
                finally:
                    command('xdotool', 'keyup', 'Shift_L')
                eventually(pixel, boot_color, 'N64 A release')
            command('xdotool', 'key', 'Escape')
            if proc.wait(timeout=10) != 0:
                raise AssertionError(f'Mupen64Plus exited with {proc.returncode}')
        finally:
            if proc.poll() is None:
                proc.kill()


def main():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        rom = make_rom(root)
        print(f'Original {len(rom)}-byte Z64: SHA-256 {hashlib.sha256(rom).hexdigest()}', flush=True)
        save_dir = root / 'persistent saves'
        display = Display()
        try:
            exercise(display, rom, save_dir, '#0000ff', press_a=True)
            (save,) = save_dir.glob('*.sra')
            if save.read_bytes()[:4] not in (b'RPSM', b'MSPR'):
                raise AssertionError(f'Guest did not write the marker to {save}')
            if not (save_dir / 'mupen64plus.cfg').is_file():
                raise AssertionError('Per-title configuration is missing')
            exercise(display, rom, save_dir, '#00ff00', press_a=False)
        finally:
            display.close()
    print('Mupen64Plus booted the original ROM, displayed A press/release, and reloaded cartridge SRAM')


if __name__ == '__main__':
    main()
