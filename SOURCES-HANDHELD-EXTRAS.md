# Pokémon handheld extras: cartridge metadata

`catalog-handheld-extras.json` adds five official English-playable spin-offs and four explicitly labeled Japanese cartridge entries. It contains metadata only: no commercial ROM was downloaded, bundled, linked, or boot-tested. Each variant’s byte size and SHA-1 comes from a raw `rom` record in Libretro’s No-Intro DATs (`2026.11.14`), pinned at `90601bff67dba7057381292f17e08ed2cecbd6dc`, the same commit used by `SOURCES.md`.[1][2][3]

## English-playable games

Platform follows the DAT: Trading Card Game and Pinball are GBC entries even though their cartridges also work on the original Game Boy.[2] Each game has one ID covering all English-capable retail cartridge records for that title in the pin, including European multilingual versions marked `En`. Labels retain region, language set, revision, and Pinball’s retail `Rumble Version` designation; a shared `USA, Australia` image is one variant. `year` is the first US cartridge release year, consistent with the main catalogue.[2][3]

| Game | Platform | Year | Pinned DAT title prefix | Variants |
| --- | --- | --- | --- | --- |
| Pokémon Trading Card Game | GBC | 2000 [4] | `Pokemon Trading Card Game` [2] | USA/Australia; Europe En/Fr/De and En/Es/It, each with original and Rev 1 |
| Pokémon Pinball | GBC | 1999 [5] | `Pokemon Pinball` [2] | USA/Australia and multilingual Europe, both retail Rumble Version |
| Pokémon Puzzle Challenge | GBC | 2000 [6] | `Pokemon Puzzle Challenge` [2] | USA/Australia and multilingual Europe |
| Pokémon Pinball: Ruby & Sapphire | GBA | 2003 [7] | `Pokemon Pinball - Ruby & Sapphire` [3] | USA and multilingual Europe |
| Pokémon Mystery Dungeon: Red Rescue Team | GBA | 2006 [8] | `Pokemon Mystery Dungeon - Red Rescue Team` [3] | USA/Australia and multilingual Europe |

## Japanese releases

These cartridges are in Japanese, not additional English variants. `year` is the first Japanese cartridge release year; the suffix `(Japan)` distinguishes them in the app. Green (Midori) is an original Japanese release, and Japanese Blue (Ao) is the later third version with distinct encounters and trades, not the existing English Blue entry.[1][9][23] Japanese Blue first shipped in 1996; Nintendo lists general retail sales starting in 1999.[10] Japanese Crystal gets a separate entry because the Japanese cartridge includes Mobile System GB features removed from the localized version; this does not restore the discontinued mobile service.[2][13] Card GB2 is a separate Japan-only sequel, commonly called *Pokémon Trading Card Game 2: The Invasion of Team GR!* in English references.[12][17]

| Game | Platform | Year | Pinned DAT title prefix | Variants |
| --- | --- | --- | --- | --- |
| Pocket Monsters Green (Japan) | GB | 1996 [9] | `Pocket Monsters - Midori` [1] | Japan, Japan Rev 1 |
| Pocket Monsters Blue (Japan) | GB | 1996 [10] | `Pocket Monsters - Ao` [1] | Japan |
| Pocket Monsters Crystal (Japan) | GBC | 2000 [9] | `Pocket Monsters - Crystal Version` [2] | Japan |
| Pokémon Card GB2: GR Dan Sanjou! (Japan) | GBC | 2001 [12] | `Pokemon Card GB 2 - GR Dan Sanjou!` [2] | Japan |

The Australian English Crystal image is a distinct retail dump but not a separate game.[2][13][20] It belongs as a variant of the existing English `pokemon-crystal` entry if the base catalogue is broadened beyond its USA-inclusive policy. This supplement does not duplicate that ID or add a separate Australian title. Other Japanese editions of already represented titles are outside the scope of this supplement.

## Screened out

