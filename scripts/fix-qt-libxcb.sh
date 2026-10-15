#!/usr/bin/env bash
# Vendor libxcb-cursor into this checkout (no sudo required).
#
# Qt >= 6.5 loads libxcb-cursor.so.0 for its xcb platform plugin. On minimal
# Ubuntu/Debian installs the package libxcb-cursor0 is missing and the GUI
# aborts with:
#   qt.qpa.plugin: From 6.5.0, xcb-cursor0 or libxcb-cursor0 is needed to load
#   the Qt platform plugin "xcb"
# This script downloads the Debian package, extracts the shared library into
# runtime-libs/ (used via LD_LIBRARY_PATH in run.sh) and copies it into the
# PySide6 Qt lib directory (covered by Qt's RPATH).
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$ROOT"

if ldconfig -p 2>/dev/null | grep -q libxcb-cursor; then
    echo "libxcb-cursor is already available system-wide; nothing to do."
    exit 0
fi

PY="venv/bin/python"
[[ -x "$PY" ]] || PY="python3"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
( cd "$TMP" && apt-get download libxcb-cursor0 )
mkdir -p runtime-libs
dpkg-deb -x "$TMP"/libxcb-cursor0_*.deb runtime-libs

QT_LIB_DIR="$("$PY" -c 'import pathlib, PySide6; print(pathlib.Path(PySide6.__file__).parent / "Qt" / "lib")')"
cp -a runtime-libs/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0* "$QT_LIB_DIR/" 2>/dev/null || true
echo "Vendored libxcb-cursor into runtime-libs/ and PySide6 Qt lib dir."
