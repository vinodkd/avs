#!/usr/bin/env bash
# Build AxEdUp AppImage for Linux (x86_64).
#
# Prerequisites (Ubuntu/Debian):
#   sudo apt install libgtk-3-dev libwebkit2gtk-4.0-dev gir1.2-webkit2-4.0
#   pip install pyinstaller
#
# Run from project root:
#   bash packaging/build_appimage.sh
#
# Output: dist/AxEdUp-<version>-x86_64.AppImage

set -euo pipefail
cd "$(dirname "$0")/.."

APPNAME="AxEdUp"
VERSION=$(python3 -c "from axedup import __version__; print(__version__)")
ARCH="x86_64"
APPIMAGE_OUT="dist/${APPNAME}-${VERSION}-${ARCH}.AppImage"
APPIMAGETOOL="dist/appimagetool"

echo "==> Building ${APPNAME} v${VERSION}"

# ── 1. PyInstaller ────────────────────────────────────────────────────────────
echo "==> Running PyInstaller..."
pyinstaller axedup.spec --noconfirm

# ── 2. Fetch appimagetool ─────────────────────────────────────────────────────
if [ ! -x "$APPIMAGETOOL" ]; then
    echo "==> Downloading appimagetool..."
    mkdir -p dist
    curl -sSL \
        "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage" \
        -o "$APPIMAGETOOL"
    chmod +x "$APPIMAGETOOL"
fi

# ── 3. Assemble AppDir ────────────────────────────────────────────────────────
echo "==> Assembling AppDir..."
APPDIR="dist/${APPNAME}.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR"

# Copy PyInstaller output (onedir bundle)
cp -r dist/axedup/* "$APPDIR/"

# Desktop entry + icon
cp packaging/axedup.desktop "$APPDIR/${APPNAME}.desktop"
if [ -f packaging/axedup.png ]; then
    cp packaging/axedup.png "$APPDIR/axedup.png"
else
    # Placeholder: copy a system icon if axedup.png hasn't been designed yet
    cp /usr/share/icons/hicolor/128x128/apps/nautilus.png "$APPDIR/axedup.png" 2>/dev/null || true
fi

# AppRun — entry point executed by the AppImage runtime
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="${HERE}/_internal:${LD_LIBRARY_PATH:-}"
exec "${HERE}/axedup" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# ── 4. Build AppImage ─────────────────────────────────────────────────────────
echo "==> Building AppImage..."
ARCH="$ARCH" APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" "$APPDIR" "$APPIMAGE_OUT"

echo ""
echo "==> Done: ${APPIMAGE_OUT}"
echo "    $(du -sh "$APPIMAGE_OUT" | cut -f1)"
