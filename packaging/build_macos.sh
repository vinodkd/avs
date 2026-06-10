#!/usr/bin/env bash
# Build AxEdUp macOS DMG using PyInstaller + create-dmg.
#
# Prerequisites:
#   brew install create-dmg
#   pip install pyinstaller
#
# Run from project root:
#   bash packaging/build_macos.sh
#
# Output: dist/AxEdUp-<version>.dmg

set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "from axedup import __version__; print(__version__)")
DMG_OUT="dist/AxEdUp-${VERSION}.dmg"

echo "==> Building AxEdUp v${VERSION}"

# ── 1. PyInstaller ────────────────────────────────────────────────────────────
echo "==> Running PyInstaller..."
pyinstaller axedup.spec --noconfirm

# ── 2. DMG ────────────────────────────────────────────────────────────────────
echo "==> Building DMG..."
mkdir -p dist

# Remove stale DMG so create-dmg doesn't error on overwrite
rm -f "$DMG_OUT"

if command -v create-dmg &>/dev/null; then
    ARGS=(
        --volname "AxEdUp"
        --window-pos 200 120
        --window-size 600 400
        --icon-size 100
        --icon "AxEdUp.app" 175 190
        --hide-extension "AxEdUp.app"
        --app-drop-link 425 185
    )
    # Add volume icon only if .icns exists
    if [ -f "packaging/axedup.icns" ]; then
        ARGS+=(--volicon "packaging/axedup.icns")
    fi
    create-dmg "${ARGS[@]}" "$DMG_OUT" "dist/AxEdUp.app"
else
    # Fallback: plain hdiutil (no fancy layout, but functional)
    echo "==> create-dmg not found; falling back to hdiutil..."
    hdiutil create -volname "AxEdUp" -srcfolder "dist/AxEdUp.app" \
        -ov -format UDZO "$DMG_OUT"
fi

echo ""
echo "==> Done: ${DMG_OUT}"
echo "    $(du -sh "$DMG_OUT" | cut -f1)"
