"""In-process ctypes frontend for the mGBA libretro core."""

from array import array
import ctypes as C
import os
from pathlib import Path
import struct
import sys
import tempfile
from threading import Lock
import time

from compat import EMULATORS, WINDOWS, program_files

if WINDOWS:
    from _ctypes import FreeLibrary as _unload
else:
    from _ctypes import dlclose as _unload


class _GameInfo(C.Structure):
    _fields_ = [('path', C.c_char_p), ('data', C.c_void_p),
                ('size', C.c_size_t), ('meta', C.c_char_p)]


class _Geometry(C.Structure):
    _fields_ = [('base_width', C.c_uint), ('base_height', C.c_uint),
                ('max_width', C.c_uint), ('max_height', C.c_uint),
                ('aspect_ratio', C.c_float)]


class _Timing(C.Structure):
    _fields_ = [('fps', C.c_double), ('sample_rate', C.c_double)]


class _AVInfo(C.Structure):
    _fields_ = [('geometry', _Geometry), ('timing', _Timing)]


_Environment = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
_Video = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
_AudioSample = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
_AudioBatch = C.CFUNCTYPE(C.c_size_t, C.c_void_p, C.c_size_t)
_InputPoll = C.CFUNCTYPE(None)
_InputState = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)

_GET_CAN_DUPE = 3
_GET_SYSTEM_DIRECTORY = 9
_SET_PIXEL_FORMAT = 10
_GET_VARIABLE_UPDATE = 17
_GET_SAVE_DIRECTORY = 31
_RGB1555, _XRGB8888, _RGB565 = range(3)
_JOYPAD = 1
_SAVE_RAM, _RTC = 0, 1
_GBA_RTC_TAG = b'RPGBArtc'
_MBC3_FOOTER = struct.Struct('<10IQ')
_CORE_SLOT = Lock()  # mGBA has process-global callbacks and game state
_BUTTON_IDS = {'b': 0, 'select': 2, 'start': 3, 'up': 4, 'down': 5,
               'left': 6, 'right': 7, 'a': 8, 'l': 10, 'r': 11}


def _installed_cores():
    """Fixed places the mGBA libretro core is installed to, never PATH."""
    if WINDOWS:
        roots = [EMULATORS / 'mgba']
        appdata = os.environ.get('APPDATA')
        if appdata and Path(appdata).is_absolute():
            roots.append(Path(appdata) / 'RetroArch' / 'cores')
        roots += [root / 'RetroArch' / 'cores' for root in program_files()]
        roots += [Path(r'C:\RetroArch-Win64\cores'),
                  *(root / 'Steam' / 'steamapps' / 'common' / 'RetroArch' / 'cores' for root in program_files())]
        return [root / 'mgba_libretro.dll' for root in roots]
    return (sorted(Path('/usr/lib').glob('*/libretro/mgba_libretro.so')) +
            [Path('/usr/lib/libretro/mgba_libretro.so')])


def locate_core(path=None):
    path = path or os.getenv('RETRO_POCKET_CORE')
    candidates = [Path(path).expanduser()] if path else _installed_cores()
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    if WINDOWS:
        raise OSError('mGBA core not found. Run tools\\setup_windows.py, or pass '
                      '--core C:\\path\\to\\mgba_libretro.dll.')
    raise OSError('mGBA core not found. Install libretro-mgba or pass --core /path/to/mgba_libretro.so.')


def _rgb16_table(pixel_format):
    green_bits = 6 if pixel_format == _RGB565 else 5
    green_mask = (1 << green_bits) - 1
    five = [(n << 3) | (n >> 2) for n in range(32)]
    green = [(n << 2) | (n >> 4) for n in range(64)] if green_bits == 6 else five
    return tuple(bytes((five[p >> (green_bits + 5)], green[(p >> 5) & green_mask],
                        five[p & 31])) for p in range(1 << (green_bits + 10)))


_RGB16 = {fmt: _rgb16_table(fmt) for fmt in (_RGB1555, _RGB565)}


