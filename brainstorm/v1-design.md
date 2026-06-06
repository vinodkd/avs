# AxEdUp v1 — Design Document

## Summary

A desktop app (Mac-first) that reads action camera footage from an SD card, automatically analyzes it using computer vision and telemetry data, guides the user through a 3-pass review workflow, assembles a finished video using a sport-specific preset, and exports it for upload.

No LLM. No cloud. No camera WiFi. No mobile. SD card in → finished video out.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Desktop Shell (Tauri)                                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  React + TypeScript UI                               │   │
│  │  Screen 1: Import  →  2: Map  →  3: Marks  →  4: Review │ │
│  └────────────────────────┬─────────────────────────────┘   │
│                           │ Tauri IPC (invoke / events)     │
│  ┌────────────────────────▼─────────────────────────────┐   │
│  │  Rust layer (Tauri backend)                          │   │
│  │  - File system access, SD card detection             │   │
│  │  - Process management                                │   │
│  │  - OS integration (notifications, drag-drop)         │   │
│  └────────────────────────┬─────────────────────────────┘   │
└───────────────────────────│─────────────────────────────────┘
                            │ stdout / IPC
┌───────────────────────────▼─────────────────────────────────┐
│  Python Processing Backend                                   │
│                                                              │
│  Ingest      → Telemetry  → Scene       → Motion            │
│  (file scan)   (GPMF/SRT)   (PyScene)    (OpenCV)           │
│                                    │                         │
│                              Clip Candidates                 │
│                                    │                         │
│  Assembly    ← Sport Preset  ←  User Marks                  │
│  (FFmpeg)      (LUT + audio)                                 │
│       │                                                      │
│  Export (MP4, multi-resolution)                              │
└─────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  Local Storage                                               │
│  SQLite (sessions, clips, marks, user profile)               │
│  File cache (thumbnails, proxy files, LUTs, music)           │
└─────────────────────────────────────────────────────────────┘
```

---

## Technology Choices

### Desktop Shell: Tauri (Rust + WebView)

**What it is:** A framework for building native desktop apps with a web frontend. Uses the OS's native WebView (WKWebView on macOS, WebView2 on Windows) rather than bundling a full Chromium instance like Electron does.

**Why Tauri over Electron:**
- Bundle size: ~10MB vs ~150MB — meaningful for a download
- Memory: significantly lower at runtime — important when ffmpeg is already using RAM
- Performance: native WebView on Apple Silicon is hardware-accelerated
- Rust backend handles file system, subprocess management, and OS events safely and fast

**Why not native Swift/SwiftUI:**
- Cross-platform is valuable — Windows action sports users exist
- Tauri gets 90% of the native feel with 50% of the platform lock-in

**Tauri's role in this app:**
- Detect SD card mount/unmount events
- Read/write local file system (SD card, cache directory, SQLite)
- Spawn and manage the Python processing subprocess
- Bridge between UI events and Python processing via IPC
- Handle OS-level things: dock icon, menu bar, system notifications, file drag-drop

### UI: React + TypeScript

**Why React:** Mature ecosystem, good component libraries, strong TypeScript support. The UI is complex enough (multiple screens, real-time progress updates, video player, thumbnail grids) to justify a component framework over vanilla JS.

**Key libraries:**
- `react-player` or native HTML5 `<video>` for the review player
- `@tanstack/react-query` for async state from the Tauri IPC layer
- `zustand` for local UI state (which clips are marked, current screen, etc.)
- A UI component library — **shadcn/ui** (Tailwind-based, unstyled primitives, good for custom design) or **Radix UI**

**Why TypeScript specifically:**
Video timecodes, clip metadata, telemetry data structures, and user profiles all have complex shapes. TypeScript prevents a class of bugs (wrong timecode format, missing fields) that would otherwise only surface at runtime.

### Processing Backend: Python

**Why Python for processing, not Rust:**
- FFmpeg, OpenCV, and PySceneDetect all have mature, well-maintained Python bindings
- The video processing domain is Python-native — most tooling, documentation, and examples assume Python
- Iteration speed: changing an ffmpeg filter chain or tuning a scene detection threshold is much faster in Python than Rust
- Not a performance bottleneck: the actual heavy lifting is done by ffmpeg (C) and OpenCV (C++) — Python is just the orchestrator

**Communication between Tauri and Python:**
- Python process launched at app startup as a subprocess
- Communication via stdin/stdout using newline-delimited JSON messages (simple, reliable, no additional dependencies)
- Progress events streamed from Python → Tauri → React UI as processing runs
- Alternatively: Python runs a local socket server; Tauri connects to it. More robust for long-running jobs.

### Video Processing: FFmpeg

The foundation of all video work in AxEdUp. Every operation routes through FFmpeg:

| Operation | FFmpeg approach |
|---|---|
| Thumbnail extraction | `ffmpeg -ss [time] -i input.mp4 -vframes 1 thumb.jpg` |
| Proxy generation | Scale to 480p H.264 for fast scrubbing |
| Scene score per frame | `showinfo` filter to get frame metadata |
| Color grading | `lut3d` filter with `.cube` LUT files |
| Clip cutting | `-ss` / `-to` with `-c copy` for fast trim |
| Assembly | `concat` demuxer for joining clips |
| Audio mixing | `amix` + `loudnorm` + `sidechaincompress` for ducking |
| Export | H.264 or H.265, target bitrate per platform |

**ffmpeg-python** (Python bindings): provides a fluent API for building FFmpeg command chains programmatically. Avoids string-manipulation bugs in CLI construction.

### Scene Detection: PySceneDetect

**What it does:** Takes a video file, outputs a list of scene boundaries (timestamps where the content changes significantly).

**How it works:** Compares adjacent frames using color histogram difference (`ContentDetector`) or brightness thresholds (`ThresholdDetector`). Fast — typically processes 1 hour of footage in under 2 minutes.

**Why not just OpenCV directly:** PySceneDetect is purpose-built for this, handles edge cases (flash frames, slow fades), and outputs clean timestamps. Using raw OpenCV would mean reimplementing what PySceneDetect already does well.

**Output used for:** Scene boundary markers on the Footage Map (Pass 1), natural cut points for clip selection (Pass 2).

### Motion Analysis: OpenCV

**What it does:** Measures how much is happening in each second of video — useful for identifying high-action moments independently of telemetry.

**Method: Dense Optical Flow (Farneback algorithm)**
- Computes per-pixel motion vectors between consecutive frames
- Aggregates into a scalar "motion intensity" value per frame
- Downsampled to per-second average for the telemetry graph

**Why this matters:** Telemetry (speed, GPS) identifies what the *camera* was doing. Optical flow identifies what's happening *in the frame* — useful for mounted cameras where the camera is stationary but the subject is moving fast, or for shots where speed isn't the relevant signal (a crash, a trick, a near-miss).

**Performance note:** Dense optical flow on full 4K frames is slow. Process on the proxy (480p) — the motion signal is valid at low resolution and processes ~10x faster.

### Telemetry Parsing

**GoPro — GPMF (GoPro Metadata Format):**
- Embedded as a binary metadata track in the MP4 container
- Contains: GPS coordinates, speed (m/s), altitude (m), 3-axis accelerometer, 3-axis gyroscope, camera orientation, audio levels
- Library: `gopro-telemetry` (Node.js, can be called from Python via subprocess) or Python port `gpmf-parser`
- Output: time-series JSON keyed by timestamp

**DJI — SRT sidecar file:**
- Plain text file alongside the MP4 with the same filename
- Format: SRT subtitle format, each entry contains timestamp + JSON payload with lat/lon/altitude/speed/ISO/EV
- Parsing: simple regex / standard SRT parser, no special library needed
- Limitation: no accelerometer or gyro data — only GPS-derived metrics

**Insta360 (flat cameras — Ace Pro, GO 3):**
- Metadata embedded in MP4, format partially documented
- Defer detailed support to v2; use GPS/speed where available
- Fallback: PySceneDetect + optical flow alone if telemetry can't be parsed

**Unified telemetry model (internal):**
All three sources are normalized into the same internal structure:
```
TelemetryPoint {
  timestamp_ms: int
  speed_kmh: float | null
  altitude_m: float | null
  lat: float | null
  lon: float | null
  accel_magnitude: float | null   // from GPMF only
  motion_intensity: float | null  // from OpenCV (all cameras)
}
```

### Local Storage: SQLite

**Why SQLite:** Single-file database, no server process, ships with Python's standard library. Perfect for a local desktop app storing session state, user preferences, and clip metadata.

**Schema (simplified):**

```sql
sessions (id, date, camera_brand, source_path, processed_at, sport, duration_s)

