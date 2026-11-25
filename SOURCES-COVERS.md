# Covers

`covers-index.json` maps catalogue IDs to front box art in the [libretro-thumbnails](https://github.com/libretro-thumbnails) repositories (`Named_Boxarts`), one repository per system, each pinned to the commit it was read from. Each entry records the URL, byte size and SHA-256 of the exact file; Retro Pocket rejects any download that differs. The images are not stored in this repository.

`tools/build_cover_index.py` (run 2026-11-25) chose each file as follows:

- **Playable releases:** the release names of the catalogued dumps, looked up by SHA-1 in the same No-Intro and Redump DATs as the catalogue (`SOURCES*.md`), in catalogue order (USA first). If libretro-thumbnails names a release with older region tags (Pokémon Diamond is "(USA) (Rev 5)" there, "(USA, Australia) (Rev 5)" in the DAT), it takes that file instead, skipping demo and kiosk boxes.
- **3DS and catalogue-only titles:** the catalogued dumps are decrypted 3DS images not in No-Intro, or there is no dump at all, so it matched the catalogue title against the repository's file names, USA releases first.

Result: 80 of 211 entries. All 65 playable releases have art (the 2048 homebrew was later removed from the catalogue). The rest have no physical box in these repositories: download-only 3DS and Wii titles (eShop, Virtual Console, WiiWare), Pokémon Box Ruby & Sapphire (GameCube; not in libretro-thumbnails), and the Wii U, Switch, mobile, arcade, PC and web entries, for which libretro-thumbnails has no repository.

Box art is the publishers' artwork; libretro-thumbnails collects it for front-end display, which is how Retro Pocket uses it.
