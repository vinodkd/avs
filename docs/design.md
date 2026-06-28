# aVs v1 — Design Document

## What This Is

A Python CLI tool that processes action camera footage from an SD card, automatically identifies interesting moments using computer vision and telemetry data, assembles a finished video using sport-specific presets, and exports it ready for upload. A minimal NiceGUI interface and local LLM text input are added in Phase 2 on top of the same pipeline.

**Core principle:** aVs is a review-and-approve tool, not a video editor. The computer does the editing; the user directs and approves. This shapes every architecture and UX decision.

---

## Design History and Decision Log

This section captures the key debates and why we landed where we did. The `/brainstorm/` folder has the full exploration.

### Why not a mobile app first?
The 3-pass editing workflow (overview, mark, assemble) requires seeing thumbnails, reviewing clips, and watching a preview. Mobile screen real estate and processing power are constraints. The end-of-day editing session happens at a desk. Desktop first validates the workflow; mobile comes later once the core idea is proven.

### Why not camera WiFi / BLE integration in v1?
Each camera brand (GoPro, DJI, Insta360) has a different API surface. GoPro has an open API; DJI requires a licensed SDK; Insta360 has limited third-party access. SD card is universal, has zero API dependencies, and covers the end-of-day use case. Camera integrations are added later as the first source of files, not a requirement for proving the pipeline works.

### Why not FastAPI + React?
Originally designed as a local web app (FastAPI serving a React frontend in the browser). Rejected for the prototype because: two separate codebases (Python and TypeScript), heavy scaffolding before any pipeline validation, and the browser-as-desktop-app pattern feels wrong for a tool where the primary interaction is watching video. CLI first proves the pipeline; NiceGUI adds just enough UI in pure Python. FastAPI revisited only if a tablet thin-client becomes a real requirement.

### Why not Electron or Tauri?
Electron bundles ~150MB of Chromium. Tauri on Linux depends on WebKitGTK, which has known rendering issues on some distros. Both require JavaScript/TypeScript for the frontend. For a prototype on a Linux dev machine, neither is justified. If the final form factor needs a native window, Tauri is the better option at that point; for now, the browser opened by NiceGUI is sufficient.

### Why not native C++ / Qt?
FFmpeg and OpenCV are C/C++ under the hood — Python is only the orchestrator. The FFmpeg C API (libav*) is notoriously complex; most C++ video apps call the ffmpeg binary as a subprocess anyway. PySceneDetect has no C++ equivalent at the same quality. Python iteration speed is more valuable than marginal C++ performance gains at prototype stage. If profiling proves Python is the bottleneck (not the underlying C libraries), hot paths can be rewritten later.

### Why not a "full" video editor UX?
Existing tools (Premiere, DaVinci Resolve, even iMovie) present an open-ended creative canvas. aVs users are not editors — they want a good video, not a masterpiece. The closest analogy is Frame.io or a review-and-approval workflow tool: the computer assembles, the user reviews. This means no timeline scrubbing, no per-clip effects panel, no keyframing. Coarse controls only: accept/reject clips, swap music, toggle overlays, change color grade style.

### Why Python throughout?
Python is the native language of the video processing ecosystem (FFmpeg, OpenCV, PySceneDetect all have mature Python bindings). Cross-platform by design: `pathlib.Path`, `imageio-ffmpeg`, `watchdog`. Runs on Linux/Mac/Windows with minimal changes. If mobile standalone processing becomes a requirement, the pipeline would need rewriting (Python is not viable on iOS; painful on Android) — but that decision can be made when mobile is a real requirement, not now.

### Why Ollama for the LLM?
Open source, runs locally, trivial to install (one command + model pull). The `ollama` Python client connects to localhost:11434. The brief-to-edit-plan task is a structured extraction problem — a 3–4B parameter model (Phi-3.5 Mini, Llama 3.2 3B) handles it well with a constrained output schema. No API cost, no data sent externally, works offline. Required as a separate install; bundling the binary and model into the app is not feasible (2–4GB model weight).

### What about a future mobile app?
Two very different architectures depending on the meaning:
- **Tablet as thin client** (connects to desktop backend over local WiFi): the REST API we removed could be added back for this. Tablet shows the review UI; desktop does all processing. Zeroconf/mDNS for auto-discovery.
- **Standalone mobile** (full processing on device): Python is not viable on iOS (Apple sandbox). Android Python is painful. Flutter with `ffmpeg_kit_flutter` is the most practical path — single Dart codebase, runs on iOS/Android/desktop. This would be a rewrite of the UI and a port of the pipeline logic. The SQLite data model and processing pipeline concepts transfer; the code does not.