def _channel_tables(pixel_format):
    """Byte tables that convert a whole 16-bit frame with C-level translate().

    Red depends only on a pixel's high byte and blue only on its low byte.
    Green's index is split across both bytes with no overlapping bits, so the
    two halves can be OR-ed and then expanded. Values match ``_rgb16_table``.
    """
    five = [(n << 3) | (n >> 2) for n in range(32)]
    if pixel_format == _RGB565:
        green = [(n << 2) | (n >> 4) for n in range(64)]
        red_hi = bytes(five[h >> 3] for h in range(256))
        green_hi = bytes((h & 7) << 3 for h in range(256))
    else:  # 0RRRRRGG GGGBBBBB; the unused top bit is ignored
        green = five
        red_hi = bytes(five[(h >> 2) & 31] for h in range(256))
        green_hi = bytes((h & 3) << 3 for h in range(256))
    green_lo = bytes(n >> 5 for n in range(256))
    blue_lo = bytes(five[n & 31] for n in range(256))
    green_expand = bytes(green[n] if n < len(green) else 0 for n in range(256))
    return red_hi, green_hi, green_lo, blue_lo, green_expand


_CHANNELS = {fmt: _channel_tables(fmt) for fmt in (_RGB1555, _RGB565)}


def _convert16(raw, pixel_format):
    """Pack native-endian 16-bit pixels as RGB bytes."""
    red_hi, green_hi, green_lo, blue_lo, green_expand = _CHANNELS[pixel_format]
    low, high = (raw[0::2], raw[1::2]) if sys.byteorder == 'little' else (raw[1::2], raw[0::2])
    count = len(low)
    green = (int.from_bytes(high.translate(green_hi), 'little')
             | int.from_bytes(low.translate(green_lo), 'little')).to_bytes(count, 'little')
    rgb = bytearray(count * 3)
    rgb[0::3] = high.translate(red_hi)
    rgb[1::3] = green.translate(green_expand)
    rgb[2::3] = low.translate(blue_lo)
    return bytes(rgb)


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    file = tempfile.NamedTemporaryFile(dir=path.parent, prefix='.save-', delete=False)
    temporary = Path(file.name)
    try:
        with file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


# GBA savestate versions whose hardware block keeps the RTC control byte at
# 0x2ac, seven latched BCD time bytes at 0x2b0 and the GPIO device mask at
# 0x2b7: v7 (mGBA 0.10, Ubuntu's core) through v11 (the libretro buildbot's
# Windows core, from mGBA 0.11's development line).
_GBA_RTC_STATE_VERSIONS = range(7, 12)


def _gba_clock(state):
    # RTC control, seven latched BCD time bytes, and the GPIO device mask
    # (bit 0 indicates an RTC).
    if len(state) < 0x2b8 or state[2:4] != b'\x00\x01':
        return False
    version = int.from_bytes(state[:2], 'little')
    return version in _GBA_RTC_STATE_VERSIONS and state[0x2b7] & 1


def _mbc3_state(state):
    return len(state) >= 0x18c and state[:4] == b'\x03\x00\x40\x00'


