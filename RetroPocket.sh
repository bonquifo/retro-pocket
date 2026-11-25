#!/bin/sh
# Start Retro Pocket from this folder (Linux). Options are passed on, for
# example --all or --roms-dir ~/Games; see app.py --help.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Retro Pocket is not set up yet: run ./setup.sh first."
  exit 1
fi
exec .venv/bin/python app.py "$@"