The current Python architecture does not preclude either future. It just doesn't try to solve them now.

---

## Architecture

### Shared engine layer

Both the CLI and the UI are thin consumers of the same `engine/` layer. The engine wraps
`processing/` algorithms and owns all orchestration (threading, cancel tokens, task state,
DB writes). Neither the CLI nor the UI calls `processing/` directly.

```
CLI ──┐
      ├── engine/ ── processing/   (algorithms unchanged)
UI  ──┘
```

### CLI

```
avs/
  cli.py          ← Typer commands — calls engine/, renders via rich
  engine/         ← shared orchestration (pipeline, sessions, marks, state, cancel)
  processing/     ← algorithms: analysis, peaks, assembly, export, ingest
  models/         ← SQLAlchemy + SQLite
  presets/        ← sport profiles, LUTs, music

User runs:
  avs ingest /media/SDCARD/DCIM --sport mtb
  avs analyze <session_id>
  avs review <session_id>       ← gates on status; directs to NiceGUI UI
  avs assemble <session_id>
  avs export <session_id>
  avs ui                        ← launches the NiceGUI desktop UI
```

### UI: NiceGUI (primary interface)

```
avs/
  ui/             ← NiceGUI screens and components — calls engine/, renders via NiceGUI
  llm/            ← Ollama client, prompt templates (future)
  main.py         ← packaged app entry point (migrations → init_db → UI)
  updater.py      ← background GitHub update check

User runs:
  avs ui               ← CLI → init_db → NiceGUI native window
  avs-ui               ← packaged entry point (same flow)
  dist/avs/avs      ← PyInstaller bundle (same flow)
```

NiceGUI handles the server and browser communication internally — no FastAPI, no React, no manual WebSocket code. The same processing modules are called directly from NiceGUI event handlers.

### Packaging

One PyInstaller spec (`avs.spec`) handles all three platforms via `sys.platform` conditionals — pywebview backend, icon format, UPX flag, and macOS `BUNDLE` step are all gated at build time.

```
avs.spec                  ← cross-platform PyInstaller spec
packaging/
  build_appimage.sh          ← Linux:   PyInstaller → AppImage
  build_windows.ps1          ← Windows: PyInstaller → Inno Setup .exe wizard
  build_macos.sh             ← macOS:   PyInstaller → create-dmg .dmg
  avs.iss                 ← Inno Setup installer definition (Windows)
  avs.desktop             ← Linux .desktop entry
.github/workflows/
  release.yml                ← three parallel jobs on tag push, each uploads to same GitHub Release
```

Per-OS artifact:

| OS | Artifact | Notes |
|---|---|---|
| Linux | `aVs-<ver>-x86_64.AppImage` | Needs `libgtk-3-0 libwebkit2gtk-4.0-37` on minimal installs |
| Windows | `aVs-<ver>-Setup.exe` | Fully self-contained; WebView2 ships with Win10/11 |
| macOS | `aVs-<ver>.dmg` | Drag-to-Applications; first launch needs right-click → Open (Gatekeeper) |

Startup sequence (packaged):
1. `main.py` runs Alembic `upgrade head` (idempotent, safe to run every launch)
2. `init_db()` sets up SQLAlchemy engine + session factory
3. `check_for_updates()` fires a background thread against GitHub API
4. `start()` launches NiceGUI native window
5. On home page load: shows update notification if a newer release was found

---

## Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Native ecosystem for FFmpeg/OpenCV/PySceneDetect |
| CLI | Typer | Type-annotated, auto-generates help text, built on Click |
| UI (Phase 2) | NiceGUI | Pure Python, browser-rendered, no JS, handles real-time updates |
| Video processing | ffmpeg-python + imageio-ffmpeg | Bundles FFmpeg binary cross-platform; no user install |
| Scene detection | PySceneDetect | Purpose-built, handles edge cases, clean API |
| Motion analysis | OpenCV (cv2) | Dense optical flow; C++ performance via Python bindings |
| Database | SQLite via SQLAlchemy | Local, serverless, ships with Python stdlib |
| DB migrations | Alembic | Schema versioning |
| LLM (Phase 2) | Ollama + `ollama` Python client | Local, free, offline, good 3–4B models for structured tasks |
| LLM model | Phi-3.5 Mini (3.8B) | ~2.2GB, fast on CPU, strong structured output |
| Filesystem watch | watchdog | Cross-platform SD card / folder detection |
| Packaging | PyInstaller + Inno Setup (Win) / create-dmg (Mac) / AppImage (Linux) | Standalone installers for all three platforms; no Python install for end users |

