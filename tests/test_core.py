import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch


def gba_rom():
    """Synthetic ARM cartridge: paint the first mode-3 pixel red, then loop."""
    rom = bytearray(0x4000)
    struct.pack_into('<I', rom, 0, 0xEA00002E)  # b 0xc0
    rom[0xA0:0xAC] = b'POCKET TEST\0'
    rom[0xAC:0xB0] = b'TEST'
    rom[0xB2] = 0x96
    rom[0xBD] = (-sum(rom[0xA0:0xBD]) - 0x19) & 0xFF
    words = (
        0xE3A00301,  # mov r0, #0x04000000 (I/O)
        0xE59F1010,  # ldr r1, =0x0403 (mode 3, BG2 on)
        0xE1C010B0,  # strh r1, [r0]
        0xE3A00406,  # mov r0, #0x06000000 (VRAM)
        0xE3A0101F,  # mov r1, #31 (red)
        0xE1C010B0,  # strh r1, [r0]
        0xEAFFFFFE,  # b .
        0x00000403,
    )
    struct.pack_into(f'<{len(words)}I', rom, 0xC0, *words)
    return bytes(rom)


def gb_rtc_rom():
    """Synthetic MBC3 cartridge. A writes SRAM and the RTC seconds register."""
    rom = bytearray(0x8000)
    rom[0x100:0x104] = bytes.fromhex('00 c3 50 01')  # nop; jp $150
    rom[0x104:0x108] = bytes.fromhex('ce ed 66 66')  # mGBA's GB signature
    rom[0x134:0x13f] = b'POCKET TEST'
    rom[0x147:0x14a] = bytes((0x10, 0, 2))  # MBC3+RTC+RAM, 32 KiB ROM, 8 KiB SRAM
    rom[0x14d] = (-sum(rom[0x134:0x14d]) - 25) & 0xff
    program = bytes.fromhex('''
        3e 0a ea 00 00
        3e 10 e0 00
        f0 00 cb 47 20 fa
        3e 5a ea 00 a0
        3e 08 ea 00 40
        3e 2a ea 00 a0
        18 fe
    ''')  # enable RAM, select buttons, wait for A, SRAM[0]=90, RTC seconds=42
    rom[0x150:0x150 + len(program)] = program
    return bytes(rom)


def gba_rtc_rom():
    """Synthetic GPIO program; A sends the RTC reset command (0x06)."""
    rom = bytearray(gba_rom())
    rom[0xac:0xb0] = b'U3IE'  # select mGBA's existing RTC+EEPROM hardware profile
    rom[0xbd] = (-sum(rom[0xa0:0xbd]) - 0x19) & 0xff
    words = [
        0xE3A00301,  # mov r0, #0x04000000 (I/O)
        0xE2800C01,  # add r0, #0x100
        0xE1D030B0 | (3 << 8),  # ldrh r3, [r0, #0x30] (KEYINPUT)
        0xE3130001,  # tst r3, #1
        0x1AFFFFFC,  # bne back to ldrh
        0xE3A00302,  # mov r0, #0x08000000 (cartridge)
        0xE28000C4,  # add r0, #0xc4 (GPIO data)
        0xE3A01007,  # mov r1, #7 (all RTC pins output)
        0xE1C010B2,  # strh r1, [r0, #2] (GPIO directions)
    ]
    pins = [1, 5]
    for i in range(8):
        low = 4 | (((0x06 >> i) & 1) << 1)
        pins.extend((low, low | 1))
    for pin in [*pins, 1]:
        words.extend((0xE3A01000 | pin, 0xE1C010B0))  # mov r1, #pin; strh r1, [r0]
    words.append(0xEAFFFFFE)
    # Put code beyond the cartridge GPIO registers at c4-c9.
    struct.pack_into('<I', rom, 0, 0xEA00007E)  # b 0x200
    struct.pack_into(f'<{len(words)}I', rom, 0x200, *words)
    return bytes(rom)


def installed_core():
    """MGBA_LIBRETRO, else the core the app would find (distro package or emulators\\mgba); None if absent."""
    supplied = os.environ.get('MGBA_LIBRETRO')
    if supplied:
        return supplied
    from core import locate_core
    try:
        return locate_core()
    except OSError:
        return None


