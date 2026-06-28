# aVs

Turn a day's action camera footage into a shareable video without learning video editing software.

aVs reads files from an SD card or local folder, analyzes them with computer vision and telemetry data, walks you through a review workflow, assembles a finished video using sport-specific presets, and exports it ready for upload — all from a desktop GUI.

**Status:** Early beta. Core pipeline (ingest → analyze → pick → assemble → export) works end-to-end. Installers available for Linux, Windows, and macOS.

---

## How it works

1. **Load** — point it at an SD card or folder; it finds your clips and extracts metadata
2. **Analyze** — generates proxy files, detects scenes, computes motion intensity from optical flow; GoPro/DJI telemetry (speed, GPS) used when available
3. **Review** — browse clips as thumbnails rated by activity score; mark which ones to include
4. **Assemble** — combines selected clips, applies a color grade and music from a sport preset, renders a preview
5. **Export** — final H.264 encode in one or more aspect ratios (16:9, 9:16, 1:1)

No timeline scrubbing, no effects panels, no keyframing. The computer edits; you approve.

---

## Install

### Linux

Download `aVs-<version>-x86_64.AppImage` from [Releases](https://github.com/vinodkd/avs/releases).

```bash
chmod +x aVs-*.AppImage
./aVs-*.AppImage
```

**Prerequisite** (only needed on minimal installs — already present on most Linux desktops):
```bash
sudo apt install libgtk-3-0 libwebkit2gtk-4.0-37
```

### Windows

Download `aVs-<version>-Setup.exe` from [Releases](https://github.com/vinodkd/avs/releases) and run it. Standard Next → Next → Install wizard; no dependencies required.

### macOS

Download `aVs-<version>.dmg` from [Releases](https://github.com/vinodkd/avs/releases). Open the DMG and drag `aVs.app` to Applications. On first launch, right-click → Open to bypass the Gatekeeper unsigned-app warning (one time only).

---

## Supported cameras

| Camera | Video | Telemetry |
|---|---|---|
| GoPro (Hero 5+) | MP4 | GPMF (speed, GPS, accelerometer) |
| DJI Osmo Action | MP4 | SRT sidecar (speed, GPS, altitude) |
| Insta360 | MP4/MOV | Motion analysis only |
| Generic action cams | MP4/MOV | Motion analysis only |

---

## CLI usage

For power users who prefer the terminal. The review step requires the NiceGUI UI
(launch with `avs ui`); all other steps work entirely from the command line.

```bash
# 1. Import footage from an SD card or folder
avs ingest /media/SDCARD/DCIM --sport mtb
# → prints session ID, clip count, duration, camera brand

# 2. Analyze (proxy build → scene detection → motion peaks)
avs analyze <session_id>          # full (default)
avs analyze <session_id> --jpg    # ~15× faster, less precise
# → rich progress bars; Ctrl-C cancels cleanly

# 3. Review clips (launches UI; use avs ui first if not running)
avs review <session_id>
# → prints the URL for the session in the NiceGUI UI
avs ui                            # start the UI server (port 8765 by default)

# 4. Assemble a preview from accepted clips
avs assemble <session_id>
avs assemble <session_id> --source jpg    # only quick-scan marks
avs assemble <session_id> --source proxy  # only full-scan marks

# 5. Refine and re-assemble
avs refine <session_id> --grade cinematic
avs refine <session_id> --swap-music
avs refine <session_id> --remove <mark_id>
avs refine <session_id> --no-overlay

# 6. Export to final files
avs export <session_id>                              # 16:9 only (default)
avs export <session_id> --aspect 16:9 --aspect 9:16 # both orientations

# Session management
avs sessions                   # list all sessions
avs sessions --status ready    # filter by status

# Sport profiles
avs profile mtb                              # show active settings
avs profile mtb --grade cinematic            # change default grade
avs profile surf --music-energy chill        # change music energy
```

---

## Build from source

**Requirements:** Python 3.10+, FFmpeg (system install or via `imageio-ffmpeg`), GTK3 + WebKit2GTK (Linux only)

```bash
git clone https://github.com/vinodkd/avs.git
cd avs
pip install -e .
avs-ui        # launch the GUI
```

To build a local AppImage (Linux):
```bash
pip install pyinstaller
bash packaging/build_appimage.sh
# → dist/aVs-<version>-x86_64.AppImage
```

To regenerate icons after editing `packaging/icon.svg`:
```bash
bash packaging/make_icons.sh
```

---

## Tech

Python 3.10+ · [NiceGUI](https://nicegui.io) · FFmpeg via [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) · [OpenCV](https://opencv.org) · [PySceneDetect](https://scenedetect.com) · SQLite via SQLAlchemy · PyInstaller

No GPU required. All processing runs on CPU.

---

## License

TBD