| Candidate | Why it is not a playable catalogue entry |
| --- | --- |
| Trade/event tools: 10th Anniversary, Aura Mew, Aurora Ticket, Doel Deoxys, Liechi Berry Glitch Fix & Shiny Zigzagoon, Manaphy Present Campaign and Slot 2 Distribution prototype | Distribution, trading or patch utilities that serve another game, not standalone games. The pinned GBA DAT lists these separately from retail games.[3][14] |
| Red Rescue Team US kiosk demo (B9JE) | A playable demo, not a separate full game or a retail revision. Listed in the Open Source Cartridge Reader metadata, not the pinned GBA DAT.[3][22] |
| Pokémon GBA Video (2004): *For Ho-Oh the Bells Toll!*, *Johto Photo Finish*, *Pokémon—I Choose You*, and *Beach Blank-Out Blastoise* | Four episode-playback cartridges, not games. None appears in the pinned GBA DAT.[3][15] |
| Ruby/Sapphire `(Pokemon Box)` records; e-Reader, Battle e and Eon Ticket | The Box records are copies embedded on the GameCube utility disc, not new handheld releases; the reader and cards are a peripheral and add-on data, not standalone Pokémon game cartridges.[3][16][19] |
| Pokémon Picross (GBC); Green Version – English Edition (Taiwan) | Picross was canceled and the DAT labels it a prototype; the purported English Green is marked `Pirate`, not an official localization.[1][2][17] |
| Blue Rescue Team, Pokémon mini games, Virtual Console and Nintendo Switch rereleases | Blue Rescue Team is for Nintendo DS; Pokémon mini is separate hardware; digital rereleases are not original GB/GBC/GBA cartridges.[8][17][18] |

## Sources

[1] https://raw.githubusercontent.com/libretro/libretro-database/90601bff67dba7057381292f17e08ed2cecbd6dc/metadat/no-intro/Nintendo%20-%20Game%20Boy.dat — Pinned No-Intro GB DAT
[2] https://raw.githubusercontent.com/libretro/libretro-database/90601bff67dba7057381292f17e08ed2cecbd6dc/metadat/no-intro/Nintendo%20-%20Game%20Boy%20Color.dat — Pinned No-Intro GBC DAT
[3] https://raw.githubusercontent.com/libretro/libretro-database/90601bff67dba7057381292f17e08ed2cecbd6dc/metadat/no-intro/Nintendo%20-%20Game%20Boy%20Advance.dat — Pinned No-Intro GBA DAT
[4] https://www.pokemon.com/us/pokemon-video-games/pokemon-trading-card-game — Pokémon.com: Trading Card Game
[5] https://www.pokemon.com/us/pokemon-video-games/pokemon-pinball — Pokémon.com: Pinball
[6] https://bulbapedia.bulbagarden.net/wiki/Pokemon_Puzzle_Challenge — Puzzle Challenge release dates
[7] https://www.pokemon.com/us/pokemon-video-games/pokemon-pinball-ruby-and-sapphire — Pokémon.com: Pinball: Ruby & Sapphire
[8] https://www.pokemon.com/us/pokemon-video-games/pokemon-mystery-dungeon-blue-rescue-team-and-pokemon-mystery-dungeon-red-rescue-team — Pokémon.com: Red and Blue Rescue Team
[9] https://www.nintendo.co.jp/n02/dmg/index.html — Nintendo’s Japanese Game Boy software archive
[10] https://www.nintendo.co.jp/n02/dmg/apej/index.html — Nintendo: Pocket Monsters Blue
[12] https://www.pokemon.co.jp/game/other/gbc-gr/ — The Pokémon Company: Card GB2
[13] https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_Crystal — Japanese and Australian Crystal differences
[14] https://bulbapedia.bulbagarden.net/wiki/Distribution_cartridge — Pokémon distribution devices
[15] https://bulbapedia.bulbagarden.net/wiki/Game_Boy_Advance_Video — The four Pokémon GBA Video cartridges
[16] https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_Box:_Ruby_&_Sapphire — Pokémon Box and its embedded games
[17] https://bulbapedia.bulbagarden.net/wiki/Pokemon_games — Pokémon games by series and platform
[18] https://www.pokemon.com/us/pokemon-video-games/pokemon-mystery-dungeon-rescue-team-dx — Pokémon.com: Original Rescue Team platforms
[19] https://bulbapedia.bulbagarden.net/wiki/E-Reader — e-Reader and its uses in Pokémon games
[20] https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_in_Australia — Australian Crystal cartridge
[22] https://raw.githubusercontent.com/sanni/cartreader/master/sd/gba.txt — Open Source Cartridge Reader: GBA cartridge metadata, including B9JE
[23] https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_Blue_Version_%28Japanese%29 — Japanese Blue and Western Blue differences