---

## Project Structure

```
avs/
├── CLAUDE.md
├── README.md
├── docs/
│   ├── requirements.md
│   ├── design.md
│   └── backlog.md
├── brainstorm/                  (read-only reference)
├── avs/
│   ├── __init__.py
│   ├── __main__.py              (python -m avs entry point)
│   ├── cli.py                   (Typer CLI commands — calls engine/)
│   ├── config.py                (paths, constants, settings)
│   ├── prefs.py                 (app_settings DB table wrapper)
│   ├── utils.py                 (fmt_duration, fmt_timestamp, is_valid_video)
│   ├── engine/                  (shared orchestration layer)
│   │   ├── cancel.py            (CancelToken: cancel(), is_cancelled(), register_cleanup())
│   │   ├── marks.py             (get_marks, count_actionable_marks, set_mark_statuses)
│   │   ├── pipeline.py          (run_proxy, run_scan, run_peaks, run_assemble, run_export)
│   │   ├── sessions.py          (list, get, delete, set_stage_time, list_exports)
│   │   └── state.py             (TaskState, StageState, task tracking)
│   ├── processing/              (algorithms — not called directly by UI or CLI)
│   │   ├── ingest.py            (scan folder, detect camera, group chapters)
│   │   ├── telemetry.py         (GPMF parser, SRT parser, normalization)
│   │   ├── analysis.py          (proxy gen, thumbnails, scene detect, optical flow)
│   │   ├── audio.py             (RMS energy, spike detection, VAD)
│   │   ├── peaks.py             (candidate mark generation, boring/dull region detection)
│   │   ├── assembly.py          (FFmpeg: concat, grade filters, audio mix, overlay)
│   │   └── export.py            (final encode per aspect ratio)
│   ├── models/
│   │   ├── db.py                (SQLAlchemy engine, session factory, inline migrations)
│   │   ├── schema.py            (ORM models)
│   │   └── migrations/          (Alembic)
│   ├── presets/
│   │   ├── sports.py            (sport profile dataclasses + DISPLAY_NAMES)
│   │   └── luts/                (reserved for LUT files)
│   ├── ui/                      (NiceGUI — primary interface)
│   │   ├── app.py               (NiceGUI app entry point, theme wiring)
│   │   ├── layout.py            (page_shell() context manager, sidebar())
│   │   ├── state.py             (re-export shim → engine/state)
│   │   ├── theme.py             (colour constants: ACCENT periwinkle, BG_PAGE, etc.)
│   │   ├── filepicker.py        (native file dialog via subprocess)
│   │   ├── screens/
│   │   │   ├── home.py          (session list table, New Edit Session)
│   │   │   ├── session.py       (full editing workflow: proxy→scan→pick→combine→export)
│   │   │   └── settings.py      (preferences + per-sport profile editor)
│   │   └── components/
│   │       ├── combine.py       (grade swatch strip, combine progress watcher)
│   │       ├── confirm_dialog.py (delete confirmation dialog)
│   │       ├── drop_zone.py     (new-session file picker + sport selector)
│   │       ├── mark_card.py     (review thumbnail cards HTML)
│   │       ├── progress.py      (bar_html, dot_html helpers)
│   │       ├── scan_progress.py (per-clip proxy/scan progress strips)
│   │       ├── session_card.py  (session table row renderer)
│   │       ├── stage_bar.py     (Next / Cancel action bar)
│   │       └── timeline.py      (mark timeline HTML, PICK_STYLE)
│   └── llm/                     (future — Ollama integration)
├── tests/
│   ├── fixtures/
│   │   └── source.mp4           (synthetic test video for pipeline tests)
│   ├── test_cli.py
│   ├── test_ingest.py
│   ├── test_telemetry.py
│   └── test_peaks.py
├── run.py                       (convenience: python run.py [command])
└── pyproject.toml
```

---

## Data Model

