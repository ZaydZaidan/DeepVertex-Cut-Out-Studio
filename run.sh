#!/usr/bin/env bash
# Cutout Studio launcher - GUI by default, CLI with: ./run.sh cli <args>
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
# Qt >= 6.5's xcb platform plugin needs libxcb-cursor.so.0. The system package
# (libxcb-cursor0) is not installed, so the library ships inside runtime-libs/
# instead of requiring a system package / sudo.
if [[ -d runtime-libs/usr/lib/x86_64-linux-gnu ]]; then
    export LD_LIBRARY_PATH="$PWD/runtime-libs/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
if [[ "${1:-}" == "cli" ]]; then
    shift
    exec venv/bin/python -m cutout.cli "$@"
fi
# GUI launches from the desktop entry have no terminal: keep a log so failures
# are diagnosable (e.g. missing system libraries).
mkdir -p "$HOME/.cache/cutout-studio"
exec venv/bin/python -m cutout "$@" 2>>"$HOME/.cache/cutout-studio/gui.log"
