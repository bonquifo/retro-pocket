# Nintendo 3DS / Azahar support findings

**Status (2026-11-24 UTC): seven 3DS titles are playable in Retro Pocket through Azahar 2127.0.** Pokémon X, Y, Omega Ruby, Alpha Sapphire, Sun, Moon and Ultra Moon are listed in `catalog-azahar.json` and replace their `catalog-unavailable.json` rows by ID. The worker checks the image in place and passes `azahar_backend.launch` a hard link to the checked file in a per-launch folder, as it does for Dolphin. Each title booted to its in-game language-selection screen under Xvfb with Mesa software OpenGL, using the official `azahar.AppImage` from release 2127.0 (SHA-256 `c69f6c3ae0862594a5e46e4811ed4282fbc3adc45831b1f94d11d2f3d7d33a60`). Gameplay past that screen, in-game saving, and online features were not tested. The AppImage needs `libOpenGL.so.0` (Ubuntu `libopengl0`).

**Byte provenance.** Each accepted variant's size and SHA-1 come from the owner's local decrypted dumps (NCSD containers whose NCCH partitions have the NoCrypto flag set) that passed this boot test. They have not been cross-checked against a No-Intro decrypted DAT, so the label says "decrypted dump". Encrypted dumps of the same release have different bytes and are rejected. That is intentional, because Azahar cannot load encrypted content without keys.[3][4][6] Other 3DS rows (including Ultra Sun) stay catalogue-only until a dump is verified the same way.

## Local launcher scope

The launcher uses `RETRO_POCKET_AZAHAR` if it is set (it must be an absolute path to a trusted executable). Otherwise it checks only these fixed paths: `/usr/bin/azahar`, `/usr/games/azahar`, `/usr/local/bin/azahar`, `~/Applications/azahar.AppImage` and `~/.local/bin/azahar`. `azahar_backend.launch(rom: Path, game_id: str, save_dir: Path)` gives the executable one absolute positional ROM path and returns the `Popen`; the caller owns the child and must keep the ROM available while it runs. This matches the Qt frontend's positional parser and `BootGame` call.[1] No shell, PATH search, installation, title conversion, or copying of an existing Azahar profile. Flatpak, wrapper scripts that reset the environment or working directory, and non-Linux platforms are outside this assessment.

Pass a private save root. Relaunch with the same `save_dir` and catalogue-style `game_id` to reuse the profile at `<save_dir>/azahar/<game_id>`. The launcher sets the child's working directory there and sets `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, and `XDG_CACHE_HOME` to the profile's `data`, `config`, and `cache` subdirectories. On Linux, upstream gives a working-directory `user` folder precedence over XDG; either path stays in the profile. Upstream places its emulated SD and NAND under its user data directory.[2] This separates default emulator profiles; it is **not** a sandbox. Do not reuse profiles that have been manually configured to point at shared save storage, or run two sessions against the same profile at once.

The launcher accepts `.cci` and `.3ds` cartridge paths and `.3dsx` homebrew paths as a narrow filename check, not proof of valid content. Upstream lists these suffixes, but its NCCH loader rejects encrypted content.[3][4] No-Intro distinguishes encrypted and decrypted byte variants; a hash for one does not validate the other.[6] The launcher does not install CIA packages or acquire keys, firmware, or games. Callers are responsible for provenance and exact-byte verification before launch.

## Reproduce the real-emulator smoke on a Linux desktop

1. Point `RETRO_POCKET_AZAHAR` at your trusted installation. In a normal graphical session, use its `--version` and `--help` to record the build and check the CLI; both flags are implemented by the Qt frontend.[1]
2. Supply a known-good, legally available local homebrew `.3dsx`, preferably one with visible input feedback and a save/readback feature. Record its provenance, exact byte size and SHA-256. Use a fresh writable scratch folder as the save root, not the normal Azahar profile. From this project directory, replace the two example paths with your own:

   ```sh
   .venv/bin/python -c 'from pathlib import Path; import sys; from azahar_backend import launch; raise SystemExit(launch(Path(sys.argv[1]), "3ds-smoke", Path(sys.argv[2])).wait())' \
     /path/to/homebrew.3dsx /path/to/scratch/azahar-smoke
   ```

3. Verify the guest boots without a loader error and responds to input. Save in the guest and close Azahar normally. Check that its data is under the scratch profile. Run the same command again and confirm the guest loads that save. Use another game ID with the same file to check that the second profile starts without the first profile's save. Process startup, an empty window, or a clean exit alone is not a passing smoke test.

## Catalogue decision

`catalog-azahar.json` promotes the seven verified titles and keeps their existing IDs. To add another title, verify a decrypted dump boots in Azahar, then add its exact size and SHA-1 as a new variant (or a new promoted row) with the same ID as its `catalog-unavailable.json` record. `tests/test_azahar.py` checks which titles are promoted, import and staging of 3DS images, and the worker's launch path.

## Sources

[1] https://github.com/azahar-emu/azahar/blob/219d743a1e698101fe1ab8bef43e6563126c3c27/src/citra_qt/citra_qt.cpp
[2] https://github.com/azahar-emu/azahar/blob/219d743a1e698101fe1ab8bef43e6563126c3c27/src/common/file_util.cpp
[3] https://github.com/azahar-emu/azahar/blob/219d743a1e698101fe1ab8bef43e6563126c3c27/src/core/loader/loader.cpp
[4] https://github.com/azahar-emu/azahar/blob/219d743a1e698101fe1ab8bef43e6563126c3c27/src/core/file_sys/ncch_container.cpp
[5] https://github.com/azahar-emu/azahar/releases/tag/2126.2
[6] https://wiki.no-intro.org/?title=Nintendo_-_Nintendo_3DS_dat_notes
