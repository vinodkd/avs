# AxEdUp

Turn a day's action camera footage into a shareable video without learning video editing software.

AxEdUp reads files from an SD card or local folder, analyzes them with computer vision and telemetry data, walks you through a review workflow, assembles a finished video using sport-specific presets, and exports it ready for upload — all from a desktop GUI.

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

Download `AxEdUp-<version>-x86_64.AppImage` from [Releases](https://github.com/vinodkd/axedup/releases).

```bash
chmod +x AxEdUp-*.AppImage
./AxEdUp-*.AppImage
```

**Prerequisite** (only needed on minimal installs — already present on most Linux desktops):
```bash
sudo apt install libgtk-3-0 libwebkit2gtk-4.0-37
```

### Windows

Download `AxEdUp-<version>-Setup.exe` from [Releases](https://github.com/vinodkd/axedup/releases) and run it. Standard Next → Next → Install wizard; no dependencies required.

### macOS

Download `AxEdUp-<version>.dmg` from [Releases](https://github.com/vinodkd/axedup/releases). Open the DMG and drag `AxEdUp.app` to Applications. On first launch, right-click → Open to bypass the Gatekeeper unsigned-app warning (one time only).

---

## Supported cameras

| Camera | Video | Telemetry |
|---|---|---|
| GoPro (Hero 5+) | MP4 | GPMF (speed, GPS, accelerometer) |
| DJI Osmo Action | MP4 | SRT sidecar (speed, GPS, altitude) |
| Insta360 | MP4/MOV | Motion analysis only |
| Generic action cams | MP4/MOV | Motion analysis only |

---

## Build from source

**Requirements:** Python 3.10+, FFmpeg (system install or via `imageio-ffmpeg`), GTK3 + WebKit2GTK (Linux only)

```bash
git clone https://github.com/vinodkd/axedup.git
cd axedup
pip install -e .
axedup-ui        # launch the GUI
```

To build a local AppImage (Linux):
```bash
pip install pyinstaller
bash packaging/build_appimage.sh
# → dist/AxEdUp-<version>-x86_64.AppImage
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
