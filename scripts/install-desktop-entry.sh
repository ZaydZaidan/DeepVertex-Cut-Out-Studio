#!/usr/bin/env bash
# Install a desktop entry (+ icon) for this checkout so the app appears in the
# application menu. Use --desktop to also place it on the Desktop.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="deepvertex-cutout-studio.desktop"

mkdir -p "$APPS_DIR"
cat > "$APPS_DIR/$ENTRY" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=DeepVertex Cut-Out Studio
GenericName=Background Remover
Comment=Local GPU background remover
Exec=$ROOT/run.sh %F
Icon=$ROOT/assets/icon.png
Terminal=false
Categories=Graphics;Photography;
StartupNotify=true
StartupWMClass=DeepVertex Cut-Out Studio
EOF
chmod +x "$APPS_DIR/$ENTRY"

if [[ "${1:-}" == "--desktop" ]]; then
    cp "$APPS_DIR/$ENTRY" "$HOME/Desktop/DeepVertex Cut-Out Studio.desktop"
    chmod +x "$HOME/Desktop/DeepVertex Cut-Out Studio.desktop"
    gio set "$HOME/Desktop/DeepVertex Cut-Out Studio.desktop" metadata::trusted true 2>/dev/null || true
fi

update-desktop-database "$APPS_DIR" 2>/dev/null || true
echo "Installed desktop entry: $APPS_DIR/$ENTRY"