```sql
-- One import session (one SD card / folder)
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,          -- UUID
    created_at      DATETIME NOT NULL,
    source_path     TEXT NOT NULL,
    sport           TEXT,                      -- 'mtb', 'surf', 'ski', etc.
    camera          TEXT,                      -- 'gopro', 'dji', 'insta360', 'unknown'
    total_clips     INTEGER,
    total_duration_s REAL,
    status          TEXT NOT NULL,             -- 'importing' | 'ingested' | 'analyzing'
                                               -- | 'ready' | 'assembled' | 'exported'
    proxy_s         REAL,                      -- actual wall-clock time for proxy stage
    scan_s          REAL,                      -- actual wall-clock time for scan stage
    highlights_s    REAL,                      -- actual wall-clock time for peaks stage
    combine_s       REAL,                      -- actual wall-clock time for combine stage
    export_s        REAL                       -- actual wall-clock time for export stage
);

-- One row per logical video clip
CREATE TABLE clips (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    filename        TEXT NOT NULL,
    filepath        TEXT NOT NULL,
    proxy_path      TEXT,
    duration_s      REAL NOT NULL,
    width           INTEGER,
    height          INTEGER,
    fps             REAL,
    codec           TEXT,
    has_telemetry   BOOLEAN DEFAULT FALSE,
    peak_speed_kmh  REAL,
    peak_altitude_m REAL,
    peak_motion     REAL,
    scene_count     INTEGER,
    clip_order      INTEGER NOT NULL           -- chronological position in session
);

-- Telemetry time-series (one row per second per clip)
CREATE TABLE telemetry (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    clip_id                 TEXT NOT NULL REFERENCES clips(id),
    timestamp_s             REAL NOT NULL,
    speed_kmh               REAL,
    altitude_m              REAL,
    lat                     REAL,
    lon                     REAL,
    accel_magnitude         REAL,
    motion_intensity        REAL,              -- from OpenCV optical flow on proxy (dense)
    motion_intensity_quick  REAL               -- from JPEG frame extraction (sparse, faster)
);

-- Candidate and user-confirmed clip regions
CREATE TABLE marks (
    id              TEXT PRIMARY KEY,
    clip_id         TEXT NOT NULL REFERENCES clips(id),
    in_s            REAL NOT NULL,
    out_s           REAL NOT NULL,
    score           REAL,                      -- 0.0–1.0; null for user-added marks
    source          TEXT NOT NULL,             -- 'telemetry_peak' | 'motion_peak'
                                               -- | 'motion_peak_jpg' | 'audio_peak'
                                               -- | 'user' | 'llm'
    status          TEXT NOT NULL,             -- 'candidate' | 'accepted' | 'rejected'
    order_in_edit   INTEGER                    -- position in final edit; null until accepted
);

-- One row per sport (user's preferences, updated over time)
CREATE TABLE profiles (
    id                      TEXT PRIMARY KEY,
    sport                   TEXT NOT NULL UNIQUE,
    color_grade             TEXT NOT NULL,     -- 'punchy'|'cinematic'|'natural'|'warm'|'cool'
    music_energy            TEXT NOT NULL,     -- 'high'|'medium'|'chill'
    target_duration_youtube_s INTEGER,
    target_duration_short_s   INTEGER,
    min_clip_s              REAL,
    max_clip_s              REAL,
    overlay_speed           BOOLEAN DEFAULT TRUE,
    overlay_altitude        BOOLEAN DEFAULT TRUE,
    overlay_gps_map         BOOLEAN DEFAULT FALSE,
    speed_threshold_kmh     REAL,
    motion_threshold        REAL,
    scene_detector          TEXT DEFAULT 'content',  -- 'content'|'adaptive'|'threshold'
    scene_threshold         REAL,              -- detector-specific threshold value
    scene_min_scene_len     INTEGER,           -- minimum scene length in frames
    updated_at              DATETIME
);

-- Export history
CREATE TABLE exports (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    exported_at DATETIME NOT NULL,
    filepath    TEXT NOT NULL,
    aspect      TEXT NOT NULL,                 -- '16:9' | '9:16'
    duration_s  REAL
);

-- App-level UI preferences (default sport/grade/scan method, export defaults).
-- One row per key, JSON-encoded value. Stored in the DB (not a config file) so
-- all app state lives in one place. Accessed via avs/prefs.py.
CREATE TABLE app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

---

## CLI Interface

The CLI is a thin consumer of the engine layer — the same engine calls the NiceGUI UI makes.
Progress events from the engine are rendered via `rich`; the UI renders them in NiceGUI.

```
avs --help

Commands:
  ingest    Scan a folder or SD card and create a new session
  analyze   Run the full analysis pipeline (proxy → scan → peaks)
  review    Gate-check session status; direct to the NiceGUI UI for review
  assemble  Assemble accepted marks into a preview video
  refine    Re-assemble with adjustments (grade, removed clips, music swap)
  export    Export the preview to final output files
  sessions  List all sessions with status
  profile   Show or update a sport profile
  ui        Launch the NiceGUI desktop UI
