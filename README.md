# Retro Pocket

A game library and player for Pokémon and Mario games, for Windows and Linux.

The catalogue opens on **your games**: everything found in your ROM folder, shown as a grid of covers grouped by system (Game Boy, Game Boy Color, Game Boy Advance, Pokémon mini, DS, 3DS, Nintendo 64, GameCube). Click **Full catalogue** or press C to also see every catalogued release, including ones you don't have yet (marked *Not owned*) and ones that can't be played here (*Not playable*). Start with `--all` to open on the full catalogue.

- **Browse:** arrow keys move around the grid; the mouse wheel scrolls; click a cover to select it. Enter (or **Play**) starts the selected game in a separate window.
- **Series:** the **Pokémon** and **Mario** tabs (with how many games each shows) split the collection; click one or press Tab (Shift+Tab goes back). A catalogue entry's optional `series` field picks its tab; entries without one are Pokémon.
- **Search:** click the search field or press `/` to search the current tab by title, platform or release year (a year needs at least three digits, such as `199` or `2013`). Enter or a click elsewhere finishes typing and keeps the filter; the field shows how many games match. Esc or the × button clears it. A search stays active when you switch tabs or views.

### Covers

Covers are the games' real box art from [libretro-thumbnails](https://github.com/libretro-thumbnails) (RetroArch's box art collection). `covers-index.json` lists, for every release that has a box, the exact file at a pinned commit with its size and SHA-256. Retro Pocket downloads that file the first time the cover is shown (your own games first), keeps it only if it matches, and caches it in `covers/downloaded/` in the data directory. Nothing else is fetched. Start with `--no-cover-downloads` to stay offline.

Releases without a box (download-only eShop and Virtual Console titles, Switch, mobile and arcade games) and covers that haven't downloaded yet show a plain card with the system and title.

To use your own picture instead (PNG or JPEG, up to 16 MB), save it either:

- as `covers/<game id>.png` (or `.jpg`) in the data directory. Game IDs are the `id` fields in the `catalog*.json` files; or
- next to the ROM, with the same name: `roms/Pokemon/Pokemon - Red Version (USA, Europe) (SGB Enhanced).png`.

Your pictures win over downloaded art; restart Retro Pocket to pick up new ones. `tools/build_cover_index.py` regenerates the index (see `SOURCES-COVERS.md`).

## Run on Windows

