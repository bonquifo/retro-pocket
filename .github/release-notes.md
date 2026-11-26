A game library and player for Pokémon and Mario games. Bring your own game dumps: none are included, and Retro Pocket never downloads games.

## Downloads

| File | For | To start |
| --- | --- | --- |
| `Retro-Pocket-Windows.zip` | Windows 10 and 11, 64-bit | Unzip anywhere, put your dumps in the `roms` folder, and double-click **Retro Pocket.cmd**. Python and the emulators are included. |
| `Retro-Pocket-macOS-Apple-Silicon.zip` | Macs with an M-series chip, macOS 11 or later | Unzip and move the app to Applications. Open it once; macOS blocks it because it isn't signed with an Apple developer ID, so choose **Open Anyway** in System Settings → Privacy & Security. Put your dumps in `~/Retro Pocket/roms`. |
| `Retro-Pocket-macOS-Intel.zip` | Intel Macs, macOS 10.15 or later (also runs on Apple Silicon under Rosetta) | As for Apple Silicon. |
| `Retro-Pocket-Linux.tar.gz` | 64-bit Linux | Unpack, install the emulators from your distribution (Ubuntu: `sudo apt install python3-venv libretro-mgba desmume mupen64plus-ui-console mupen64plus-video-glide64mk2`), then run `./setup.sh` and `./RetroPocket.sh`. |

**Updating:** Retro Pocket 1.1.0 and later find new releases themselves and offer an **Update** button. Your saves, settings and ROMs are kept. Version 1.0.0 predates this, so replace it by hand once: put the new version where the old one was, and move your `roms` folder over on Windows and Linux.

On a Mac, Nintendo 3DS games need macOS 13.4 or later. Supported dumps: `.gb`, `.gbc`, `.gba`, `.nds`, `.z64`, `.min`, uncompressed GameCube `.iso` and decrypted 3DS `.3ds`. Retro Pocket recognises them by their contents (each listed release has a known size and digest), so file names don't matter. See the README for controls, saves and details.

Each file was built from this release's commit on GitHub Actions and checked before publishing. The unit tests ran on each system, and each build was unpacked and run with its own Python. The checks covered the Game Boy Advance emulator running a test game, every emulator being found and built for the right processor, and box art downloading over HTTPS. On Windows and macOS the emulators also started, and on macOS Apple's code signatures were verified.

## Included software

The Windows and macOS builds include these programs unchanged, each under its own licence, from their official releases:

| Program | In | Licence | Source |
| --- | --- | --- | --- |
| mGBA libretro core (libretro buildbot build) | Windows, macOS | MPL 2.0 | [libretro/mgba](https://github.com/libretro/mgba) |
| DeSmuME 0.9.13 | Windows | GPL 2.0 | [TASEmulators/desmume](https://github.com/TASEmulators/desmume) |
| Mupen64Plus 2.6.0 | Windows | GPL 2.0 | [mupen64plus](https://github.com/mupen64plus) |
| Azahar 2127.0.1 | Windows, macOS | GPL 2.0 | [azahar-emu/azahar](https://github.com/azahar-emu/azahar) |
| melonDS 1.1 | macOS | GPL 3.0 | [melonDS-emu/melonDS](https://github.com/melonDS-emu/melonDS) |
| ares v148 | macOS | ISC | [ares-emulator/ares](https://github.com/ares-emulator/ares) |
| CPython 3.12 (python-build-standalone) | Windows, macOS | PSF | [astral-sh/python-build-standalone](https://github.com/astral-sh/python-build-standalone) |
| pygame-ce 2.5.7 | all | LGPL 2.1 | [pygame-community/pygame-ce](https://github.com/pygame-community/pygame-ce) |
| certifi | macOS | MPL 2.0 | [certifi/python-certifi](https://github.com/certifi/python-certifi) |

The one change: Azahar's macOS release packs its Qt frameworks without their symbolic links, so the build puts the standard links back (the files themselves are unchanged).
