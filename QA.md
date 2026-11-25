# Gameplay and resize verification

These are short tests of the software paths, not completion playthroughs or a claim of zero bugs. No matching commercial Pokémon cartridge or disc image was found in the local library or user project/download files. Tests used homebrew and original fixtures, in temporary data folders. No physical audio device or physical HiDPI monitor was needed.

| Path | Check |
| --- | --- |
| Catalogue → mGBA subprocess (X11/Xvfb) | Resized the catalogue and player across wide, tall and compact sizes; clicked actual catalogue rows and the resized player Close button. Used keyboard search, downloaded pinned 2048, and verified a corrupt cache was rejected with a copyable log. (ROM downloads were removed on 2026-11-25; `tests/smoke_real.py` now copies a supplied 2048 ROM into a temporary ROM folder and corrupts that copy. On 2026-11-25 the updated script passed on Xvfb with Pokémon Red (USA, Europe): resizes, tile clicks, C, search, mGBA launch and Close button, and a damaged ROM-folder copy refused at launch with a clear digest message.) |
| mGBA gameplay (SDL dummy video, unavailable audio driver) | Booted 2048, opened the board with Enter, resized the running window twice, moved tiles via the on-screen D-pad, and exited with Escape. Separately used a synthetic cartridge to verify mouse input persisted a battery save. |
| Nintendo DS / DeSmuME | Synthetic cartridge: keyboard input and mouse touch affected video, and EEPROM reloaded after restart. |
| N64 / Mupen64Plus | Synthetic cartridge: keyboard A press/release affected video, and SRAM reloaded after restart. |
| Pokémon mini / PokeMini | Synthetic cartridge: keyboard input affected the LCD, and EEPROM reloaded after restart. |
| GameCube / Dolphin | The author's 240p Test Suite ISO rendered and closed cleanly in the native X11 frontend. No memory-card readback or commercial-game input was tested. |
| Nintendo 3DS / Azahar 2127.0 AppImage (Xvfb, Mesa software OpenGL) | All seven listed titles (X, Y, Omega Ruby, Alpha Sapphire, Sun, Moon, Ultra Moon) booted from the owner's decrypted dumps to the in-game language-selection screen. Pokémon X was also imported with `Library.import_rom` and launched through `emulator_worker.py` with Azahar autodetected at `~/Applications/azahar.AppImage`; it ran at 100% speed. A stale launch snapshot left by a killed worker was removed by the next launch's cleanup. Input, in-game saving and gameplay past the language screen were not tested. |

`tests/test_resize.py` covers aspect-ratio preservation, desktop-fit sizing, scaled hitboxes, letterbox rejection and coordinate conversion when surface pixels differ from window coordinates. The live-window smoke covers X11, not native Wayland or physical display scaling. Third-party windows are not controlled by the app's resize logic: the tested Ubuntu DeSmuME SDL frontend is fixed-size; PokeMini's native SDL2 renderer can stretch on resize.

With the dependencies and a valid mGBA libretro core installed:

```sh
MGBA_LIBRETRO=/path/to/mgba_libretro.so RETRO_POCKET_NETWORK_TESTS=1 \
  .venv/bin/python -m unittest discover -s tests -v
```

The real-window regression script is `tests/smoke_real.py` (pass a catalogued GB, GBC or GBA dump and the mGBA core path; use a disposable X11 display with `xwininfo` and `xdotool`); the sound-device-failure exercise is `tests/smoke_handheld.py` (pass the same ROM and core paths). The rows above that mention 2048 were run with the 2048 homebrew, which was removed from the catalogue on 2026-11-25.

## Performance and memory (2026-11-24, NVMe, 4 cores, X11/Xvfb, Mesa software GL)

| Path | Before | After |
| --- | --- | --- |
| Launch check, largest DS game (512 MB) | 548 MB peak, whole ROM in memory | 24 MB peak; streamed hash, hard link to the checked file |
| Launch, 4 GB 3DS image | 4 GB copy written per launch, 10.6 s | no copy (hard link), 5.7 s (SHA-1 bound) |
| First ROM-folder scan, 25 GB cold | n/a | 10.3 s, 25 MB, page cache left clean; 4 hashing threads on SSD, 1 on rotational disks |
| Cached ROM-folder scan at app start | n/a | 0.07 s |
| GBA frame (emulate + convert + draw) | ~5 ms | 2.3 ms; pixel conversion bit-identical (exhaustive test) |
| GBA player process | 186 MB | 82 MB (no GL presentation path on X11) |
| Library app idle, 1600×1000 window | ~14–17% of a core | 2.6% of a core; input handled on the next 30 fps tick |

