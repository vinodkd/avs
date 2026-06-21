# DJI: Ecosystem Analysis

## Devices
- **Osmo Action 4 / 5 Pro** — primary action cameras (GoPro competitors)
- **Osmo Pocket 3** — compact gimbal camera, vlog-oriented
- **Osmo Mobile 6/7** — smartphone gimbal (not a camera, but relevant for the app ecosystem)
- Note: DJI drones (Mini, Air, Mavic) use the same apps and file formats — drone footage is a natural pairing with action cam footage for adventure content

## File Formats
- **Video:** `.MP4` (H.264 / H.265 / HEVC), `.MOV` on some models
- **Photos:** `.JPG`, `.DNG` (RAW on Pro models)
- **D-Log / D-Log M**: flat color profile for grading — common on Osmo Action 4/5 Pro
- **Telemetry:** Embedded in MP4 as SRT subtitles (`.SRT` sidecar file) or via DJI's proprietary metadata track
  - SRT contains: timestamp, latitude, longitude, altitude, distance, speed, ISO, shutter, EV
  - Less rich than GoPro's GPMF — no accelerometer/gyroscope in SRT
  - Newer models embed more data in MP4 metadata directly
- **Stabilization:** RockSteady (electronic), HorizonSteady (horizon lock) — applied in-camera, no external processing needed

## Native Editing Tools

### DJI Mimo (Mobile — iOS/Android)
- Primarily for Osmo Pocket and Osmo Mobile devices
- Templates, auto-edit, basic trim and arrange
- Story Mode: guided shooting + auto-assembly
- Limited to DJI-recorded content

### DJI Fly (Mobile/Desktop — iOS/Android/Windows/Mac)
- Primarily for drone footage editing
- SkyMasters AI editing: auto-cut to music, color grading templates
- Can handle Osmo Action footage but not the primary use case
- Desktop version has more timeline control

### LightCut (Mobile — iOS/Android)
- DJI's newest dedicated editing app (2022+)
- AI-driven auto-edit: scene detection, beat sync with music
- Templates and style presets
- Handles both action cam and drone footage
- More polished than Mimo for pure editing
- Export up to 4K
- No subscription required (free, unlike GoPro Quik full features)

### DJI Studio (Desktop concept — part of DJI's roadmap)
- DJI has historically not had a strong desktop story beyond DJI Fly
- Most serious DJI users migrate to DaVinci Resolve or Premiere for D-Log grading

## Camera WiFi / Control API
- **No official open API** — this is DJI's biggest gap vs. GoPro
- DJI MSDK (Mobile SDK): available for licensed app developers, requires NDC agreement
- Osmo Action cameras connect via WiFi and Bluetooth for preview and file transfer via the official apps only
- Third-party file access is possible via USB mass storage mode or SD card
- No BLE control API comparable to Open GoPro

## Upload Paths
- **DJI Sky Pixel**: DJI's own social platform — niche, adventure/drone community
- **YouTube**: from LightCut/DJI Fly via share sheet
- **Instagram/Facebook/TikTok**: via share sheet after export — no deep integration
- **No Strava integration**
- DJI does not have a cloud storage subscription for footage (unlike GoPro Plus)

## Telemetry / Overlay Features
- SRT files are easy to parse — latitude/longitude/altitude/speed in plain text
- Third-party tools (DJI SRT Viewer, Dashware) can create overlays from SRT
- No official overlay tool within DJI apps beyond basic speed display
- D-Log footage requires LUT application before sharing — most users apply DJI's own LUTs
- GPS track can be exported for mapping but requires manual workflow

## Strengths for aVs
- SRT telemetry format is simple to parse (plain text)
- D-Log flat profile footage looks great after a LUT — automatic LUT application is a clear value-add
- LightCut is newer and more open than Quik — less locked-in community
- Drone + action cam combined editing is a natural use case (outdoor adventures always mix both)
- No subscription model to compete with — DJI doesn't charge for cloud

## Weaknesses / Challenges
- No open camera control API — can't pull files programmatically over WiFi without MSDK license
- Telemetry (SRT) is less comprehensive than GoPro GPMF — no accelerometer/gyro
- D-Log/HLG footage is non-trivial for non-technical users — needs automatic LUT handling
- DJI's ecosystem is more drone-centric; action camera users feel like second-class citizens in DJI apps
- File naming conventions differ across camera models
