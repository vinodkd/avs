# GoPro: Ecosystem Analysis

## Devices
- Hero series (13, 12, 11, etc.) — standard action cameras
- MAX / MAX Lens Mod — 360-degree and ultra-wide capture
- Volta, remote, accessories ecosystem

## File Formats
- **Video:** `.MP4` (H.264 / H.265), `.360` (proprietary dual-fisheye for MAX)
- **Photos:** `.JPG`, `.GPR` (GoPro RAW, DNG-compatible)
- **Chapters:** Long clips are split into ~4GB chapter files (GH010001.MP4, GH020001.MP4...) that belong to the same recording session
- **Telemetry:** Embedded in MP4 via GPMF (GoPro Metadata Format) — GPS, accelerometer, gyroscope, speed, altitude, heart rate (if connected)
- **Highlight tags:** HiLight markers stored as metadata in the file

## Native Editing Tools

### GoPro Quik (Mobile — iOS/Android)
- Auto-edit: selects best clips and assembles a highlight reel with music
- Manual edit: trim, arrange, transitions, text, speed ramps
- Mural: syncs all footage to a cloud timeline
- Subscription (GoPro Plus) required for full feature access and unlimited cloud storage
- Exports up to 4K
- Auto-upload to GoPro cloud when connected to WiFi

### GoPro Player (Desktop — Mac/Windows)
- Required for viewing `.360` files natively
- ReelSteady Go integration for advanced stabilization
- Horizon leveling for MAX footage
- Export to standard MP4
- Not a full NLE — limited editing beyond playback and reframe

### GoPro Quik Desktop (Desktop)
- Essentially a desktop version of the mobile Quik app
- Cloud sync with mobile
- Less capable than dedicated desktop editors

## Camera WiFi / Control API
- **Open GoPro API**: BLE + WiFi API, officially supported and documented
- Can control camera remotely, pull media list, download files, configure settings
- Enables third-party apps to treat GoPro as a first-class source
- Live streaming: supported over WiFi (RTMP) to YouTube, Facebook, etc.

## Upload Paths
- **GoPro Plus cloud**: auto-upload, stores original quality files
- **YouTube**: direct from Quik app (standard and 360 via YouTube 360 metadata)
- **Instagram/Facebook**: via share sheet from Quik
- **No native TikTok integration**: must export then share manually
- **No native Strava integration**: telemetry data not pushed to Strava automatically

## Telemetry / Overlay Features
- GoPro Telemetry Overlay (third-party, open source) can extract GPMF data to create gauges
- Quik app shows speed/distance but limited overlay customization
- GoPro Player can burn in some telemetry
- Full GPMF spec is public — GPS, speed (m/s), altitude (m), 3-axis accel/gyro, camera orientation, audio levels

## Strengths for AxEdUp
- Open GoPro API is well-documented — easiest to integrate of the three brands
- GPMF telemetry is comprehensive and spec is public
- Chapter file detection is a known problem with a known solution (join by session ID in metadata)
- Huge user base — largest action camera community

## Weaknesses / Challenges
- GoPro Plus subscription model may conflict with a third-party app
- `.360` format requires special handling (dual fisheye → equirectangular → reframe pipeline)
- HiLight tags are useful but rarely exposed outside the GoPro ecosystem
- Quik auto-edit quality is inconsistent — users often redo it manually
