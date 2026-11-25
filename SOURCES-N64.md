# Nintendo 64

`catalog-n64.json` carries clean retail `.z64` variants for five titles, sourced from the [No-Intro Nintendo 64 DAT dated 2026.11.14](https://raw.githubusercontent.com/libretro/libretro-database/90601bff67dba7057381292f17e08ed2cecbd6dc/metadat/no-intro/Nintendo%20-%20Nintendo%2064.dat). These are big-endian images, not `.v64` byte-swapped files, Virtual Console variants, demos or modified ROMs. The Japanese-only original Stadium is separate from the international Stadium games. Hey You, Pikachu! remains catalogue-only: the needed Voice Recognition Unit path has not been validated. Transfer Pak features were not validated.

With Ubuntu's Mupen64Plus 2.6.0 and Glide64mk2, `tests/smoke_n64.py` booted an original cartridge, verified keyboard A press/release through frame changes, and verified guest SRAM after a restart. No commercial ROM was used.

## Other Nintendo 64 titles

`catalog-mario.json` adds Super Mario 64 at the owner's request, so a dump in the ROM folder can be played the same way. Its four clean retail `.z64` variants (USA, Europe (En,Fr,De), Japan, and Japan Rev 3 Shindou Edition) come from the same No-Intro DAT as above. The owner's USA dump matched it byte for byte (SHA-1 `9bef1128717f958171a4afac3ed78ee2bb4e86ce`). It booted under Mupen64Plus 2.6.0 with Glide64mk2 on Xvfb (software OpenGL): Start, A and the analog stick worked from the title screen into the castle grounds, and the EEPROM save file was written to the game's save folder.