Every launch still checks the full hash of the game file. Emulator memory (DeSmuME ~205 MB, Azahar ~750–770 MB) belongs to the emulators and is unchanged.

## Controls and save persistence (2026-11-24, real ROMs, X11/Xvfb, keys injected with XTest)

| Check | Result |
| --- | --- |
| Shared layout (`controls.LAYOUT`) | One key per button for GB/GBC/GBA (integrated player), DS (DeSmuME via `ds_input_shim.c`) and 3DS (Azahar profile). Unit tests cover each translation. |
| DeSmuME 0.9.13 stock keyboard | Broken: `load_default_config` `memcpy`s a 32-bit key table into a 16-bit array. Platinum: Down closed the lid (black screens), the menu cursor never moved, and Enter didn't start. Source: `frontend/posix/shared/ctrlssdl.cpp:86`. Table confirmed in `/usr/games/desmume-cli`. |
| DeSmuME with shim, Platinum | Up/Down/Left/Right, A, B, X (menu), Start (naming → OK), Select (letter case) and touch all worked. |
| Azahar, Pokémon X | The old A key did nothing; X confirmed, Z cancelled, arrows moved the menu, Enter started from the title. The bindings survived Azahar rewriting `qt-config.ini` on exit. |
| GB in-game save, Pokémon Red | Saved from the Start menu, then a fresh core boot showed CONTINUE. |
| GB/GBC/GBA save memory, all 11 dumps | Random marker round-trips byte-exact through `cartridge.sav`; the clock games add their clock footer. |
| Player SIGTERM | Exit 143, and `cartridge.sav` was rewritten at 4 s (before the 10 s periodic flush). |
| DS in-game save, Platinum | The `.dsv` changed on disk while the game was saving. After SIGKILL and a relaunch, Continue loaded the saved bedroom. |
| 3DS save data, Pokémon X | The save archive created at first boot was byte-identical across two further launches of the same profile. |

## Nintendo 64 shared controls and categories (2026-11-24, Super Mario 64 USA, X11/Xvfb, keys injected with XTest)

| Check | Result |
| --- | --- |
| Mupen64Plus 2.6.0 input with no saved config | The log showed "Using manual config with no SDL joystick". Enter started, X opened file A, Z closed Lakitu's message, holding A (Z trigger) crouched, I (C-up) moved the camera in, W (R) switched Lakitu to Mario cam. |
| Saved Mupen config after Esc | `mupen64plus.cfg` kept the layout (`mode = 0`, A=X, B=Z, Z=A) and the Fast Forward and Gameshark hotkeys stayed unbound. F and G did nothing. |
| Catalogue tabs | Tab switched Pokémon (211 titles; 210 since 2048 was removed) and Mario (1). Unit tests cover Shift+Tab, clicks and a search carried across tabs. The Import ROM button and path entry were later removed; games are added only through the ROM folder (or Download for 2048). |
| Gamepad path | Untested on hardware: with a joystick device present, player 1 keeps Mupen's automatic gamepad setup (unit test only). |

## Super Mario 64 extended run (2026-11-25, Ubuntu Mupen64Plus 2.6.0 + Glide64mk2, Xvfb, Mesa llvmpipe software GL, 4 cores)

| Check | Result |
| --- | --- |
| Speed | 96–100% (29–30 FPS of 30) in menus, the grounds and the castle. Dips to 72–89% when foliage, water or dialogue boxes fill the screen; this is the software renderer, not a GPU. |
| In-game save (EEPROM) | Sound set to Mono on file select; the `.eep` changed on disk, kept Mono through a reset (F9), and showed Mono again after quitting and relaunching from the library. |
| Manual play | Intro, Lakitu tutorial, castle grounds, moat (surface and underwater swimming, leaving the water), castle front door, Lakitu Bros. camera scene, Bowser's welcome inside the castle, Lakitu/Mario camera, C-button camera. |
| Title-screen soak, 25 min | Process alive at all 50 samples, every frame different, no log output, RSS 400 → 445 MB in the first 5 min then flat. The attract demos did not start, so no courses were shown. |
| Random-input gameplay soak, 10 min | 777 random moves (run, jump, punch, crouch, crouch-jump, camera) around the castle entrance, the inner room and the moat. Alive at all 20 samples, every frame different, no log output, RSS flat at 447–448 MB. |
| Not covered | Entering a course painting, collecting or saving a star, boss fights, a full playthrough, sound output, and a real GPU. |

