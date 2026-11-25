#!/bin/bash
# Retro Pocket for macOS, run from this folder: a Python for this Mac (Apple
# Silicon or Intel), pygame-ce, and the emulators in emulators/ (see
# tools/install_emulators.py). Double-click it in Finder, or run it in
# Terminal; run it again at any time to repair or update. Arguments go to
# install_emulators.py. For a double-clickable app, see tools/build_macos.py.
set -euo pipefail
cd "$(dirname "$0")"

# Python, pinned: python-build-standalone's relocatable CPython for this Mac.
RELEASE=https://github.com/astral-sh/python-build-standalone/releases/download/20261124
case "$(uname -m)" in
  arm64)  NAME=cpython-3.12.16+20261124-aarch64-apple-darwin-install_only.tar.gz
          SHA256=431b99a9c2cdd37ad9b06e425be0e520d2dbce0552abe454257abef592fe3634 ;;
  x86_64) NAME=cpython-3.12.16+20261124-x86_64-apple-darwin-install_only.tar.gz
          SHA256=ccce24cfd3f56f62561d2c9480fcc567ca3a9bac68450cd73e11aeb631befa1f ;;
  *) echo "Unsupported Mac: $(uname -m)"; exit 1 ;;
esac

if [ ! -x .python/bin/python3.12 ]; then
  echo "Downloading Python 3.12 for $(uname -m)..."
  scratch=$(mktemp -d)
  trap 'rm -rf "$scratch"' EXIT
  curl --fail --location --silent --show-error -o "$scratch/python.tar.gz" "$RELEASE/${NAME//+/%2B}"
  echo "$SHA256  $scratch/python.tar.gz" | shasum -a 256 -c - >/dev/null || { echo "Python download failed its SHA-256 check"; exit 1; }
  tar -xzf "$scratch/python.tar.gz" -C "$scratch"
  rm -rf .python
  mv "$scratch/python" .python
fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating the Python environment..."
  .python/bin/python3.12 -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
.venv/bin/python tools/install_emulators.py "$@"
echo
echo "Setup complete. Put your game dumps in the roms folder and double-click RetroPocket.command."