class Core:
    """Run one mGBA ROM at a time; call ``save()`` before ``close()``.

    Consume audio by reading and clearing ``audio``. Use this object serially
    from the emulation thread and give each ROM its own save directory.
    """

    def __init__(self, rom: bytes, retro_path: str, save_dir: Path):
        self.audio = bytearray()
        self._frame = None
        self._pixel_format = _RGB1555  # libretro's default until negotiated
        self._pressed = set()
        directory = Path(save_dir).resolve()
        self._directory = os.fsencode(directory)
        self._save_path = directory / 'cartridge.sav'
        self._rom = bytes(rom)  # Borrowed by the core via a pointer below; no second copy.
        self._initialized = self._loaded = False
        self._lib = None
        self._owns_slot = _CORE_SLOT.acquire(blocking=False)
        if not self._owns_slot:
            raise RuntimeError('An mGBA core is already open in this process')
        try:
            self._open(retro_path)
        except BaseException:
            self.close()
            raise

    def _open(self, retro_path):
        try:
            self._lib = C.CDLL(retro_path)
        except OSError as exc:
            # Windows loader errors ("%1 is not a valid Win32 application") omit the file.
            if str(retro_path) in str(exc):
                raise
            raise OSError(f'{retro_path}: {exc}') from exc
        if self._bind('api_version', C.c_uint)() != 1:
            raise RuntimeError('Unsupported libretro API version')
        callbacks = (
            ('environment', _Environment(self._environment)),
            ('video_refresh', _Video(self._video)),
            ('audio_sample', _AudioSample(self._audio_sample)),
            ('audio_sample_batch', _AudioBatch(self._audio_batch)),
            ('input_poll', _InputPoll(lambda: None)),
            ('input_state', _InputState(self._input_state)),
        )
        self._callbacks = callbacks  # libretro keeps these function pointers
        for suffix, callback in callbacks:
            self._bind('set_' + suffix, None, type(callback))(callback)
        for name in ('init', 'deinit', 'unload_game', 'run'):
            self._bind(name, None)
        load_game = self._bind('load_game', C.c_bool, C.POINTER(_GameInfo))
        get_av = self._bind('get_system_av_info', None, C.POINTER(_AVInfo))
        self._bind('get_memory_size', C.c_size_t, C.c_uint)
        self._bind('get_memory_data', C.c_void_p, C.c_uint)
        self._bind('serialize_size', C.c_size_t)
        self._bind('serialize', C.c_bool, C.c_void_p, C.c_size_t)
        self._bind('unserialize', C.c_bool, C.c_void_p, C.c_size_t)
        self._lib.retro_init()
        self._initialized = True
        game = _GameInfo(None, C.cast(C.c_char_p(self._rom), C.c_void_p).value, len(self._rom), None)
        if not load_game(C.byref(game)):
            raise ValueError('mGBA could not load the ROM')
        self._loaded = True
        av = _AVInfo()
        get_av(C.byref(av))
        self.fps = av.timing.fps
        self.sample_rate = av.timing.sample_rate
        self._gba = (av.geometry.base_width, av.geometry.base_height) == (240, 160)
        self._restore_save()

    def _bind(self, name, result, *arguments):
        function = getattr(self._lib, 'retro_' + name)
        function.restype = result
        function.argtypes = arguments
        return function

    def _environment(self, command, data):
        if command == _SET_PIXEL_FORMAT:
            fmt = C.c_int.from_address(data).value
            if fmt not in (_RGB1555, _XRGB8888, _RGB565):
                return False
            self._pixel_format = fmt
        elif command in (_GET_CAN_DUPE, _GET_VARIABLE_UPDATE):
            C.c_bool.from_address(data).value = command == _GET_CAN_DUPE
        elif command in (_GET_SYSTEM_DIRECTORY, _GET_SAVE_DIRECTORY):
            C.cast(data, C.POINTER(C.c_char_p))[0] = self._directory
        else:
            return False
        return True

    def _video(self, data, width, height, pitch):
        if not data:  # NULL means repeat the previous frame
            return
        fmt = self._pixel_format
        row_bytes = width * (4 if fmt == _XRGB8888 else 2)
        if pitch == row_bytes:  # Contiguous frame: one copy instead of one per row.
            rows = C.string_at(data, row_bytes * height)
        else:
            rows = b''.join(C.string_at(data + y * pitch, row_bytes) for y in range(height))
        if fmt == _XRGB8888:
            pixels = bytearray(width * height * 3)
            offsets = (2, 1, 0) if sys.byteorder == 'little' else (1, 2, 3)
            for channel, offset in enumerate(offsets):
                pixels[channel::3] = rows[offset::4]
            rgb = bytes(pixels)
        else:
            rgb = _convert16(rows, fmt)
        self._frame = width, height, rgb

    def _audio_sample(self, left, right):
        self.audio.extend(array('h', (left, right)).tobytes())

    def _audio_batch(self, data, frames):
        self.audio.extend(C.string_at(data, frames * 4))
        return frames

    def _input_state(self, port, device, index, button):
        return int(port == 0 and device == _JOYPAD and index == 0 and button in self._pressed)

    def run(self, buttons: set[str]) -> tuple[int, int, bytes] | None:
        """Advance one emulated frame and return the latest packed RGB image."""
        if not self._loaded:
            raise RuntimeError('Core is closed')
        self._pressed = {_BUTTON_IDS[name] for name in buttons if name in _BUTTON_IDS}
        self._lib.retro_run()
        return self._frame

    def _memory(self, region):
        size = self._lib.retro_get_memory_size(region)
        return (self._lib.retro_get_memory_data(region), size) if size else (None, 0)

    def _restore_save(self):
        try:
            with self._save_path.open('rb') as file:
                data = file.read(128 * 1024 + _MBC3_FOOTER.size + 1)
        except FileNotFoundError:
            data = b''
        ram, ram_size = self._memory(_SAVE_RAM)
        rtc, rtc_size = self._memory(_RTC)
        gba_footer = b''
        if self._gba and len(data) % 256 == 16 and data.endswith(_GBA_RTC_TAG):
            data, gba_footer = data[:-16], data[-16:-8]
        if ram and data:
            C.memmove(ram, data, min(len(data), ram_size))
        if rtc:
            footer = data[ram_size:ram_size + rtc_size]
            if len(footer) != rtc_size and rtc_size == _MBC3_FOOTER.size:
                # Without a footer, the core reads its erased (0xff) backing
                # buffer as clock registers and a timestamp on the first run.
                footer = _MBC3_FOOTER.pack(*([0] * 10), int(time.time()))
            if len(footer) == rtc_size:
                C.memmove(rtc, footer, rtc_size)
                if not ram_size and rtc_size == _MBC3_FOOTER.size:
                    # GBLoadSave skips the native footer reader on RTC-only
                    # cartridges that have no external RAM.
                    state = bytearray(self._serialize())
                    if _mbc3_state(state):
                        fields = _MBC3_FOOTER.unpack(footer)
                        state[0x17f:0x184] = bytes(x & 0xff for x in fields[5:10])
                        struct.pack_into('<Q', state, 0x184, fields[-1])
                        self._restore_clock_state(state)
        if gba_footer:
            # Patch only the clock registers in a fresh state. Never load a
            # disk-backed CPU state or rewind gameplay to restore a battery.
            state = bytearray(self._serialize())
            if _gba_clock(state):
                state[0x2ac] = gba_footer[7]
                state[0x2b0:0x2b7] = gba_footer[:7]
                self._restore_clock_state(state)

    def _restore_clock_state(self, state):
        native = (C.c_char * len(state)).from_buffer(state)
        if not self._lib.retro_unserialize(native, len(state)):
            raise RuntimeError('mGBA could not restore the cartridge clock')

    def _serialize(self):
        size = self._lib.retro_serialize_size()
        state = C.create_string_buffer(size)
        if not size or not self._lib.retro_serialize(state, size):
            raise RuntimeError('mGBA could not snapshot the cartridge clock')
        return state.raw

    def save(self):
        """Atomically replace this game's cartridge save (RAM plus clock)."""
        if not self._loaded:
            raise RuntimeError('Core is closed')
        ram, ram_size = self._memory(_SAVE_RAM)
        rtc, rtc_size = self._memory(_RTC)
        data = C.string_at(ram, ram_size) if ram else b''
        if rtc and rtc_size == _MBC3_FOOTER.size:
            # The mGBA 0.10 GB state stores the live MBC3 registers and last
            # latch at 0x17f and 0x184. RETRO_MEMORY_RTC only exposes the
            # backing footer, which is stale until the core flushes it.
            state = self._serialize()
            if _mbc3_state(state):
                regs = state[0x17f:0x184]
                last_latch, = struct.unpack_from('<Q', state, 0x184)
                data += _MBC3_FOOTER.pack(*regs, *regs, last_latch)
            else:
                data += C.string_at(rtc, rtc_size)
        elif rtc:
            data += C.string_at(rtc, rtc_size)
        elif self._gba:
            # mGBA 0.10 does not export GBA GPIO RTC via RETRO_MEMORY_RTC.
            # Preserve the registers it emulates; the running clock uses host time.
            state = self._serialize()
            if _gba_clock(state):
                data += state[0x2b0:0x2b7] + state[0x2ac:0x2ad] + _GBA_RTC_TAG
        if data:
            _atomic_write(self._save_path, data)

    def close(self):
        """Release the native game and core; safe to call repeatedly."""
        if not self._owns_slot:
            return
        try:
            if self._loaded:
                self._loaded = False
                self._lib.retro_unload_game()
            if self._initialized:
                self._initialized = False
                self._lib.retro_deinit()
        finally:
            try:
                if self._lib is not None:
                    # mGBA 0.10's deinit frees a buffer without clearing its
                    # static pointer. Start with fresh globals on each load.
                    _unload(self._lib._handle)
                    self._lib = None
            finally:
                self._callbacks = ()
                self._rom = None
                self._owns_slot = False
                _CORE_SLOT.release()