```

### Command Details

```bash
# Import footage from SD card or folder
avs ingest /media/SDCARD/DCIM --sport mtb
avs ingest ~/footage/todays-ride --sport mtb
# → prints session ID, clip count, total duration, camera brand detected
# → Next step: avs analyze <session_id>

# Run analysis (proxy build → scene detect → peak detection)
avs analyze <session_id>             # full proxy-based motion analysis (default)
avs analyze <session_id> --jpg       # faster JPEG frame extraction for motion (~15× faster)
# → rich progress bar per clip per stage (proxy, scan, peaks)
# → Ctrl-C cancels cleanly via CancelToken
# → Next step: avs review <session_id>

# Review candidates
avs review <session_id>
# → gates on session status (must be ready/assembled/exported)
# → prints: run 'avs ui' and navigate to the session, or visit localhost:8080/session/<id>
# The actual review (timeline, thumbnail cards, accept/reject) is in the NiceGUI UI

# Launch the UI
avs ui [--port 8765]
# → starts NiceGUI on localhost; opens in the default browser

# Assemble preview
avs assemble <session_id>
avs assemble <session_id> --source jpg         # only motion_peak_jpg marks
avs assemble <session_id> --source proxy       # only motion_peak marks
avs assemble <session_id> --source telemetry   # only telemetry_peak marks
# → FFmpeg concat + grade filter + audio mix + overlays
# → Next step: avs export <session_id>

# Refine (re-assemble with changes)
avs refine <session_id> --remove <mark_id>
avs refine <session_id> --swap-music
avs refine <session_id> --grade cinematic
avs refine <session_id> --no-overlay
avs refine <session_id> --source jpg

# Export
avs export <session_id>                        # defaults: 16:9 only
avs export <session_id> --aspect 16:9 --aspect 9:16
# → outputs to ~/Videos/aVs/<date>_<sport>_<aspect>.mp4

# Session management
avs sessions               # list all (ID, date, sport, camera, clips, status)
avs sessions --status ready  # filter by status

# Sport profiles
avs profile mtb            # show active settings
avs profile mtb --grade cinematic --music-energy high
```

---

## Processing Pipeline

### Stage 1 — Ingest (`processing/ingest.py`)

```
scan directory for .MP4, .MOV files
  exclude: .LRV (GoPro proxy), .THM, files under 5 seconds

detect camera brand per file:
  filename: GH/GX/GOPR → gopro | DJI_ → dji | VID_ → insta360
  fallback: ffprobe container metadata (make/model tags)

group GoPro chapters:
  GH010001.MP4 + GH020001.MP4 → one logical clip
  match: same base prefix + sequential chapter number

for each logical clip:
  ffprobe → duration, resolution, fps, codec, has_audio
  check for .SRT sidecar (DJI telemetry)
  check for GPMF metadata track (GoPro telemetry)
  write to clips table

write session record → status = 'importing'
```

### Stage 2 — Analysis (`processing/analysis.py`)

Per clip, in order (resumable — skips already-completed steps based on DB state):

```
1. Proxy generation
   ffmpeg -i {source} -vf scale=854:480 -c:v libx264 -preset ultrafast
          -crf 28 -c:a aac -b:a 64k {cache/proxies/clip_id.mp4}

2. Thumbnail extraction
   ffmpeg -i {proxy} -vf fps=1/5 {cache/thumbs/clip_id/%04d.jpg}

3. Telemetry parsing (processing/telemetry.py)
   GoPro: extract GPMF binary track → TelemetryPoint[]
   DJI:   parse .SRT sidecar → TelemetryPoint[]
   Other: skip; motion_intensity only

4. Scene detection
   PySceneDetect on proxy — detector type and params from sport profile:
     content (default): ContentDetector(threshold, min_scene_len)
     adaptive:          AdaptiveDetector(adaptive_threshold, min_scene_len)
     threshold:         ThresholdDetector(threshold)
   Falls back to ContentDetector(threshold=27, min_scene_len=15) if no profile.
   → list of (start_s, end_s) scene tuples → stored in clips.scene_count

5. Motion intensity (OpenCV) — two methods, selectable via --proxy / --jpg:
   Proxy method (default): Farneback dense optical flow on proxy frames (sampled every 0.5s)
     → stored in telemetry.motion_intensity
   JPEG method (--jpg, ~15× faster): ffmpeg extracts one frame per 0.5s interval as JPEG,
     Farneback runs on consecutive JPEG pairs; temp frames deleted after
     → stored in telemetry.motion_intensity_quick
   Both methods can be run on the same session. Results are independent — review shows
   whichever source(s) have candidates; assembly --source selects which to use.