clips (id, session_id, filename, start_ms, end_ms, scene_count, peak_speed, peak_altitude, peak_motion)

marks (id, clip_id, in_ms, out_ms, confidence, source, accepted)
-- source: 'telemetry_peak' | 'motion_peak' | 'user'
-- confidence: 0.0–1.0 (AI picks) or null (user pick)

user_profile (id, sport, preferences_json, created_at, updated_at)

exports (id, session_id, exported_at, platform, duration_s, filepath)
```

### Sport Presets

Stored as structured data files, not code. Each preset bundles:

```
SportPreset {
  id: "mtb" | "surf" | "ski" | "skydive" | "moto" | "trail" | "cycling"
  color: {
    lut_file: "mtb_punchy.cube"    // .cube LUT applied via ffmpeg lut3d filter
    saturation_boost: 1.2
    contrast_boost: 1.1
  }
  music: {
    genre_tags: ["rock", "metal", "hip-hop"]
    energy: "high"
    bundled_tracks: ["mtb_01.mp3", "mtb_02.mp3", "mtb_03.mp3"]
  }
  edit: {
    target_duration_youtube_s: 240     // 4 min
    target_duration_short_s: 45
    cut_rhythm: "fast"                 // informs minimum/maximum clip length
    min_clip_s: 2
    max_clip_s: 15
  }
  overlays: {
    speed: true
    altitude: true
    gps_map: false
    heart_rate: false
  }
  telemetry_thresholds: {
    speed_peak_kmh: 30        // speeds above this are "interesting"
    accel_spike_g: 1.5        // G-force spikes above this are "interesting"
    motion_intensity: 0.6     // optical flow score above this is "interesting"
  }
}
```

LUT files (`.cube`) are included in the app bundle — small files (~500KB each). Music tracks are bundled as well (~3–5 per sport, royalty-free Creative Commons licensed).

### Export

FFmpeg handles all export. Target specs per platform:

| Platform | Resolution | Codec | Bitrate | Aspect | Audio |
|---|---|---|---|---|---|
| YouTube | 4K or 1080p | H.264 | 20 Mbps | 16:9 | AAC 192kbps |
| YouTube Shorts | 1080p | H.264 | 8 Mbps | 9:16 | AAC 192kbps |
| Instagram Reel | 1080p | H.264 | 8 Mbps | 9:16 | AAC 192kbps |
| TikTok | 1080p | H.264 | 8 Mbps | 9:16 | AAC 192kbps |
| Strava | 1080p | H.264 | 8 Mbps | 16:9 | AAC 128kbps |

v1 exports to file. Direct platform upload (via API) is v2.

---

## Processing Pipeline — Detailed Flow

### Stage 1: Ingest (on SD card insert)

```
SD card detected
  → Scan for video files: .MP4, .MOV, .LRV (GoPro proxy), .THM (thumbnails)
  → Detect camera brand from:
      filename pattern  (GH/GX/GOPR = GoPro, DJI_ = DJI, VID_ = Insta360)
      container metadata (make/model in MP4 headers)
  → Group GoPro chapter files (GH010001.MP4, GH020001.MP4 → same session)
  → For each clip:
      extract duration, resolution, framerate, codec
      check for .SRT sidecar (DJI)
      extract GPMF track presence (GoPro)
  → Persist session + clip records to SQLite