## Cover grid and "your games" view (2026-11-25, X11/Xvfb, real ROM folder)

| Check | Result |
| --- | --- |
| Default view | Pokémon 27 / Mario 1: only the 28 dumps found in `roms/`, grouped Game Boy, Game Boy Color, Game Boy Advance, Nintendo DS, Nintendo 3DS, Nintendo 64. |
| Full catalogue | C and the **Full catalogue** button both switched to 211 / 1 and kept the selected game; unowned playable releases showed *No ROM yet*, catalogue-only releases *Not playable*. |
| Navigation | Arrow keys moved across and between rows and section headings; the grid scrolled to keep the selection (and its heading) in view; mouse clicks selected tiles after scrolling; search "ultra" left the two 3DS Ultra games. |
| Covers | Generated covers rendered for every system; a picture in `<data dir>/covers/<id>.png` replaced the generated cover in the grid and the details panel, centred with its aspect ratio kept. Unit tests cover picture precedence, a broken picture falling back, and the 16 MB limit. |

## Box art (2026-11-25, X11/Xvfb, network)

| Check | Result |
| --- | --- |
| First start | All 28 covers in the collection downloaded and matched `covers-index.json` in about 12 s; the grid replaced each plain card as its art arrived. |
| Full catalogue | Art for the 52 other listed releases downloaded as they scrolled into view (80 cached in total); download-only and non-Nintendo titles kept plain cards. |
| Verification | Unit tests: a tampered download and a damaged cache file are rejected (the damaged one is fetched again), index entries outside libretro-thumbnails, over 4 MB or with a malformed digest are ignored, and `--no-cover-downloads` / unlisted games never fetch. |

## Window controls and search field (2026-11-25, X11/Xvfb without a window manager)

| Check | Result |
| --- | --- |
| Catalogue window | Real X geometry after `xdotool` drags: the header drag moved the window by exactly the pointer distance (+260, +90); the bottom-right grip shrank it by (300, 140); the left edge widened it by 250 while keeping its right side. F11, a header double-click and the full-screen button each covered the 1280×800 display and restored the previous geometry. |
| Player window (Pokémon Red, mGBA) | Title-bar drag moved it (+200, +60); the grip resized it; F11 covered the display and restored it; Escape still closed the game (exit 0). |
| Search field | Idle (placeholder and `/` hint), typing (accent border, caret) and filtered (query, match count, clear button) states rendered in the header. Unit tests: clicking a tile ends typing and keeps the filter; the clear button empties it. |
| Note | SDL's own full screen needs a window manager (without one the X window kept its size), so full screen is a borderless window the size of the display. DS, N64 and 3DS games run in their emulators' own windows, which these controls do not change. |

## macOS port (2026-11-25, prepared on Windows; not yet run on a Mac)

The macOS code and both apps were built and checked on the Windows PC; nothing has run on macOS yet. Choices were made from the emulators' sources and release files:

| Check | Result |
| --- | --- |
| Emulator releases | melonDS 1.1 (universal, signed, no outside libraries), ares v148 (universal, signed), Azahar 2127.0.1 (arm64 and x86_64 builds, signed, macOS 13.4+), the buildbot mGBA core (arm64 signed; x86_64). Mupen64Plus 2.6.0's macOS bundle was rejected: Intel only, unsigned, and it loads SDL2, libpng, FreeType and libsamplerate from a Homebrew install in `/usr/local/opt`. |
| Emulator behaviour, from their sources | melonDS reads its settings from a `portable` folder beside `melonDS.app` and starts with no keyboard mapping; on macOS, Qt reports arrow keys with the keypad modifier and melonDS marks the right Shift key with bit 31. ares takes `--settings-file`, has no default key bindings, names keys by their index in its Quartz keyboard list, and writes saves beside the game. Azahar for macOS uses a `user` folder in its working directory (portable mode). |
| Apps | `tools/build_macos.py` built both zips (238 MB and 226 MB) and its checks passed: required files and permissions, every Mach-O (about 160 per app) contains the app's architecture, all arm64 code is signed, every symlink resolves, bytecode matches Python 3.12. Python 3.12.16 (python-build-standalone) has libpython and SSL built in, so it runs from `Contents/MacOS`; no extension links the separate libpython. pygame-ce 2.5.7's wheel is universal2 and signed. |
| Unit tests (on Windows) | 174 run, 165 passed, 9 skipped. The melonDS, ares and Azahar macOS code paths ran with stand-in programs, including a fake `melonDS.app` bundle, and with the platform switched to macOS for the DS, N64 and 3DS launch paths. |
| To check on the Mac | `tests/smoke_macos.py` (from `setup.command`) and `tests/smoke_macos.py --app` for each app: windows open, games keep running, saves land in `saves/<game>/`. Then by hand: the first-open approval, keys in melonDS (arrows with the keypad modifier, right Shift), ares, Azahar; whether macOS asks for Input Monitoring for ares; the library window on a Retina display; Control-Command-F full screen. |