update clips record (peak_speed, peak_altitude, peak_motion, scene_count)
```

### Stage 3 — Peak Detection (`processing/peaks.py`)

```
for each clip:
  load telemetry rows (speed_kmh, accel_magnitude, motion_intensity)
  normalize each signal to [0, 1] range
  weighted sum → combined_score[] (weights from sport profile thresholds)
  find local maxima above threshold (scipy.signal.find_peaks or manual)

  for each peak:
    region = (peak_s - 2s pre-padding, peak_s + 5s post-padding)
    clip to clip boundaries
    score = max combined_score in region

  merge overlapping regions
  write to marks table (status='candidate', source='telemetry_peak'|'motion_peak')
```

Boring-region detection (`detect_boring_regions`, same module) runs right after,
over the same stored motion series — no extra video pass:

```
low_bar = sport motion_threshold × boring_threshold_pct (global setting)
smooth series (rolling mean, 3 samples)
runs = spans where smoothed motion < low_bar, bridging blips ≤ boring_gap_s
cut out any overlap with non-boring marks (found highlights always win)
keep runs ≥ boring_min_s → marks (status='boring', source='boring_motion')
```

Thresholds are global app settings (Settings → Boring-region detection), not code
constants; per-profile overrides only if usage shows sports need different
tolerances. In review, boring marks render amber/hatched with a `z` badge and
cycle skip↔include on click (never red). Combine assembles only accepted marks,
so skipped spans stay out unless rescued.

Dull-gap marking (`detect_dull_gaps`, same module) runs last: every span not
covered by any other mark becomes a Mark with status='dull' (source='dull_gap',
min length = `dull_min_s` setting). The timeline therefore has no anonymous
gaps — everything is highlight (green/red), boring (amber hatched), or dull
(solid orange, `–` badge). Dull cycles dull↔include on click, exactly like
boring's rescue.

### Stage 4 — Review (`ui/screens/session.py` — NiceGUI REVIEW mode)

The static-HTML review (`processing/review.py`) is deleted. Review is now in the NiceGUI
session page. The CLI `avs review` command gates on session status and prints the URL.

```
NiceGUI session page enters REVIEW mode when the user clicks "Review clips →":
  stage table compresses (est/act columns hidden, counts stay)
  review panel slides in below the player:
    timeline bar: one coloured rectangle per mark (green=in, red=out, amber=boring, orange=dull)
    thumbnail cards: one per mark, showing nearest proxy thumbnail
      each card: thumbnail image, clip name, in/out timestamps, score badge
      click: cycles in → out → in (boring: skip ↔ in; dull: dull ↔ in); seeks proxy player

user clicks "Save & combine clips →":
  engine.marks.set_mark_statuses() — writes decisions to marks table
  page transitions to Combine step; combine watcher starts
```

### Stage 5 — Assembly (`processing/assembly.py`)

```
collect accepted marks sorted by (clip.clip_order, mark.in_s)

cut segments (stream copy, fast):
  for each mark:
    ffmpeg -ss {in_s} -to {out_s} -i {source} -c copy {segments/mark_id.mp4}
  cached — skipped if segment file already exists

encode segments in parallel (4 workers):
  for each segment:
    ffmpeg -i {segment} -vf {grade_filter} -c:v libx264 -preset medium -crf 22
           {segments/encoded/{mark_id}_{grade}_{filterhash}.mp4}
  cached — keyed by mark + grade + a hash of the grade's filter string (the grade
  is baked into the encode, so grade changes or filter retunes re-encode instead
  of reusing stale files); validated with ffprobe before trusting; corrupt files
  deleted and re-encoded

concat encoded segments (lossless copy):
  ffmpeg -f concat -i {list} -c copy {cache/previews/{session_id}_preview.mp4}
```

### Stage 6 — Export (`processing/export.py`)

```
for each requested aspect ratio:
  '16:9': use preview as-is (source is 16:9)
  '9:16': ffmpeg crop (centre crop 9:16 from 16:9) → scale 1080x1920

encode per target:
  libx264 -crf 20 -preset slow -c:a aac -b:a 192k

