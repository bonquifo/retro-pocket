#!/bin/sh
# Retro Pocket for Linux: create the Python environment and install pygame-ce.
# The emulators come from your distribution's packages (see README.md); this
# says which are missing. Run it again at any time to repair.
set -eu
cd "$(dirname "$0")"

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  echo "Python 3.11 or newer is needed as python3."
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating the Python environment..."
  python3 -m venv .venv || { echo "Install your distribution's python3-venv package and run this again."; exit 1; }
fi
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt

missing=""
ls /usr/lib/*/libretro/mgba_libretro.so /usr/lib/libretro/mgba_libretro.so >/dev/null 2>&1 || missing="$missing libretro-mgba"
[ -x /usr/games/desmume-cli ] || [ -x /usr/bin/desmume-cli ] || [ -x /usr/games/desmume ] || [ -x /usr/bin/desmume ] \
  || missing="$missing desmume"
[ -x /usr/games/mupen64plus ] || [ -x /usr/bin/mupen64plus ] || missing="$missing mupen64plus-ui-console"
if [ -n "$missing" ]; then
  echo "Not installed yet:$missing (on Ubuntu: sudo apt install$missing)."
  echo "Nintendo 3DS games need Azahar; see README.md."
fi
echo "Setup complete. Put your game dumps in the roms folder and run ./RetroPocket.sh"