1. Install Python 3.11 or newer from <https://www.python.org/downloads/windows/> (3.12 recommended).
2. Double-click **`setup.cmd`**. It creates `.venv`, installs pygame-ce, and downloads the emulators into `emulators\`:

   | Systems | Emulator |
   | --- | --- |
   | Game Boy, Game Boy Color, Game Boy Advance | mGBA libretro core (`emulators\mgba\mgba_libretro.dll`), played in Retro Pocket's own window |
   | Nintendo DS | DeSmuME 0.9.13 |
   | Nintendo 64 | Mupen64Plus 2.6.0 |
   | Nintendo 3DS | Azahar 2127.0.1 |

   Each archive is an official release, checked against a pinned size and SHA-256 before it is unpacked. The mGBA core has no pinned release: it comes from the libretro buildbot's current Windows build, is checked to be a 64-bit Windows DLL, and its SHA-256 is printed. Nothing else is downloaded: no ROMs, BIOS or firmware files, or console keys. Run `setup.cmd` again to repair the installation; `setup.cmd --force` downloads everything again, and `setup.cmd --mgba-core C:\path\mgba_libretro.dll` uses a core you already have.
3. Put your dumps in `roms\` (see Playing) and start **`RetroPocket.cmd`**. It opens the library without a console window. To see diagnostics, run `.venv\Scripts\python app.py` from a terminal instead. The same options work with both, for example `RetroPocket.cmd --all`.

Library data, saves and logs are stored in `%LOCALAPPDATA%\RetroPocket`; `--data-dir` overrides the location (choose one outside `%TEMP%`: Windows DeSmuME ignores its settings folder when it runs from there). When started from `RetroPocket.cmd`, the library's own messages go to `logs\retro-pocket.log` there.

Besides `emulators\`, each emulator is found in its usual folder under Program Files. Otherwise, set `RETRO_POCKET_CORE` (the mGBA `.dll`), `RETRO_POCKET_DESMUME`, `RETRO_POCKET_MUPEN64PLUS`, `RETRO_POCKET_AZAHAR`, `RETRO_POCKET_DOLPHIN` or `RETRO_POCKET_POKEMINI` to the absolute path of a trusted `.exe`. PATH is never searched.

GameCube, Wii and Pokémon mini emulators are not installed by `setup.cmd`. For GameCube and Wii, extract the Windows build of Dolphin from <https://dolphin-emu.org/download/> so that `emulators\dolphin\Dolphin.exe` exists. For Pokémon mini, put PokeMini's Windows build in `emulators\pokemini\PokeMini.exe`.

Some things work differently on Windows:

- **A copy of the emulator for each game.** Windows DeSmuME and Azahar keep their settings next to their program, and they have no option to keep them elsewhere. Each DS and 3DS game therefore runs its own copy of the emulator, placed in its save folder and made of hard links, so it takes no disk space. A real copy is made only when the data folder is on a different drive from `emulators\`. That is what keeps each game's settings and saves separate, as on Linux. After you update an emulator, each game's copy is refreshed the next time it starts.
- **Display scaling.** Retro Pocket's windows draw at the display's full resolution under Windows display scaling (125%, 150% and so on). To have Windows stretch them instead, set `SDL_WINDOWS_DPI_AWARENESS=unaware`.
- **Force close** ends the game's whole process tree: the worker, Retro Pocket's GB/GBA player, and the emulator.

## Run on Ubuntu

Open a terminal inside a graphical desktop session:

```sh
sudo apt install libretro-mgba desmume python3-venv
cd /home/bonquifo/projects/retro-pocket
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

If mGBA is installed in a nonstandard location, pass `--core /path/to/mgba_libretro.so` (trusted local core only). Library data and per-game cartridge saves are stored under your XDG data directory by default; `--data-dir` overrides the location.

For Nintendo 64 and GameCube support, install the additional Ubuntu packages:

```sh
sudo apt install mupen64plus-ui-console mupen64plus-video-glide64mk2 dolphin-emu
```

For Nintendo 3DS support, install Azahar's OpenGL dependency and the official Linux AppImage from <https://github.com/azahar-emu/azahar/releases> (check the published SHA-256), saved as `~/Applications/azahar.AppImage`:

```sh
sudo apt install libopengl0
chmod +x ~/Applications/azahar.AppImage
```

Retro Pocket also finds `azahar` in `/usr/bin`, `/usr/games`, `/usr/local/bin` or `~/.local/bin`, or you can set `RETRO_POCKET_AZAHAR` to the absolute path of a trusted Azahar executable. Retro Pocket does not download Azahar, firmware or keys for you.

