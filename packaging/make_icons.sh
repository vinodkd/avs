#!/usr/bin/env bash
# Generate axedup.ico, axedup.icns, and axedup.png from packaging/icon.svg.
#
# Prerequisites (already available on dev machine):
#   inkscape, imagemagick (convert), python3 + Pillow
#
# Run from project root:
#   bash packaging/make_icons.sh

set -euo pipefail
cd "$(dirname "$0")"          # work from packaging/

SVG="icon.svg"
TMP=".icon_tmp"

mkdir -p "$TMP"
trap 'rm -rf "$TMP"' EXIT

# ── 1. Export PNGs at all needed sizes ────────────────────────────────────────
echo "==> Exporting PNGs from SVG..."
for SIZE in 16 24 32 48 64 128 256 512; do
    inkscape \
        --export-type=png \
        --export-filename="$TMP/icon-${SIZE}.png" \
        --export-width="$SIZE" \
        --export-height="$SIZE" \
        "$SVG" 2>/dev/null
    echo "    ${SIZE}x${SIZE}"
done

# ── 2. axedup.ico — multi-resolution Windows icon ─────────────────────────────
echo "==> Building axedup.ico..."
convert \
    "$TMP/icon-256.png" \
    "$TMP/icon-128.png" \
    "$TMP/icon-64.png"  \
    "$TMP/icon-48.png"  \
    "$TMP/icon-32.png"  \
    "$TMP/icon-16.png"  \
    axedup.ico

# ── 3. axedup.icns — macOS bundle icon ────────────────────────────────────────
echo "==> Building axedup.icns..."
python3 - "$TMP" <<'PYEOF'
import sys
from PIL import Image

tmp = sys.argv[1]
img = Image.open(f"{tmp}/icon-512.png").convert("RGBA")
img.save("axedup.icns", format="icns",
         sizes=[(16,16),(32,32),(48,48),(128,128),(256,256),(512,512)])
PYEOF

# ── 4. axedup.png — 512px for AppImage ───────────────────────────────────────
echo "==> Copying axedup.png (512px for AppImage)..."
cp "$TMP/icon-512.png" axedup.png

echo ""
echo "==> Done:"
ls -lh axedup.ico axedup.icns axedup.png
