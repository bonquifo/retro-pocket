# Nintendo DS catalog provenance

`catalog-nds.json` contains 20 games: all nine mainline releases, all ten official US retail spin-offs, and the English European cartridge of **Learn with Pokémon: Typing Adventure**.[1][2][3] Typing Adventure had no North American release.[4]

## Cartridge metadata

All 22 variants were matched to the `rom` records in Libretro’s Nintendo DS No-Intro DAT, version `2026.11.14`, pinned at commit `90601bff67dba7057381292f17e08ed2cecbd6dc`. The DAT itself is 2,325,135 bytes, with SHA-256 `6cb477b781dceb11fdef07fb5ee11ad9ff24da342271e323aeb26f7af20e85d2`.[1]

The catalog uses the DAT’s exact untrimmed `.nds` byte sizes and SHA-1 values (written in lowercase). Labels preserve the DAT’s region, revision, and `NDSi Enhanced` flags. Combined regions identify one image, not separate variants. The four Gen V mainline titles and Conquest are DSi-enhanced DS cartridges, so their platform is `NDS`. Diamond and Pearl use the USA-inclusive `Rev 5` records; Platinum and Conquest each have two USA-inclusive retail variants in this snapshot.[1][2]

Validation compared each catalog variant’s label, exact byte count, and SHA-1 against a unique DAT entry. To reproduce, combine the DAT title stem below with the catalog region in parentheses and the remaining label suffix unchanged, then compare the named `.nds` record’s `size` and `sha1` fields. `year` is the first US cartridge release year, or the first European release year for Typing Adventure, not the year of a revision or rerelease.[1][3][4]

| Catalog ID (without `pokemon-`) | DAT title stem | Release year [3][4] |
| --- | --- | ---: |
| `diamond` | `Pokemon - Diamond Version` | 2007 |
| `pearl` | `Pokemon - Pearl Version` | 2007 |
| `platinum` | `Pokemon - Platinum Version` | 2009 |
| `heartgold` | `Pokemon - HeartGold Version` | 2010 |
| `soulsilver` | `Pokemon - SoulSilver Version` | 2010 |
| `black` | `Pokemon - Black Version` | 2011 |
| `white` | `Pokemon - White Version` | 2011 |
| `black-2` | `Pokemon - Black Version 2` | 2012 |
| `white-2` | `Pokemon - White Version 2` | 2012 |
| `dash` | `Pokemon Dash` | 2005 |
| `trozei` | `Pokemon Trozei!` | 2006 |
| `mystery-dungeon-blue-rescue-team` | `Pokemon Mystery Dungeon - Blue Rescue Team` | 2006 |
| `ranger` | `Pokemon Ranger` | 2006 |
| `mystery-dungeon-explorers-of-time` | `Pokemon Mystery Dungeon - Explorers of Time` | 2008 |
| `mystery-dungeon-explorers-of-darkness` | `Pokemon Mystery Dungeon - Explorers of Darkness` | 2008 |
| `ranger-shadows-of-almia` | `Pokemon Ranger - Shadows of Almia` | 2008 |
| `mystery-dungeon-explorers-of-sky` | `Pokemon Mystery Dungeon - Explorers of Sky` | 2009 |
| `ranger-guardian-signs` | `Pokemon Ranger - Guardian Signs` | 2010 |
| `conquest` | `Pokemon Conquest` | 2012 |
| `typing-adventure` | `Learn with Pokemon - Typing Adventure` | 2012 (Europe) |

## Exclusions

- Other regional variants are outside the US-first scope. **Pokémon Link!** is the European localization of **Trozei!**, not a separate game.[1][3] **Pokémon Card Game: How to Play DS** is a distinct Japan-only cartridge with no US or European release.[2][5]
- **Mystery Dungeon: Red Rescue Team** is GBA, not DS. **PokéPark Fishing Contest DS** is a Download Play release, not a retail cartridge.[2][3]
- Demos, prototypes, promotional videos, event-distribution and kiosk cards, Wii U Virtual Console images, unofficial modifications, and trimmed images are not retail cartridge variants in this catalog.[1][2]

No commercial ROMs were downloaded, bundled, linked, or booted. Verification covers catalog metadata and loading, not gameplay.

## Sources

[1] https://raw.githubusercontent.com/libretro/libretro-database/90601bff67dba7057381292f17e08ed2cecbd6dc/metadat/no-intro/Nintendo%20-%20Nintendo%20DS.dat — Libretro No-Intro Nintendo DS DAT (pinned)
[2] https://bulbapedia.bulbagarden.net/wiki/Nintendo_DS — Bulbapedia: Nintendo DS
[3] https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_games — Bulbapedia: Pokémon games and regional release dates
[4] https://bulbapedia.bulbagarden.net/wiki/Learn_with_Pok%C3%A9mon:_Typing_Adventure — Bulbapedia: Learn with Pokémon: Typing Adventure
[5] https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_Card_Game:_How_to_Play_DS — Bulbapedia: Pokémon Card Game: How to Play DS
