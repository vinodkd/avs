# aVs v1 — Requirements

## Problem Statement

Action camera enthusiasts end the day with raw footage on an SD card and want a shareable video before they go to sleep. Current tools are siloed to one camera brand, require video editing expertise, or both. The editing process has three natural passes — overview, marking, assembly — and no existing tool makes all three fast and low-friction across GoPro, DJI, and Insta360 cameras.

## Target User

An action sports enthusiast who:
- Films with GoPro, DJI Osmo, or Insta360 cameras
- Wants a finished video shareable to YouTube or Instagram within an hour of finishing
- Does not want to learn video editing software
- Is editing at the end of the day, at home, SD card in hand

## Context

**End-of-day editing session.** Not at the trailhead, not on a phone. The user is home, sitting at a computer, SD card available. Speed and low cognitive load are the priorities.

**aVs is a review-and-approve tool, not a video editor.** The computer does the editing; the user directs and approves. This distinction shapes every UI and workflow decision.

---

## Build Phases

### Phase 1 — CLI Pipeline (current)
Prove the core pipeline works on real footage before building any UI.
All interaction via command line. Review step uses a generated static HTML page.

### Phase 2 — NiceGUI + LLM
Add a minimal Python-native browser UI (NiceGUI) on top of the same pipeline.
Add text input via a local Ollama LLM for brief-based clip selection.

### Phase 3 — Form Factor Decision
Once the workflow is validated, decide on the final UI: NiceGUI stays, Flutter for cross-platform mobile, or another approach. The pipeline code is reusable regardless.

---

## Functional Requirements

### FR-1: Session Import
- Accepts a path to an SD card or any local folder containing video files
- Supports MP4 and MOV files from GoPro, DJI Osmo, and Insta360 cameras
- Detects camera brand from filename patterns and MP4 container metadata
- Groups GoPro chapter files (split recordings) into a single logical clip
- Extracts clip metadata: duration, resolution, framerate, codec

### FR-2: Telemetry Extraction
- Parses GoPro GPMF telemetry embedded in MP4 (speed, altitude, GPS, accelerometer)
- Parses DJI SRT sidecar files (speed, altitude, GPS)
- Falls back gracefully to motion-only analysis when telemetry is absent (Insta360, unknown)
- Normalizes all sources to a common internal format

### FR-3: Automated Analysis
- Generates 480p proxy video per clip (all analysis runs on proxies, never originals)
- Generates one thumbnail per 5 seconds
- Detects scene boundaries (PySceneDetect)
- Computes per-second motion intensity (OpenCV dense optical flow on proxy)
- All analysis CPU-only — no GPU required

### FR-4: Footage Map — Pass 1
- CLI: prints session summary (clip count, duration, camera brand, detected peaks)
- Phase 2 UI: scrollable thumbnail strip with telemetry graph and scene markers

### FR-5: Clip Marking — Pass 2
- Pre-marks candidate regions based on telemetry peaks, motion intensity, audio spikes
- CLI: prints candidate table, user accepts/rejects interactively; or generates static HTML review page
- Phase 2 UI: card-based review interface with accept/reject/trim per candidate
- Output: ordered list of accepted clip regions with in/out timestamps

### FR-6: Sport Profile
- First-use asks one question: what sport?
- Supported: MTB, surfing, skiing/snowboarding, skydiving, motorcycling, trail running, road/gravel cycling
- Each sport provides: target duration, color grade, music energy/genre, overlay preferences, telemetry thresholds
- Preferences update over time from user refinements

### FR-7: Video Assembly
- Assembles accepted clips in chronological order
- Applies sport profile color grade (FFmpeg eq/colorbalance filters; LUT files are a possible future upgrade)
- Optionally adds background music with auto-ducking; user provides their own track via `--music /path/to/track.mp3`
- Renders telemetry overlays (speed, altitude) if data present and enabled
- Produces 1080p H.264 preview