class CoreTests(unittest.TestCase):
    def setUp(self):
        lib = installed_core()
        if lib is None:
            self.skipTest('Install libretro-mgba (Linux) or run setup.cmd / setup.command, or set MGBA_LIBRETRO')
        self.retro_path = str(lib)
        scratch = self.enterContext(tempfile.TemporaryDirectory())
        self.save_dir = Path(scratch) / 'saves'

    def open_core(self, rom):
        from core import Core

        instance = Core(rom, self.retro_path, self.save_dir)
        self.addCleanup(instance.close)
        return instance

    def test_headless_frame_and_audio(self):
        instance = self.open_core(gba_rom())
        self.assertAlmostEqual(instance.fps, 59.73, places=2)
        self.assertGreater(instance.sample_rate, 0)
        for _ in range(4):
            frame = instance.run(set())
        self.assertIsNotNone(frame)
        width, height, pixels = frame
        self.assertEqual((width, height), (240, 160))
        self.assertIsInstance(pixels, bytes)
        self.assertEqual(len(pixels), width * height * 3)
        self.assertEqual(pixels[:6], b'\xff\0\0\0\0\0')
        self.assertEqual(pixels[width * 3:width * 3 + 3], b'\0\0\0')
        self.assertIsInstance(instance.audio, bytearray)
        self.assertGreater(len(instance.audio), 0)
        self.assertEqual(len(instance.audio) % 4, 0)
        instance.audio.clear()
        instance.run(set())
        self.assertGreater(len(instance.audio), 0)

    def test_sram_and_live_mbc3_rtc_save_before_core_flushes(self):
        rom = gb_rtc_rom()
        instance = self.open_core(rom)
        instance.run(set())
        instance.save()
        target = self.save_dir / 'cartridge.sav'
        self.assertEqual(target.read_bytes()[0], 0xff)
        instance.run({'a'})
        instance.save()
        saved = target.read_bytes()
        self.assertEqual(saved[0], 0x5a)
        self.assertEqual(struct.unpack_from('<I', saved, 8192 + 20)[0], 42)
        instance.close()

        reopened = self.open_core(rom)
        reopened.run(set())
        reopened.save()
        self.assertEqual(target.read_bytes(), saved)

    def test_gba_gpio_clock_control_round_trip(self):
        rom = gba_rtc_rom()
        target = self.save_dir / 'cartridge.sav'
        instance = self.open_core(rom)
        instance.run(set())
        instance.save()
        self.assertEqual(target.read_bytes()[-9], 0x40)
        instance.run({'a'})
        instance.save()
        self.assertEqual(target.read_bytes()[-9], 0)
        instance.close()

        reopened = self.open_core(rom)
        reopened.run(set())
        reopened.save()
        self.assertEqual(target.read_bytes()[-9], 0)

    def test_failed_atomic_replace_leaves_previous_save_intact(self):
        instance = self.open_core(gb_rtc_rom())
        instance.run(set())
        instance.save()
        target = self.save_dir / 'cartridge.sav'
        previous = target.read_bytes()
        instance.run({'a'})
        with patch('core.os.replace', side_effect=OSError('simulated I/O failure')):
            with self.assertRaises(OSError):
                instance.save()
        self.assertEqual(target.read_bytes(), previous)
        self.assertEqual(list(self.save_dir.iterdir()), [target])

    def test_second_live_instance_is_rejected_before_touching_callbacks(self):
        instance = self.open_core(gba_rom())
        with self.assertRaisesRegex(RuntimeError, 'already open'):
            self.open_core(gba_rom())
        self.assertIsNotNone(instance.run(set()))
        instance.close()
        instance.close()
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            instance.run(set())
        self.assertIsNotNone(self.open_core(gba_rom()).run(set()))

    def test_native_load_failure_does_not_prevent_reopening(self):
        self.open_core(gba_rom()).close()
        with self.assertRaisesRegex(ValueError, 'could not load the ROM'):
            self.open_core(bytes(0x4000))
        self.assertIsNotNone(self.open_core(gba_rom()).run(set()))

    def test_mbc3_clock_only_cartridge_restores_clock(self):
        rom = bytearray(gb_rtc_rom())
        rom[0x147:0x14a] = bytes((0x0f, 0, 0))
        rom[0x14d] = (-sum(rom[0x134:0x14d]) - 25) & 0xff
        instance = self.open_core(bytes(rom))
        instance.run({'a'})
        instance.save()
        target = self.save_dir / 'cartridge.sav'
        self.assertEqual(struct.unpack_from('<I', target.read_bytes(), 20)[0], 42)
        instance.close()
        reopened = self.open_core(bytes(rom))
        reopened.run(set())
        reopened.save()
        self.assertEqual(struct.unpack_from('<I', target.read_bytes(), 20)[0], 42)


class PixelConversionTests(unittest.TestCase):
    def test_fast_conversion_matches_reference_table_for_every_pixel(self):
        import core
        from array import array

        for fmt in (core._RGB1555, core._RGB565):
            with self.subTest(fmt=fmt):
                values = array('H', range(1 << 16))
                lookup = core._RGB16[fmt]
                mask = len(lookup) - 1
                expected = b''.join(lookup[v & mask] for v in values)
                self.assertEqual(core._convert16(values.tobytes(), fmt), expected)
