#!/bin/bash
# Start Retro Pocket from this folder (macOS). Options are passed on, for
# example --all or --roms-dir ~/Games; see app.py --help. Messages appear in
# this Terminal window.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Retro Pocket is not set up yet: double-click setup.command first."
  exit 1
fi
exec .venv/bin/python app.py "$@"
