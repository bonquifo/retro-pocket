# Retro Pocket

[![Build and verify](https://github.com/bonquifo/retro-pocket/actions/workflows/build.yml/badge.svg)](https://github.com/bonquifo/retro-pocket/actions/workflows/build.yml)

A game library and player for Pokémon and Mario games, for Linux, Windows and macOS (Apple Silicon and Intel).

## Downloads

Download the latest version from the [Releases page](https://github.com/bonquifo/retro-pocket/releases/latest). Once installed, it updates itself (see Updates). Every push to `main` also builds and checks all four versions on GitHub Actions; those builds are under **Artifacts** on each run of the [Actions page](https://github.com/bonquifo/retro-pocket/actions/workflows/build.yml) for two weeks.

| Version | File | To start |
| --- | --- | --- |
| Windows (64-bit) | `Retro-Pocket-Windows.zip` | Unzip anywhere and double-click **Retro Pocket.cmd**. Everything is included: Python and the emulators. Put dumps in its `roms` folder |
| Linux (x86_64) | `Retro-Pocket-Linux.tar.gz` | Unpack, install the emulators from your distribution (see Run on Ubuntu), run `./setup.sh`, then `./RetroPocket.sh` |
| macOS, Apple Silicon | `Retro-Pocket-macOS-Apple-Silicon.zip` | See Run on macOS |
| macOS, Intel | `Retro-Pocket-macOS-Intel.zip` | See Run on macOS |

No version includes or downloads games. To build them yourself, run `tools/build_windows.py`, `tools/build_linux.py` or `tools/build_macos.py` (each runs on any OS and writes to `dist/`). `tools/verify_build.py` then checks a build from the inside with its own Python, as CI does: the mGBA core emulating a test cartridge, each emulator found and built for the right CPU, box art over HTTPS, and on macOS and Windows the emulators starting.

The catalogue opens on **your games**: everything found in your ROM folder, shown as a grid of covers grouped by system (Game Boy, Game Boy Color, Game Boy Advance, Pokémon mini, DS, 3DS, Nintendo 64, GameCube). Click **Full catalogue** or press C to also see every catalogued release, including ones you don't have yet (marked *Not owned*) and ones that can't be played here (*Not playable*). Start with `--all` to open on the full catalogue.

- **Browse:** arrow keys move around the grid; the mouse wheel scrolls; click a cover to select it. Enter (or **Play**) starts the selected game in a separate window.
- **Series:** the **Pokémon** and **Mario** tabs (with how many games each shows) split the collection; click one or press Tab (Shift+Tab goes back). A catalogue entry's optional `series` field picks its tab; entries without one are Pokémon.
- **Search:** click the search field or press `/` to search the current tab by title, platform or release year (a year needs at least three digits, such as `199` or `2013`). Enter or a click elsewhere finishes typing and keeps the filter; the field shows how many games match. Esc or the × button clears it. A search stays active when you switch tabs or views.

### Covers

Covers are the games' real box art from [libretro-thumbnails](https://github.com/libretro-thumbnails) (RetroArch's box art collection). `covers-index.json` lists, for every release that has a box, the exact file at a pinned commit with its size and SHA-256. Retro Pocket downloads that file the first time the cover is shown (your own games first), keeps it only if it matches, and caches it in `covers/downloaded/` in the data directory. Start with `--no-cover-downloads` to fetch no box art. Apart from box art, the downloadable builds only contact GitHub to look for updates (see Updates).

Releases without a box (download-only eShop and Virtual Console titles, Switch, mobile and arcade games) and covers that haven't downloaded yet show a plain card with the system and title.

To use your own picture instead (PNG or JPEG, up to 16 MB), save it either:

- as `covers/<game id>.png` (or `.jpg`) in the data directory. Game IDs are the `id` fields in the `catalog*.json` files; or
- next to the ROM, with the same name: `roms/Pokemon/Pokemon - Red Version (USA, Europe) (SGB Enhanced).png`.

Your pictures win over downloaded art; restart Retro Pocket to pick up new ones. `tools/build_cover_index.py` regenerates the index (see `SOURCES-COVERS.md`).

## Run on Windows

The simplest way is the `Retro-Pocket-Windows.zip` download (see Downloads): nothing to install. To run from this folder instead:

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

## Run on macOS

Retro Pocket for macOS comes as two apps:

| App | For | Needs |
| --- | --- | --- |
| **Retro Pocket (Apple Silicon)** | Macs with an M-series chip | macOS 11 or later |
| **Retro Pocket (Intel)** | Intel Macs (also runs on Apple Silicon under Rosetta) | macOS 10.15 or later |

Each app is self-contained: Python, pygame-ce and the emulators for that kind of Mac are inside it. Nothing needs to be installed first.

| Systems | Emulator in the app |
| --- | --- |
| Game Boy, Game Boy Color, Game Boy Advance | mGBA libretro core, built for that Mac, played in Retro Pocket's own window |
| Nintendo DS | melonDS 1.1 (universal) |
| Nintendo 64 | ares v148 (universal; macOS 11 or later) |
| Nintendo 3DS | Azahar 2127.0.1, built for that Mac (macOS 13.4 or later) |

1. Build the apps on any computer with this folder and Python 3.11 or newer: `python tools/build_macos.py` (on Windows, `.venv\Scripts\python tools\build_macos.py`). This writes `dist/Retro-Pocket-macOS-Apple-Silicon.zip` and `dist/Retro-Pocket-macOS-Intel.zip`, about 230 MB each, and checks every program inside them. The archives are pinned by size and SHA-256 like the Windows ones; the mGBA core is the libretro buildbot's current build. `--arch arm64` or `--arch x86_64` builds just one.
2. Copy the zip to the Mac, double-click it, and move the app to Applications.
3. The apps aren't signed with an Apple developer ID, so macOS blocks the first start. Open the app once, then go to System Settings → Privacy & Security and choose **Open Anyway** (on macOS 14 and earlier, Control-click the app and choose Open). After that it starts normally. The app then lifts macOS's download quarantine from the emulators inside it, so they don't each ask too.
4. Put your dumps in **`~/Retro Pocket/roms`** (in your home folder; the app creates it). Library data, saves and logs are in `~/Library/Application Support/RetroPocket`, and the library's messages go to `logs/retro-pocket.log` there.

To run from this folder instead (for development), double-click **`setup.command`**. It downloads a pinned Python for this Mac into `.python`, creates `.venv`, installs pygame-ce and puts the emulators in `emulators/`. Then double-click **`RetroPocket.command`**, which runs the library from Terminal with its messages shown; dumps go in `roms/` as on the other systems. As on Windows, `RETRO_POCKET_CORE`, `RETRO_POCKET_MELONDS`, `RETRO_POCKET_ARES`, `RETRO_POCKET_AZAHAR`, `RETRO_POCKET_DOLPHIN` and `RETRO_POCKET_POKEMINI` can name an emulator elsewhere (an `.app` or the program inside it). Without them, `emulators/` and `/Applications` are searched.

GameCube, Wii and Pokémon mini emulators are not included. Dolphin is found as `Dolphin.app` in `/Applications`. PokeMini has no macOS release; a build of your own is found in `emulators/pokemini/` or Homebrew's `bin` folder.

Some things work differently on macOS:

- **Nintendo DS runs in melonDS**, not DeSmuME, because DeSmuME's macOS app can't be started on a game and supervised. Retro Pocket gives melonDS the same keys (melonDS has no keyboard layout of its own). Each game runs its own linked copy of melonDS with its settings in `saves/<game>/melonds/portable/`; Config → Input changes apply to that game. Saves are melonDS `.sav` files next to the game in `saves/<game>/`, not DeSmuME `.dsv` files; converting between them isn't covered here. View → Screen size changes the window size.
- **Nintendo 64 runs in ares**: Mupen64Plus has no macOS build that works without Homebrew. The keys are the same as on the other systems, Esc quits as with Mupen64Plus, and each game has its own ares settings (`saves/<game>/ares/settings.bml`). ares doesn't set up a gamepad automatically: assign one under Settings → Input, and it is kept for that game. Its saves are ares's own files next to the game.
- **Nintendo 3DS**: each game's Azahar data is in `saves/<game>/azahar/<game>/user/`, as on Windows.
- **Full screen** uses macOS's own full screen: Control-Command-F or the full-screen button (F11 shows the desktop on a Mac).
- **Leaving a game**: Esc in Game Boy, Game Boy Advance and N64 games; Command-Q in melonDS and Azahar (Azahar asks to confirm).

## Run on Ubuntu

Open a terminal inside a graphical desktop session:

```sh
sudo apt install libretro-mgba desmume python3-venv
cd /home/bonquifo/projects/retro-pocket
./setup.sh          # creates .venv with pygame-ce and names any missing emulator packages
./RetroPocket.sh    # or: .venv/bin/python app.py
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

The ROM folder is the only way to add a game; to play a dump stored somewhere else, copy or link it into that folder. The app does not unpack ZIPs. At launch, the game file is checked by reading it once, 1 MB at a time, and the emulator gets a hard link to the checked file rather than a copy. Neither step loads the game into Retro Pocket's memory or uses extra disk space. Linking falls back to a copy only if your data directory is on a different filesystem (on Windows, a different drive) from the ROM. Large 3DS images take a few seconds to check. Retro Pocket never downloads ROMs: nothing is included, searched for online, or fetched. It downloads only box art (see Covers) and its own updates (see Updates).

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
| Leave the game | Esc | N64, and DS on Linux: Esc quits the emulator. DS on Windows: close DeSmuME's window. DS on macOS: Command-Q. 3DS: close the window or press Ctrl+Q (Command-Q on a Mac), then choose Yes when Azahar asks to exit |

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

### Moving saves between Linux, Windows and macOS

Linux and Windows use the same emulators, so their save files have the same formats. Copy them from `~/.local/share/retro-pocket/saves/` on Linux to `%LOCALAPPDATA%\RetroPocket\saves\` on Windows (or back), with the game closed. On macOS (`~/Library/Application Support/RetroPocket/saves/`) the Game Boy, Game Boy Advance and 3DS saves are the same files; DS and N64 saves come from different emulators there (see Run on macOS).

- Game Boy, Game Boy Color, Game Boy Advance: `<game>/cartridge.sav`.
- Nintendo DS: `<game>/desmume/<game>.dsv`.
- Nintendo 64: the `.eep` (or `.sra`, `.fla`, `.mpk`) file in `<game>/`.
- Nintendo 3DS: the Azahar data folders. Linux keeps them in `<game>/azahar/<game>/data/azahar-emu/`, Windows and macOS in `<game>/azahar/<game>/user/`. Copy the `sdmc` and `nand` folders between them.

Emulators run in separate processes, so an emulator crash does not close the library. Close an emulator normally to let it finish saving; closing the library does not force the game to quit. If an emulator freezes, use **Force close** and confirm the warning about unsaved progress. If a game fails to launch or crashes, use **Copy log path** to locate the diagnostic log. Saves and launch logs are kept separately under `saves/` and `logs/` inside the app's data directory.

## Updates

The downloadable Windows, macOS and Linux versions keep themselves up to date. At most once a day, when the library opens, it asks GitHub for the latest release of this repository. If that is newer, an **Update to 1.2.0** button appears at the bottom right:

1. Clicking it downloads this version's file from the release. The file is accepted only if its size and SHA-256 match what GitHub publishes for it, and it is unpacked next to the installation and checked to be the expected version for the same system.
2. **Restart to update** closes the library. A small helper (PowerShell on Windows, a shell script on macOS and Linux) puts the installed version aside, moves the new one into place, carries your `roms` folder over (on Linux also `.venv`, then reruns `setup.sh`), deletes the old version and opens the library again. If any step fails, the installed version is put back.
3. The next start shows whether the update worked. The helper's log is `logs/update.log` in the data directory.

Saves, settings, box art and the ROM index live in the data directory, which updates never touch. A copy that can't replace itself (in a read-only folder, or opened on macOS straight from the download without moving it to Applications) opens the release page instead. From a terminal, `app.py --update` installs the newest release without opening the library, and `app.py --version` shows the version. To turn the daily check off, start with `--no-update-check` or set `RETRO_POCKET_NO_UPDATE_CHECK=1`. A source checkout (this folder run with `RetroPocket.cmd`, `.command` or `.sh`) doesn't update itself: use `git pull`.

Updates trust GitHub and this repository: whoever can publish a release here can update every copy. Keep the GitHub account behind two-factor authentication.

## Development and releases

`.github/workflows/build.yml` builds and checks all four versions on every push to `main`, on every pull request, and every Monday, to catch changes in the emulators and in GitHub's machines. A quick version and lint job runs first. Then, on Windows, Linux, macOS on Apple Silicon and macOS on Intel, each job:

1. sets up from source with that system's own setup script and runs the unit tests;
2. builds the version. It reports its version from git: `1.2.0` on a release tag, `1.2.0-3-gabc1234` three commits later;
3. unpacks the build and checks it from the inside with its own Python (`tools/verify_build.py`);
4. installs an older copy of the build and lets it update itself to the new one, as a user's copy would (`tools/check_update.py`).

The builds are kept as artifacts for two weeks. Dependabot opens weekly pull requests for newer GitHub Actions and Python packages, and each one goes through the same checks. `requirements.txt` is the one place Python packages are pinned: the setup scripts install from it, the Windows and macOS builds fetch the same versions' wheels from PyPI (checked against PyPI's SHA-256, as pip checks them), and the checks fail if a build carries any other pygame-ce. Merging a Dependabot bump is all it takes to ship a new version in the next release.

To release a version, either:

- on the Actions tab, open **Build, check and release**, choose **Run workflow**, and enter the version (such as `1.2.0`); or
- push a tag: `git tag v1.2.0`, then `git push origin v1.2.0`.

The release is published, with the four builds, a `SHA256SUMS` file and notes listing the changes, only if every check passed. Within a day, installed copies offer the update.

### Signing the Mac apps

With an Apple Developer Program membership, CI signs both Mac apps with your Developer ID and has Apple notarize them (`tools/sign_macos.py`), so macOS opens them without asking. Every program and library inside is signed with the hardened runtime, including the emulators. Without the secrets below, the apps are built unsigned, as are pull requests from forks and Dependabot, which get no secrets. The checks then confirm that the app is notarized with the ticket stapled, that Gatekeeper accepts it, and that the signature survives an update.

1. **A Developer ID Application certificate.** On your Mac, open Keychain Access and choose **Keychain Access → Certificate Assistant → Request a Certificate From a Certificate Authority**. Enter your email, choose **Saved to disk**, and save the file. At [developer.apple.com → Certificates](https://developer.apple.com/account/resources/certificates/list), click **+**, choose **Developer ID Application**, and upload that file. Only the account holder can make one. Download the certificate and double-click it to add it to your keychain. If you already have one, it is under **My Certificates** in Keychain Access as "Developer ID Application: …".
2. **Export it with its key.** In Keychain Access, under **My Certificates**, right-click it, choose **Export**, save it as a `.p12` file, and set a password.
3. **An App Store Connect API key for notarization.** In [App Store Connect](https://appstoreconnect.apple.com/access/integrations/api), open **Users and Access → Integrations → App Store Connect API** (the first time, the account holder clicks **Request Access**). Under **Team Keys**, click **+** and give the key the **Developer** role. Download the `.p8` file (Apple offers it only once), and note its **Key ID** and the **Issuer ID** shown above the list.
4. **Add five repository secrets.** On GitHub, go to the repository's **Settings → Secrets and variables → Actions → New repository secret**. In Terminal, `pbcopy` copies a file for pasting:

   | Secret | Value |
   |---|---|
   | `MACOS_CERTIFICATE_P12` | the `.p12` in base64: `base64 -i Certificates.p12 \| pbcopy` |
   | `MACOS_CERTIFICATE_PASSWORD` | the password from step 2 |
   | `NOTARY_KEY` | the `.p8` file's text: `pbcopy < AuthKey_XXXXXXXXXX.p8` |
   | `NOTARY_KEY_ID` | the Key ID |
   | `NOTARY_ISSUER_ID` | the Issuer ID |

   Then delete the `.p12` and `.p8` files from your Mac. The certificate stays in your keychain, and you can make a new key anytime.

A Developer ID signature carries the certificate's name: your name, or your organization's. Anyone can read it from a downloaded app. To sign on your own Mac instead, save the notarization credentials once with `xcrun notarytool store-credentials retro-pocket`, then run `python tools/sign_macos.py dist/Retro-Pocket-macOS-Apple-Silicon.zip --identity "Developer ID Application: …" --notary-profile retro-pocket`.

## Verification and limitations

Only listed variants of playable titles are accepted: every file is checked against its exact catalogued size and SHA-1 or SHA-256 digest before play. A successful digest match checks identity and integrity, not the absence of emulator bugs. Keep the distro’s emulators up to date. See `SOURCES*.md` for catalogue provenance and omissions and `QA.md` for the resize and gameplay test scope. Catalogue entries do not imply that a title was played through or that its external services still work.

To run the tests:

```sh
.venv/bin/python -m unittest discover -s tests -v       # Linux
.venv\Scripts\python -m unittest discover -s tests -v    # Windows
```

On Windows, `tests\smoke_windows.py OUTPUT_DIR [GAME_ID ...]` starts real games from your ROM folder the way Play does, captures each emulator's window to a PNG and closes it again. On macOS, `.venv/bin/python tests/smoke_macos.py [GAME_ID ...]` does the same for this folder's setup, checking that each emulator opens a window and keeps running; with `--app "/Applications/Retro Pocket (Intel).app"` it tests a built app with its own Python and emulators (the Intel app under Rosetta on an Apple Silicon Mac).