```

### Stage 2: Analysis (background, while user sees progress)

For each clip, in parallel:

```
Telemetry extraction
  GoPro: parse GPMF binary track → TelemetryPoint[]
  DJI:   parse .SRT sidecar → TelemetryPoint[]
  Other: GPS from MP4 metadata if present

Thumbnail generation (FFmpeg)
  One frame every 5 seconds → JPEG → cache/thumbnails/[clip_id]/

Proxy generation (FFmpeg)
  480p H.264, fast encode → cache/proxies/[clip_id].mp4
  (used for OpenCV motion analysis and scrub preview)

Scene detection (PySceneDetect on proxy)
  ContentDetector, threshold=27 (tunable per sport)
  → list of scene boundaries with timestamps

Motion analysis (OpenCV on proxy)
  Farneback dense optical flow, sampled every 0.5 seconds
  → motion intensity time-series

Peak detection (Python, on combined telemetry + motion signal)
  Find local maxima above sport preset thresholds
  Merge overlapping peaks into candidate regions (in_ms, out_ms)
  Score each candidate (0.0–1.0) by peak magnitude
  → Marks saved to SQLite with source='telemetry_peak' or 'motion_peak'
```

### Stage 3: User Review — Pass 1 (Footage Map)

No processing here. UI renders the pre-computed data:
- Thumbnails → scrollable strip
- Telemetry + motion intensity → SVG chart below thumbnails
- Scene boundaries → vertical dividers on the strip
- Candidate marks → highlighted regions

### Stage 4: User Review — Pass 2 (Clip Marks)

User accepts/rejects/adjusts AI candidates. Any adjustments written back to SQLite.
Final set of accepted marks = the edit list.

### Stage 5: Assembly (FFmpeg, triggered on "Assemble →")

```
Sort accepted marks by original timestamp (chronological default)

