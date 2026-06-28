# Insta360: Ecosystem Analysis

## Devices
- **X4 / X3 / ONE X2** — 360-degree cameras (flagship line)
- **GO 3S / GO 3** — tiny wearable cameras (thumb-sized, magnetic mount)
- **Ace Pro 2 / Ace Pro** — flat action cameras (GoPro/DJI competitors)
- **ONE RS** — modular system (swap between 360, 1-inch wide, and 4K standard lenses)

## File Formats

### 360 Cameras (X series, ONE X2, ONE RS 360 lens)
- **`.INSV`** — proprietary dual-fisheye video (two separate streams, one per lens)
- **`.INSP`** — proprietary 360 photo format
- Must be stitched/processed before viewing in standard players
- Processed output: equirectangular MP4 or reframed standard MP4
- **Flowstate stabilization:** gyroscope-based, applied during processing (not in-camera)
- **Gyro log:** separate `.gyro` file or embedded — used for post-processing stabilization

### Flat/Standard Cameras (Ace Pro, GO 3, RS 4K lens)
- **`.MP4`** (H.264 / H.265)
- Flowstate applied in-camera or during app processing
- Telemetry: embedded GPS + IMU data

### Common to All
- **`.LRV`** — low-res proxy file for fast preview on mobile (auto-deleted after processing on some workflows)
- **`.THM`** — thumbnail
- Active HDR: proprietary HDR format, needs processing

## Native Editing Tools

### Insta360 App (Mobile — iOS/Android)
- **AI Editor**: uploads clips to Insta360 servers, uses AI to select best moments, assemble reel
- **Reframe**: for 360 footage — set keyframes to "direct" the camera after the fact. This is Insta360's killer feature.
- **Deep Track**: AI subject tracking — auto-reframe to keep subject centered through a 360 clip
- **PureShot / Active HDR processing**: HDR tone-mapping applied during export
- **Templates**: sport-specific styles with music sync
- **Log**: flat profile, requires LUT (similar to D-Log)
- Export up to 8K (360) or 4K (standard)

### Insta360 Studio (Desktop — Mac/Windows)
- Full 360 reframing with keyframe timeline
- Batch export: process multiple files with same settings
- Flowstate stabilization settings (horizon lock, etc.)
- Color grading: LUT import, basic color tools
- Plugins available for Premiere Pro and Final Cut Pro
- Required for serious 360 work — the mobile app's reframe is limited in precision

### Insta360 AI Reframe (Desktop add-on)
- Automated subject tracking for batch processing 360 → standard clips
- Useful for sports content where subject is always visible

## Camera WiFi / Control API
- **No official open API** — similar situation to DJI
- Insta360 Connect SDK: exists but requires developer partnership/licensing
- WiFi transfer: works within official app, limited to official app
- USB transfer: standard mass storage mode — files accessible directly
- Third-party tool: **OpenInsta360** (community project) — reverse-engineered some protocols
- Camera control via BLE: partially reverse-engineered by community

## Upload Paths
- **Insta360 community site**: niche platform, 360 photo/video hosting
- **YouTube**: supports 360 video via spatial metadata injection during export
- **Facebook**: supports 360 content
- **Instagram/TikTok**: 360 must be reframed to standard flat video first — cannot upload raw 360
- **No Strava integration**
- **Insta360 cloud storage**: available via subscription, stores original `.INSV` files

## Telemetry / Overlay Features
- GPS and IMU embedded in footage
- App shows speed, distance, elevation in playback
- **Overlay customization in app**: speed, altitude, compass, GPS map — more flexible than GoPro/DJI apps
- Deep Track uses IMU to smooth subject tracking — IMU data is used internally but not exposed as a data export
- Third-party: gyroflow supports Insta360 IMU data for stabilization

## Unique Technical Challenges

### Stitching Pipeline
Raw `.INSV` files are dual-fisheye — stitching into equirectangular or reframing into standard video requires:
1. Lens calibration data (model-specific)
2. Optical flow stitching for seamless seam
3. Flowstate gyro correction applied during stitch
4. Color matching between the two lenses
This is computationally heavy — Insta360 app offloads to phone GPU; Studio uses CPU/GPU on desktop.

### Reframing as Editing
The "direct the camera after the fact" paradigm is fundamentally different from standard video editing. You are setting a virtual camera path through a 360 sphere — keyframed pan/tilt/roll/fov. aVs would need to decide: support full 360 reframing, or convert to flat and treat like any other camera?

### File Size
360 files at full quality are enormous — 8K 30fps is ~600–800 MB/min. Proxy workflow (using LRV files for editing, then re-rendering final) is essential.

## Strengths for aVs
- Insta360's AI Editor and Deep Track show the category direction — AI-assisted editing is expected
- 360 reframing is a genuinely unique feature that no other brand offers
- GO 3 (wearable) footage has a very different feel — hands-free POV — worth a dedicated preset
- Strong community on YouTube around Insta360 tutorials — active base to market to

## Weaknesses / Challenges
- `.INSV` format is proprietary — requires either licensing Insta360 SDK or community reverse-engineering
- Stitching pipeline is complex and device-specific — different stitch parameters per camera model
- Reframing UX is non-trivial to build well — the keyframe metaphor confuses newcomers
- AI Editor requires cloud upload — privacy concern, bandwidth cost, latency
- Flat action cameras (Ace Pro) are a newer addition and feel less differentiated vs. GoPro/DJI