For Pokémon mini, install the native SDL2 build of [PokeMini](https://github.com/gameblabla/pokemini/tree/6ce9b614bd99c69311f12fa831fc2ad380b4a19f). With `build-essential`, `libsdl2-dev`, and `zlib1g-dev` installed, build from that checkout with `make -C platform/sdl2`, then set `RETRO_POCKET_POKEMINI` to the absolute path to `platform/sdl2/PokeMini` before launching Retro Pocket. The app does not install emulator binaries, system firmware or keys on your behalf.

## Playing

Put your own raw dumps (`.gb`, `.gbc`, `.gba`, `.nds`, `.z64`, `.min`, uncompressed GameCube `.iso`, or decrypted Nintendo 3DS `.3ds`) anywhere under the `roms/` folder next to `app.py`. Subfolders such as `roms/Pokemon/` are fine. To use another folder, pass `--roms-dir /path/to/roms` or set `RETRO_POCKET_ROMS`. When the app opens, it checks that folder in the background and matches each file to a game by its exact size and hash, so file names don't matter. Matched games show **Ready to play**. Select one and choose **Play**; nothing is copied into the data directory.

The first check reads every candidate file once, which takes a few minutes for large 3DS images. The results are cached in `rom-index.json` in the data directory, and later starts only re-read files that have changed. Every launch still re-checks the game's bytes before the emulator starts.

The ROM folder is the only way to add a game; to play a dump stored somewhere else, copy or link it into that folder. The app does not unpack ZIPs. At launch, the game file is checked by reading it once, 1 MB at a time, and the emulator gets a hard link to the checked file rather than a copy. Neither step loads the game into Retro Pocket's memory or uses extra disk space. Linking falls back to a copy only if your data directory is on a different filesystem (on Windows, a different drive) from the ROM. Large 3DS images take a few seconds to check. Retro Pocket never downloads ROMs: nothing is included, searched for online, or fetched. The only thing it downloads is box art (see Covers).

## Controls

Game Boy, Game Boy Color, Game Boy Advance, Nintendo DS, Nintendo 3DS and Nintendo 64 games all use the same keys:

| Button | Key | Notes |
| --- | --- | --- |
| D-pad | Arrow keys | On 3DS and N64 the arrows drive the analog stick (the 3DS circle pad, which every 3DS Pokémon game walks with; Sun and Moon ignore the D-pad). The 3DS and N64 D-pad is on T / F / G / H |
| A / B | X / Z | |
| X / Y (DS, 3DS) | S / A | |
| Z trigger (N64) | A | The N64 has no Y button, so Z takes its key: hold it with the left hand while pressing A or B |
| L / R (GBA, DS, 3DS, N64) | Q / W | |
| ZL / ZR (3DS) | 1 / 2 | 3DS C-stick and N64 C buttons: I / J / K / L |
| Start / Select | Enter / Right Shift | Azahar can't tell the Shift keys apart, so either Shift works as Select on 3DS. The N64 has no Select |
| Touchscreen (DS, 3DS) | Mouse on the lower screen | |
| Leave the game | Esc | N64, and DS on Linux: Esc quits the emulator. DS on Windows: close DeSmuME's window. 3DS: close the window or press Ctrl+Q, then choose Yes when Azahar asks to exit |

The integrated Game Boy player also has clickable on-screen buttons, and the middle and right mouse buttons press A and B.

- **Nintendo DS on Windows:** DeSmuME's own default keys are exactly the layout above, so nothing is changed. Each DS game has its own DeSmuME settings (`saves\<game>\desmume\desmume.ini`), so changes under Config → Control Config apply to that game. The window starts at 2× (View → Window Size changes it), and DeSmuME is resizable.
- **Nintendo DS on Linux:** Ubuntu's `desmume-cli` 0.9.13 scrambles its own keyboard table and ignores its config file. Down closes the lid, Enter presses Up, and B, Start, L, Y, Left and Down can't be pressed. Retro Pocket works around this by preloading a small input shim (`ds_input_shim.c`) that turns the keys above into the gamepad events DeSmuME handles correctly. Other keys, such as Esc and the F1–F10 save-state keys, pass through unchanged. The shim is compiled once with `/usr/bin/cc` (install `build-essential`) and cached under `saves/.ds-input/`. Without a compiler, the launch log shows a warning and a gamepad still works.
- **Nintendo 3DS:** the first time a game launches, Retro Pocket writes these keys into that game's Azahar profile. Changes you make later in Azahar under Emulation → Configure → Controls are kept. Each 3DS game keeps its own Azahar profile (settings, save data and extra data) under `saves/<game>/azahar/` in the data directory; on Windows the profile's data is in `saves\<game>\azahar\<game>\user\`. Only decrypted `.3ds` dumps whose exact bytes are listed in `catalog-azahar.json` are accepted; encrypted dumps and `.cia` packages are not supported.
- **Nintendo 64:** Retro Pocket passes these keys to Mupen64Plus every time a game starts. The console build has no controls screen, so there are no in-emulator changes to keep. It also turns off Mupen's Fast Forward (F) and Gameshark (G) hotkeys, which would otherwise fire with the D-pad. When a gamepad is connected (on Windows, any controller the Windows joystick API sees; on Linux, a `/dev/input/by-id/*-event-joystick` device), player 1 uses Mupen's automatic gamepad setup instead. A keyboard can't tilt the stick part-way, so Mario always runs rather than walks.
- **Other systems:** PokeMini and Dolphin keep their own controller mappings. PokeMini maps A to X. On Linux, Dolphin prefers its X11 frontend when available. Game-specific motion, microphone, Transfer Pak, GameCube–GBA link, and online features are not verified.

## Window size and audio

The catalogue and Retro Pocket's mGBA window can be moved, resized and made full screen, with or without a desktop window manager (on a bare X server or over VNC, too):

- **Move:** drag the top bar (the header around the title, or the game's title bar).
- **Resize:** drag any edge, or the grip in the bottom-right corner. Your desktop's own window borders and maximize button work as well.
- **Full screen:** F11, the full-screen button (top right) or a double-click on the top bar. The same again returns to the previous size and position.

The catalogue scales its layout to fit, and the handheld player fits the game image without stretching it. Mouse buttons stay aligned with the displayed controls. The mGBA player continues without sound when it can't initialize an audio device.

External emulators, including Azahar, manage their own windows and audio. Ubuntu's `desmume-cli` uses a fixed window size chosen at launch; it does not implement live resize. The Windows DeSmuME window can be resized. Native PokeMini allows resizing but can stretch the game in a non-proportional window. The Retro Pocket window scaling does not change either emulator's behavior.

## Saves

Use the game's own save menu. Every save is kept per game under `saves/<game>/` in the data directory, so it doesn't depend on where the ROM came from (the ROM folder or a copy kept in the data directory):

- **Game Boy, Game Boy Color, Game Boy Advance:** `cartridge.sav`, including the clock for Gold, Silver, Crystal, Ruby, Sapphire and Emerald. The player writes it every 10 seconds, when you leave the game, and when the system asks it to quit (logout or shutdown).
- **Nintendo DS:** `desmume/<game>.dsv`. DeSmuME writes it as soon as the game saves.
- **Nintendo 3DS:** inside the game's Azahar profile. Azahar writes it as soon as the game saves.
- **Nintendo 64:** Mupen64Plus's own save file (for Super Mario 64, an `.eep` EEPROM file) beside `mupen64plus.cfg`.

Save states (the emulators' own snapshot features) are not managed by Retro Pocket.

### Moving saves between Linux and Windows

The save files have the same formats on both systems. Copy them from `~/.local/share/retro-pocket/saves/` on Linux to `%LOCALAPPDATA%\RetroPocket\saves\` on Windows (or back), with the game closed:

- Game Boy, Game Boy Color, Game Boy Advance: `<game>/cartridge.sav`.
- Nintendo DS: `<game>/desmume/<game>.dsv`.
- Nintendo 64: the `.eep` (or `.sra`, `.fla`, `.mpk`) file in `<game>/`.
- Nintendo 3DS: the Azahar data folders. Linux keeps them in `<game>/azahar/<game>/data/azahar-emu/`, Windows in `<game>\azahar\<game>\user\`. Copy the `sdmc` and `nand` folders between them.

Emulators run in separate processes, so an emulator crash does not close the library. Close an emulator normally to let it finish saving; closing the library does not force the game to quit. If an emulator freezes, use **Force close** and confirm the warning about unsaved progress. If a game fails to launch or crashes, use **Copy log path** to locate the diagnostic log. Saves and launch logs are kept separately under `saves/` and `logs/` inside the app's data directory.

## Verification and limitations

Only listed variants of playable titles are accepted: every file is checked against its exact catalogued size and SHA-1 or SHA-256 digest before play. A successful digest match checks identity and integrity, not the absence of emulator bugs. Keep the distro’s emulators up to date. See `SOURCES*.md` for catalogue provenance and omissions and `QA.md` for the resize and gameplay test scope. Catalogue entries do not imply that a title was played through or that its external services still work.

To run the tests:

```sh
.venv/bin/python -m unittest discover -s tests -v       # Linux
.venv\Scripts\python -m unittest discover -s tests -v    # Windows
```

On Windows, `tests\smoke_windows.py OUTPUT_DIR [GAME_ID ...]` starts real games from your ROM folder the way Play does, captures each emulator's window to a PNG and closes it again.