### FR-8: Review and Refinement — Pass 3
- CLI: plays preview with system video player; refinement via follow-up commands
- Phase 2 UI: inline video player with coarse refinement controls (remove clip, swap music, toggle overlay, change grade)
- Re-renders only the affected section where possible

### FR-9: Export
- Exports to local folder (~/Videos/aVs/)
- 16:9 (YouTube) and/or 9:16 (Reels/Shorts/TikTok) in one pass
- H.264 (libx264) encoding — no H.265, no GPU codecs in v1
- File export only — no direct platform upload in v1

### FR-10: Session Persistence
- All session state stored in local SQLite database
- Resume interrupted sessions
- Export history recorded

### FR-11: Text Brief Input (Phase 2)
- User types a plain English description of what they want
- Local Ollama LLM (Phi-3.5 Mini or Llama 3.2 3B) interprets the brief
- LLM receives: brief text + structured clip metadata (not video)
- LLM outputs: structured edit plan adjusting candidate selection and ordering
- Ollama is a required separate install; model is a one-time download (~2GB)
- Falls back to automated candidate selection if Ollama is not running

---

## Non-Functional Requirements

### NFR-1: Performance (CPU-only Linux)
- Footage map ready within 5 minutes for a 45-minute session on a mid-range CPU
- All analysis on 480p proxy — never on originals
- Preview assembly under 2 minutes for a 4-minute output on CPU

### NFR-2: Platform
- Development and primary target: Linux
- Cross-platform by design: `pathlib.Path` everywhere, `imageio-ffmpeg` for bundled FFmpeg, `watchdog` for filesystem events
- Mac and Windows added later without significant rework

### NFR-3: File Safety
- Original files on SD card or source folder never modified or deleted
- Intermediates (proxies, thumbnails, previews) written to a local cache directory
- Exports written to a separate output directory

### NFR-4: No External Services
- Runs entirely offline (Ollama runs locally)
- No cloud APIs, no user accounts, no analytics
- No hosted backend

### NFR-5: Resilience
- Corrupt or unreadable clips skipped with a warning — app does not crash
- Interrupted analysis resumes from last completed step on next run

---

## Out of Scope for v1

| Feature | Reason deferred |
|---|---|
| FastAPI / REST API | Too heavy for prototype; revisit if mobile thin-client becomes real |
| React frontend | Same — NiceGUI covers the prototype UI need in pure Python |
| Camera WiFi / BLE import | Per-brand SDK complexity; SD card covers the use case |
| Direct upload to platforms | Platform OAuth complexity |
| 360 footage (INSV) | Different pipeline — tracked as aVs360 |
| Mobile builds | Desktop first; Flutter is the likely path when this becomes real |
| Cloud / hosted backend | Not a goal |
| Multi-day trip sessions | Session grouping complexity — v2 |
| Bundled music library | Licensing/redistribution complexity; user provides their own track instead |
| In-app CC0 music browser | Phase 2 UI feature — browse and select tracks from online CC0 sources |
| Preset marketplace | Needs user base first |
| Windows / Mac builds | Cross-platform by design; add after Linux is solid |
| Frame-precise timeline editing | Contradicts the "not a video editor" principle |
| Session deletion with artifact cleanup | Artifacts (proxies, thumbnails) are keyed by clip UUID, not source filename — a new session for the same video will get a new UUID and regenerate them anyway, so old artifacts from abandoned sessions are orphaned. A `clean` command should let the user delete a session and optionally its artifacts. Deferred until the happy path is solid. |
| Clip ID keyed to video file not session | Currently clip IDs are random UUIDs assigned at ingest, so artifacts are never reused across sessions for the same file. Keying on `sha256(filename + filesize)[:32]` would allow artifact reuse and make the `clean` command simpler. Requires upsert logic on ingest and a schema change. |
| Decouple assemble/export/review from CLI | `assemble`, `export`, and `review` pipeline functions still accept a `console: Console` parameter (CLI-coupled). Refactor them to use the same `on_event` callback pattern as `analyze_session`, then give the CLI its own rich renderer for each — same pattern already done for analysis. |