output → ~/Videos/aVs/{YYYY-MM-DD}_{sport}_{aspect}.mp4
write exports record
update session status = 'exported'
```

---

## LLM Integration (Phase 2)

### How it fits in

Text brief from user → Ollama (local) → structured edit plan (JSON) → adjusts mark selections before assembly. If Ollama is not running, the pipeline falls back to automated candidate selection with no user brief.

### Prompt design

The LLM receives a system prompt defining its role and the output schema, plus a user message containing:
- The brief (plain English from the user)
- Structured session context: clip list with durations, telemetry summaries, candidate marks with scores

It does **not** receive video data — only text metadata. This keeps token count low and avoids sending footage anywhere.

Output is a JSON edit plan:
```json
{
  "rationale": "User highlighted third clip as best...",
  "accepted_marks": ["mark_id_3", "mark_id_7", "mark_id_12"],
  "rejected_marks": ["mark_id_1", "mark_id_5"],
  "target_duration_s": 480,
  "grade_override": null,
  "note": "Crash at end of clip 5 included as user mentioned it"
}
```

### Model choice

**Phi-3.5 Mini (3.8B)** — ~2.2GB download, runs on CPU at useful speed, strong at structured output with schema enforcement. Pull with `ollama pull phi3.5`.

Fallback: **Llama 3.2 3B** (~2GB) if Phi-3.5 unavailable.

---

## Sport Presets

Defined in `avs/presets/sports.py` as Python dataclasses.

| Sport | Grade | Music energy | Speed threshold | Motion threshold | YT duration |
|---|---|---|---|---|---|
| mtb | punchy | high | 25 km/h | 0.60 | 4 min |
| surf | warm | medium | 15 km/h | 0.50 | 3 min |
| ski | cool | high | 40 km/h | 0.65 | 4 min |
| skydive | vibrant | high | 100 km/h | 0.70 | 2.5 min |
| moto | cinematic | high | 60 km/h | 0.55 | 6 min |
| trail | natural | medium | 10 km/h | 0.40 | 3 min |
| cycling | natural | medium | 20 km/h | 0.45 | 5 min |

Grades are FFmpeg `eq`/`colorbalance` filter strings (`GRADE_FILTERS` in `processing/assembly.py`) — no LUT files are used at present; `presets/luts/` is reserved for a possible LUT upgrade (see Open Questions). The Combine stage shows a swatch per grade (the session still rendered through each filter, cached by filter-string hash) with a full-size preview in the player on selection. Music: user-provided via `--music /path/to/track.mp3`. No bundled tracks — see `/brainstorm/audio-music.md` for licensing rationale and future browser feature plan.

---

## Build Order

### Phase 1 — Pipeline

1. `pyproject.toml`, `config.py`, SQLAlchemy models + Alembic migration
2. `processing/ingest.py` — folder scan, camera detection, chapter grouping, ffprobe
3. `processing/telemetry.py` — GPMF parser (GoPro), SRT parser (DJI)
4. `processing/analysis.py` — proxy gen, thumbnails, PySceneDetect, OpenCV optical flow
5. `processing/peaks.py` — candidate mark generation
6. `cli.py` — `ingest` and `analyze` commands; test with real Insta360 footage
7. Review HTML generation — static page with thumbnails and checkboxes
8. `cli.py` — `review` command
9. `processing/assembly.py` — FFmpeg concat, LUT, audio mix
10. `cli.py` — `assemble` and `refine` commands
11. `processing/export.py` — multi-aspect encode
12. `cli.py` — `export` command
13. `presets/sports.py` — MTB preset complete (LUT + music)

### Phase 2 — UI + LLM

14. `llm/client.py` + `llm/prompts.py` + `llm/parser.py` — Ollama integration
15. `cli.py` — `brief` command (text input → LLM → adjust marks → assemble)
16. NiceGUI scaffold + Import screen
17. NiceGUI Footage Map screen
18. NiceGUI Clip Marks screen
19. NiceGUI Review Player screen
20. NiceGUI Export screen

---

## UI Design (NiceGUI)

The NiceGUI desktop UI is the primary interface. `avs ui` (or `python run.py ui`) launches it; it calls the same processing modules as the CLI — no separate backend, no duplication of pipeline logic. The CLI lags behind the UI and its refactor is parked (see `docs/backlog.md` → "CLI — power users").

Full layout rationale and behaviour detail: `docs/plan_ui_redesign_2.md` (the shipped v2 redesign).

### Navigation

Collapsible left sidebar. Items: Home, Current Edit, Settings (future). Uses `ui.left_drawer` with `breakpoint=0` so it never auto-hides. On the session page it starts collapsed; the collapse toggle sits at the top of the drawer itself — hamburger icon when collapsed, chevron (<) when expanded.

### Home / History screen (`/`)

Lists past sessions from the DB: sport badge, date, clip count, total duration, status badge, "Continue →" button, delete button. Delete removes all DB records and cached files (proxies, thumbnails, jpeg_frames, segments incl. encoded, preview, still, grade swatches). "Start editing →" navigates to `/session/new`.

### Session screen (`/session/{id}` and `/session/new`)

Single page containing the entire editing workflow:

```
┌─────────────────────────────────────────────────────────┐
│  header: sport · date · elapsed time · est   [delete]   │
├───────────────────┬─────────────────────────────────────┤
│                   │  step options       [Next action →]  │
│   Stage table     ├─────────────────────────────────────┤
│   (300px fixed)   │  (progress strip / grade swatches)  │
│                   ├─────────────────────────────────────┤
│   Stage Est Act N │  Video player in a labeled frame    │
│   ──────────────  │                                     │
│   Select video    │  EMPTY   → placeholder + browse     │
│   Trim video      │  PREVIEW → still, then proxy        │
│    …sub-rows…     │  REVIEW  → timeline + thumb cards   │
│   [Add text]      │           (below the player)        │
│   [Add music]     │  OUTPUT  → preview / exported file  │
│   Export          │                                     │
└───────────────────┴─────────────────────────────────────┘
```

- **Stage table:** Stage / Est / Act / N columns; estimates static, actuals and counts update live (task timestamps survive page reloads via shared task state; not app restarts). Compresses during clip review, keeping counts.
- **Options bar:** all per-step controls (scan method, combine grade, export aspects/folder) plus the next-action button at top right. No dialogs.
- **Player frame label** states what is on screen: "Static preview of original" → "Working copy" → "Selected clips, combined" → "Exported". After export the exported file itself is mounted (served via a per-file media route, so any output folder works).
- **Progress strips** (per-clip proxy/scan bars, combine "x of y segments", export %) sit above the player, never overlaying it. Combine/export watchers re-attach when the user navigates away and back mid-run.
- **Grade swatches** at the Combine stage: the session still rendered through each grade filter; clicking shows the frame full-size in the player (click again to return to the video).
- **Steps:** Select video · Trim video (working copy → scan → find clips → select clips → combine) · Add text (future) · Add music (future) · Export.
- Drag-and-drop is deliberately absent: pywebview's default drop navigates the app to fullscreen video playback; default drop is blocked window-wide.

Assembly falls back to CANDIDATE marks if no ACCEPTED marks exist (user skipped Save Picks).

### Share screen (future, Phase 3)

Platform tiles (YouTube, Instagram), per-platform metadata, auth flow. Not implemented.

### Settings screen (`/settings`)

Two cards:

- **Preferences** — default sport, default grade, default scan method, export
  aspects, output folder. Stored in the `app_settings` table via `avs/prefs.py`;
  consumed by the session page as pre-selected values.
- **Sport profiles** — per-sport editor over all `Profile` fields, split into
  "used by the pipeline" (grade, motion threshold, scene detection) and "stored but
  not used yet" (music energy, clip bounds, targets, overlays, speed threshold).
  Save upserts the sport's DB row; Reset deletes it so the built-in defaults in
  `presets/sports.py` apply again (row exists = customised, no row = defaults —
  the same fallback the pipeline uses). Adding custom sports is deferred
  (backlog → "Custom sports").

Still possible later: global cache dir, custom FFmpeg path.

---

## Open Questions

1. **Proxy storage strategy:** Generate proxies eagerly at ingest or lazily on first analysis run? Eager is better UX; lazy saves disk for abandoned sessions.
2. **GoPro chapter joining:** Virtual join (treat as one logical clip, stitch only at assembly) or physical join at ingest time (ffmpeg concat demuxer, takes time upfront)?
3. **Music licensing:** Confirm Free Music Archive and ccMixter have appropriate CC0 / CC-BY tracks for the sports needed.
4. **LUT sources:** Commission, adapt open-source packs, or generate via FFmpeg eq/curves parameters? Open-source LUT packs (e.g. from Lutify.me free tier) may be usable with attribution.
5. ~~**Scene detection threshold:** Default 27 is tuned for general content. Action footage with motion blur and fast panning may need a higher threshold.~~ Resolved: `scene_detector`, `scene_threshold`, and `scene_min_scene_len` are now per-sport profile fields, configurable per sport in `presets/sports.py`.
6. ~~**Review HTML polling:** Polling a temp file works but is crude.~~ Resolved for the UI: the NiceGUI session page does review natively. The temp-file approach survives only in the CLI path (`processing/review.py`) — tracked under `docs/backlog.md` → "CLI — power users".
