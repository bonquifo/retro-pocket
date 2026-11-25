#!/usr/bin/env python3
"""Regenerate covers-index.json: pinned box art for the catalogue.

Developer tool; needs network access. For each playable game it finds the
release name (No-Intro, or Redump for GameCube) of its catalogued dumps by
SHA-1, picks the first name that has a box art file in the matching
libretro-thumbnails repository at a pinned commit, downloads that file once
and records its size and SHA-256. Retro Pocket then downloads exactly those
bytes at runtime and rejects anything else.

Usage: python3 tools/build_cover_index.py WORK_DIR
"""
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from library import Library  # noqa: E402

DATABASE = 'https://raw.githubusercontent.com/libretro/libretro-database/90601bff67dba7057381292f17e08ed2cecbd6dc/metadat/'
SYSTEMS = {  # platform: (libretro-thumbnails repository, DAT path or None)
    'GB': ('Nintendo_-_Game_Boy', 'no-intro/Nintendo - Game Boy.dat'),
    'GBC': ('Nintendo_-_Game_Boy_Color', 'no-intro/Nintendo - Game Boy Color.dat'),
    'GBA': ('Nintendo_-_Game_Boy_Advance', 'no-intro/Nintendo - Game Boy Advance.dat'),
    'NDS': ('Nintendo_-_Nintendo_DS', 'no-intro/Nintendo - Nintendo DS.dat'),
    '3DS': ('Nintendo_-_Nintendo_3DS', None),  # Catalogued 3DS bytes are decrypted dumps; match by title.
    'N64': ('Nintendo_-_Nintendo_64', 'no-intro/Nintendo - Nintendo 64.dat'),
    'GCN': ('Nintendo_-_GameCube', 'redump/Nintendo - GameCube.dat'),
    'Wii': ('Nintendo_-_Wii', 'redump/Nintendo - Wii.dat'),
    'Mini': ('Nintendo_-_Pokemon_Mini', 'no-intro/Nintendo - Pokemon Mini.dat'),
}
UA = {'User-Agent': 'retro-pocket-cover-index'}


def fetch(url, binary=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as response:
        data = response.read()
    return data if binary else data.decode('utf-8', 'replace')


def api(path):
    return json.loads(fetch('https://api.github.com/' + path))


def thumbnail_name(release):
    """libretro-thumbnails replaces these characters in file names."""
    return re.sub(r'[&*/:`<>?\\|"]', '_', release) + '.png'


def dat_names(text):
    """SHA-1 (lower case) -> release name, from a clrmamepro DAT."""
    names = {}
    for block in re.finditer(r'^game \(\n(.*?)^\)', text, re.M | re.S):
        name = re.search(r'^\tname "(.*)"$', block.group(1), re.M)
        for sha1 in re.findall(r'sha1 ([0-9A-Fa-f]{40})', block.group(1)):
            if name:
                names.setdefault(sha1.lower(), name.group(1))
    return names


def ascii_fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))


def main(work):
    work = Path(work)
    (work / 'art').mkdir(parents=True, exist_ok=True)
    library = Library(root=work / 'library')
    index = {'source': 'https://github.com/libretro-thumbnails', 'covers': {}}
    pinned, listings, dats = {}, {}, {}
    for game in library.games:
        # Catalogue-only titles get art too, matched by title, when their system has a repository.
        if game['platform'] not in SYSTEMS:
            continue
        repo, dat = SYSTEMS[game['platform']]
        if repo not in pinned:
            pinned[repo] = api(f'repos/libretro-thumbnails/{repo}/commits/master')['sha']
            top = api(f'repos/libretro-thumbnails/{repo}/git/trees/{pinned[repo]}')['tree']
            boxarts = next(t for t in top if t['path'] == 'Named_Boxarts')
            listings[repo] = {t['path'] for t in api(
                f"repos/libretro-thumbnails/{repo}/git/trees/{boxarts['sha']}")['tree']}
        if dat and dat not in dats:
            dats[dat] = dat_names(fetch(DATABASE + urllib.parse.quote(dat)))
        candidates = [dats[dat][v['sha1'].lower()] for v in game.get('variants', ())
                      if dat and v.get('sha1', '').lower() in dats[dat]]
        if not candidates:
            # Match by title: "Pokémon X" -> "Pokemon X (USA)...", USA releases first.
            stem = ascii_fold(game['title']).replace(':', ' -')
            matches = sorted((p[:-4] for p in listings[repo] if p.startswith(stem + ' (')),
                             key=lambda n: ('(USA' not in n, '(Demo' in n or 'Kiosk' in n, n))
            candidates = matches
        chosen = next((c for c in candidates if thumbnail_name(c) in listings[repo]), None)
        if chosen is None and candidates:
            # Region tags in thumbnail names can lag the DAT ("(USA)" vs "(USA, Australia)"):
            # accept another file for the same release name, USA first, no demos.
            base = thumbnail_name(candidates[0].split(' (')[0])[:-4]
            same = sorted((p[:-4] for p in listings[repo] if p.startswith(base + ' (')
                           and 'Demo' not in p and 'Kiosk' not in p),
                          key=lambda n: ('(USA' not in n, n))
            chosen = same[0] if same else None
        if chosen is None:
            print(f"no box art: {game['id']} ({game['title']}); tried {candidates[:3]}")
            continue
        path = f'Named_Boxarts/{thumbnail_name(chosen)}'
        url = f'https://raw.githubusercontent.com/libretro-thumbnails/{repo}/{pinned[repo]}/' + \
            urllib.parse.quote(path)
        data = fetch(url, binary=True)
        (work / 'art' / f"{game['id']}.png").write_bytes(data)
        index['covers'][game['id']] = {'url': url, 'size': len(data),
                                       'sha256': hashlib.sha256(data).hexdigest(), 'release': chosen}
        print(f"{game['id']}: {chosen} ({len(data)} bytes)")
    out = ROOT / 'covers-index.json'
    out.write_text(json.dumps(index, indent=1, ensure_ascii=False) + '\n')
    print(f'wrote {out} with {len(index["covers"])} covers')


if __name__ == '__main__':
    main(sys.argv[1])