For each mark:
  ffmpeg -ss [in_ms] -to [out_ms] -i [source.mp4] -c copy [tmp_clip_N.mp4]

Load sport preset:
  Select music track (random from sport bundle, or user-selected)
  Load .cube LUT file path

Build ffmpeg assembly command:
  concat demuxer for all tmp clips
  lut3d filter for color grade
  eq filter for saturation/contrast tweaks
  amix for music + original audio
  loudnorm on original audio
  sidechaincompress for music ducking under loud original audio

Overlay generation (if telemetry present):
  Generate overlay video (black bg, speed/altitude text at timestamps)
  overlay filter to composite onto main video

Encode to cache/preview/[session_id]_preview.mp4 (1080p)
```

### Stage 6: User Review — Pass 3 (Review Player)

User watches the assembled preview. Refinement instructions handled as:

| Instruction | Action |
|---|---|
| "This clip is too long" | Shorten the mark's out_ms by 30%, re-assemble affected section |
| "Remove this clip" | Delete the mark, re-assemble |
| "Try different music" | Pick next track from sport bundle, re-mix audio only |
| "More cinematic color" | Swap LUT file, re-apply color grade, re-encode |
| "Remove speed overlay" | Disable overlay flag in session, re-assemble |

For v1 these refinements are handled via UI controls (buttons/sliders), not text input. Text/voice input is a v2 addition.

### Stage 7: Export

User selects target platforms. FFmpeg re-encodes the approved preview to each target spec. Files saved to ~/Movies/AxEdUp/[session_date]/.

---

## Data Flow Summary

```
SD Card
  → [Ingest] → SQLite (clips, metadata)
  → [Analysis] → SQLite (marks, scores) + File cache (thumbnails, proxies)
  → [User: Pass 1] → (no new data, just display)
  → [User: Pass 2] → SQLite (accepted marks, user adjustments)
  → [Assembly] → File cache (preview MP4)
  → [User: Pass 3] → SQLite (refinement log)
  → [Export] → ~/Movies/AxEdUp/ (final MP4s)
```

---

## What's Explicitly Out of Scope for v1

| Feature | Why deferred |
|---|---|
| Text/voice brief input | Requires LLM layer; v2 addition |
| Camera WiFi import | Requires per-brand SDK work; add after SD card is solid |
| Direct platform upload | Platform OAuth complexity; v2 |
| 360 footage | Different pipeline entirely; AxEdUp360 |
| Windows support | Mac-first to validate; Tauri makes Windows easy to add later |
| Multi-day trip sessions | Session grouping logic; v2 |
| User preference learning | Need session history first; v2 |
| Preset marketplace | Need users first; v2 |
| Custom music import | Royalty licensing complexity; v2 |

---

## Open Questions for v1 Build

1. **Proxy strategy:** Generate proxies eagerly (at ingest) or lazily (on demand)? Eager is faster for UX but uses more disk space.
2. **Scene detection threshold:** ContentDetector threshold=27 is PySceneDetect's default. Action footage (lots of motion blur, rapid cuts) may need tuning per sport.
3. **Music licensing:** Which Creative Commons / royalty-free sources for the bundled tracks? Freesound.org, ccMixter, Free Music Archive are candidates.
4. **LUT sources:** Create custom LUTs or adapt from open-source packs? Several well-regarded free LUT packs exist for each style.
5. **Chapter file joining:** GoPro splits recordings into ~4GB chapter files. Should AxEdUp join these transparently into a single virtual clip for the UI, or expose them as separate clips?

---

## Build Order

1. Python processing backend (standalone, CLI-testable):
   - Ingest + camera detection
   - GPMF parser (GoPro) + SRT parser (DJI)
   - PySceneDetect integration
   - OpenCV motion analysis
   - Peak detection + candidate mark generation
   - FFmpeg assembly with LUT + audio mix

2. SQLite schema + Python ORM layer

3. Tauri shell + React UI scaffolding

4. Screen 1: Import (SD card detection, session display)

5. Screen 2: Footage Map (thumbnail strip + telemetry chart)

6. Screen 3: Clip Marks (candidate cards, accept/reject)

7. Screen 4: Review Player (assembled preview, refinement controls)

8. Screen 5: Export (format selection, file output)

9. Sport presets (LUTs, music, thresholds) — one complete sport to start (MTB)