## Windows port (2026-11-25, Windows 11, Python 3.12.10, pygame-ce 2.5.7 / SDL 2.32.10, 3840×2160 display at 150%)

Emulators installed by `setup.cmd`: the libretro buildbot's mGBA core (GBA savestate format v11), DeSmuME 0.9.13 x64, Mupen64Plus 2.6.0 and Azahar 2127.0.1 (MSVC build).

| Check | Result |
| --- | --- |
| Unit tests | 152 run: 143 passed, 9 skipped. Skipped: 5 that need symlinks (Windows allows them only in Developer Mode or for administrators; junction variants of the link checks do run), 3 Linux-only (Dolphin's X11 frontend, the DeSmuME keyboard shim), 1 FIFO. Emulator stand-ins are real `.exe` files (pip's launcher stub plus a Python zip). |
| mGBA core | All core tests pass against the buildbot DLL, including SRAM, the MBC3 clock (Gold/Silver/Crystal) and the GBA cartridge clock (Ruby/Sapphire/Emerald), whose savestate fields are at the same offsets in format v11 as in v7. |
| ROM folder | All 28 of the owner's dumps matched the catalogue; the first scan (about 25 GB) took 3.6 s, a cached rescan 0.00 s. |
| Real launches (`tests/smoke_windows.py`, Play's own worker path) | Pokémon Red (GB), Emerald (GBA), Platinum and Black (DS), Super Mario 64 (N64) and Pokémon X (3DS) opened their windows within 2 s and were running after boot: Red's title, Emerald's intro, Black's intro, Mario's title head, and X's language menu at 100% speed. The mGBA player, DeSmuME and Mupen64Plus closed on a window close request with exit 0. Azahar asks for confirmation, so it was force closed. |
| Save locations | `cartridge.sav` written on exit (Emerald: 131,088 bytes, flash plus the 16-byte clock footer); DeSmuME's `.dsv` in `saves\<game>\desmume\`, the same place as on Linux; Mupen's `.eep` in `saves\<game>\`; Azahar's data entirely in `saves\<game>\azahar\<game>\user\` (portable mode); no files in `%APPDATA%` or `%LOCALAPPDATA%` outside Retro Pocket's folder. |
| Library window | Catalogue drawn at 1260×930 pixels for an 840×620-point window; all 28 covers downloaded and verified; Play showed "Playing Pokémon Crystal…" after 4 s; Force close needed a second click and reported "Emulator exited (force closed)". `RetroPocket.cmd` opened it without a console and it closed cleanly. |
| Force close | Ends the worker and the emulator it started (job object), covered by a unit test that checks the grandchild process is gone. |
| Found and handled | Windows DeSmuME ignores the settings folder beside it when its program is under `%TEMP%` (it uses `%LOCALAPPDATA%\DeSmuME`); Retro Pocket's data folder is outside `%TEMP%`, and a launch-log warning covers `--data-dir` there. DeSmuME's default 1× window was too small on a 4K display, so each game's settings start at 2×. |
| Not tested on Windows | Keyboard and gamepad input inside DeSmuME, Mupen64Plus and Azahar (their key settings use the same formats as on Linux, where they were verified); in-game saving beyond the files created at boot; Dolphin and PokeMini (not installed, no dumps); the X11 smoke scripts (`smoke_*.py`, `x11_mgba_smoke.py`), which are Linux only. |

