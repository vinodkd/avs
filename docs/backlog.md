# aVs — Backlog

Source of truth for priorities and pending work. Struck-through items are committed.

---

## Current priorities (in order)

1. **Session UI usability** — show source filename everywhere; step navigation
   from left nav (jump to completed steps without re-running).
   (→ Session UI)
2. **Analysis robustness** — persist `audio_boosted` flag on `Mark`; crash/restart
   safety for partial proxy and scan builds.
   (→ Analysis pipeline)
3. **Remaining audio scoring** — WebRTC VAD for speech detection + score boost.
   (→ Analysis pipeline → Audio scoring)

Done: v0.1.5 released 2026-06-14 — audio scoring (RMS + spike detection),
dull/boring-region detection, settings screen, grade swatches, sport profile
popover, superseded screens removed, GH Actions bumped to Node 24.
Demoted: CLI refactor — revisit if/when power users appear (→ CLI — power users).

---

## Session setup / quick-start

- [ ] **"Use defaults" quick-start mode** — checkbox (or button) at session start that
  skips all per-step choices and applies defaults for every decision: sport profile,
  grade, motion threshold, dull threshold, clip count, output aspect. The defaults come
  from the active sport profile and app settings (already stored in DB). Result: user
  points at a folder and gets a finished video with zero decisions.
  Differs from current flow only in that the UI advances automatically through each step
  without pausing for input. Low priority until core pipeline is stable. Noted 2026-06-20.

- [ ] **Target output duration** — user sets a desired total clip length (e.g. 3 min)
  and the app works backwards to hit it: adjusts the motion sensitivity threshold and
  dull-region aggressiveness until the selected clips sum to approximately that duration.
  This inverts the current model (fixed thresholds → variable output length) into
  (fixed output length → variable thresholds). Needs a binary search or gradient loop
  over threshold values, re-running peak detection each iteration on the cached motion
  data (cheap — no re-scan needed). Noted 2026-06-20.

---

## Review / clip selection

- [ ] **Manual mark creation / precision sub-selection** — ~~largely superseded by dull sections~~: every unclaimed gap ≥ `dull_min_s` is now a rescuable dull mark, covering the core "include footage the system didn't flag" use case. Remaining gap: gaps shorter than `dull_min_s` stay black and unclickable; rescuing a long dull section includes all of it rather than just the interesting moment. Demoted to low priority — revisit if users need precision trimming within dull sections.
- [x] ~~**Boring-region detection and auto-rejection** — flag low-motion segments as
  `MarkStatus.BORING`, third bucket in counts, user-overridable from the timeline.~~
  Shipped 2026-06-12: motion-based detection in `peaks.py` (smoothed motion below a
  % of the sport motion threshold, sustained, gap-tolerant; highlight windows are
  never flagged). Amber hatched bars / yellow cards with z badge; click cycles
  skip↔include (never red). Thresholds are global settings (Settings → Boring-region
  detection). Timeline dark gaps remain by design: footage that is neither highlight
  nor confidently boring — see manual mark creation above for making them actionable.
  Audio/telemetry signals will join the scoring later (Analysis pipeline → Audio scoring).

---

## Session UI

- [ ] **Show source filename everywhere** — the source video filename should be visible
  on the home page session list and in the session page header at all times. Currently
  neither surface shows it, making it ambiguous which file is being processed when
  multiple sessions exist. Noted 2026-06-14.

- [ ] **Step navigation from left nav** — clicking a completed step header in the left nav
  should jump to that step and allow proceeding forward from there. Currently the UI only
  advances linearly; a `ready` session should allow jumping back to Scan results or Pick
  without re-running anything. Noted 2026-06-14.

- [ ] **Option to hide dull cards in review** — dull sections render as cards like
  everything else; fine while sessions are short (the card area scrolls), but
  hours-long footage will produce hundreds of dull cards. Add a toggle (or show
  dull only in the timeline) when that day comes. Noted 2026-06-12.

- [x] ~~**Grade swatch strip** (decided 2026-06-11) — at the Combine stage, render one
  representative proxy frame through each grade's filter string and show a row of
  small swatches, one per grade, so the user compares side by side before choosing.~~
  Shipped, including click-for-full-size preview in the player. Grades were retuned
  for visual separation (midtone-based warm/cool); may need further tweaking after
  more real-footage use.
- [x] ~~**Sport profile info popover** (decided 2026-06-11) — popover next to the sport
  selector listing what the active profile actually sets.~~ Shipped: shows the three
  wired-in settings (grade, motion threshold, scene detection) with the inert fields
  called out; friendly sport display names added alongside (storage keys unchanged).
- [x] ~~**Settings screen** (decided 2026-06-11) — preferences + per-sport profile
  editor with reset.~~ Shipped: `/settings` page; preferences in the new
  `app_settings` DB table (consumed as session-page defaults), profile editor with
  save-as-DB-row / reset-deletes-row semantics.
- [ ] **Custom sports (full profile CRUD)** — add/rename/delete sports beyond the seven
  built-ins. Requires DB to become the authoritative sport list (not `DEFAULT_PROFILES`):
  seed all seven built-ins at `init_db()` time with `is_default=True, is_active=True`;
  add `display_name` column to `Profile` (replaces hardcoded `DISPLAY_NAMES` dict, needed
  for user-created sport names); soft-delete via `is_active=False` for built-ins that
  sessions reference; hard-delete for user-created sports with no session references.
  All sport list queries then read from DB. Deferred 2026-06-12 as not yet needed.

---

## Analysis pipeline

- [ ] Progress and visibility
  - [x] ~~Progress bar for proxy generation (ffmpeg pipe → `out_time_ms`)~~
  - [x] ~~Progress bar for motion intensity (OpenCV frame counter)~~
  - [ ] **Pause and cancel running pipeline stages** — long proxy builds and scans
    on large videos have no way to stop short of killing the app. Add a Cancel
    button per stage (sends SIGTERM to the ffmpeg/OpenCV subprocess and marks
    the stage as interrupted); pause is a stretch goal (harder with ffmpeg, more
    useful for the OpenCV motion scan). Noted 2026-06-20.
    Context: deleting a session mid-scan removes it from the DB and UI but the
    background thread keeps running (holding in-memory refs) until it finishes,
    then fails silently trying to write back to the deleted session. CPU burn
    continues until the scan completes; only way to stop it sooner is killing
    the whole app. A cancel button needs to actually terminate the subprocess,
    not just remove the DB row.
  - [ ] **UI instability during assembly — thread-unsafe progress updates** —
    with 4 parallel encoding workers all firing `on_progress` callbacks
    simultaneously, NiceGUI receives rapid-fire concurrent UI mutations from
    background threads, causing flashing, redraws, and unresponsiveness. Fix:
    (1) throttle updates — only push to UI every N segments, not every callback;
    (2) marshal UI mutations to the main thread via NiceGUI's async/event-loop
    patterns rather than touching UI elements directly from worker threads.
    Observed during a 101-segment combine. Noted 2026-06-20.
- [ ] Scene detection
  - [x] ~~Scene detector type + params per sport profile (`scene_detector`, `scene_threshold`, `scene_min_scene_len`)~~
- [ ] Audio scoring
  - [ ] Run WebRTC VAD on proxy audio to detect speech segments
  - [ ] Boost peak score for segments containing speech
  - [ ] Optional: `faster-whisper` transcription for keyword search
- [x] ~~Optical flow optimisation (`--jpg` / `--proxy` flag on `analyze`)~~ — shipped
  as the Quick (1fps) / Full scan method
  - [x] ~~Extract sample frames as JPEGs via ffmpeg (`fps=2`) instead of decoding every frame~~
  - [x] ~~Run Farneback on JPEG pairs — ~15× faster for sparse sampling~~
  - [x] ~~Store results in `motion_intensity_quick` (separate from proxy `motion_intensity`)~~
  - [x] ~~Peak detection runs per-method, marks tagged `motion_peak_proxy` vs `motion_peak_jpg`~~
  - [x] ~~Review shows two sections when both sets of marks exist~~ — superseded: one
    review set; Combine has a source filter (all / still-frame picks / motion picks)

- [ ] **Persist audio_boosted flag on Mark** — currently the mic icon on motion marks
  that contain an audio spike is computed at render time by re-querying spike timestamps
  on every page load. Make it durable: add `audio_boosted: bool` column to `marks` table
  (migration + schema change), set it in `_detect_clip_peaks()` when boost is applied.
  Card rendering then reads the flag directly instead of re-checking telemetry.
  Requires a rescan of existing sessions to populate the flag.

- [ ] Pipeline timing
  - [ ] Add `analyzed_at`, `assembled_at`, `exported_at` timestamps to `Session`
  - [ ] Add `analysis_duration_s`, `assembly_duration_s`, `export_duration_s` to `Session`
  - [ ] Show timings in `avs sessions` output
  - [ ] Stage-table "est→actual" times: actuals live in in-process task state, so
        they survive page reloads but are lost on app restart — persist via the
        duration columns above

- [ ] **Session status must be authoritative from DB** — on restart, if the DB says
    `assembled` or `ready`, the UI must show that state regardless of whether proxy/cache
    files are present. Missing files should surface as a warning ("session was at export
    but proxy files not found"), not silently revert the session to an earlier stage.
    Currently the UI re-derives state from file presence, which caused sessions to revert
    to "create working copy" after a cache directory move. Noted 2026-06-20.

- [ ] Crash/restart robustness (stage completion is inferred, not recorded)
  - [ ] Proxy: `all_proxies_done` is file-existence-based; an app kill mid-build
        leaves a half-written proxy file that reads as "done" on restart and
        plays corrupt. Write to a temp name and rename on completion, or record
        per-clip proxy completion in the DB
  - [ ] Scan: `has_motion_data` is true after the first telemetry rows, so a
        partially scanned session reads as scan-complete on restart. Record
        per-clip scan completion in the DB
  - (combine/export are already restart-safe: status stays READY/ASSEMBLED until
   the step finishes, so the UI correctly offers the step again)

---

## Assembly pipeline

- [ ] Reliability and performance
  - [x] ~~Parallel segment encoding (4 workers)~~
  - [x] ~~Validate encoded segment cache before use (ffprobe check, delete corrupt files)~~
  - [ ] **Clip boundary overlap causing glitch at cuts** — assembled output shows a
    brief repeated-action glitch at segment boundaries, suggesting the cut points have
    overlapping frames (start of next segment repeats the end of the previous one).
    Check that segment start/end times are exclusive and that the ffmpeg concat filter
    is not duplicating frames at boundaries. Noted 2026-06-20.
- [ ] Progress and estimates
  - [x] ~~Progress bar for segment encoding (N of M segments)~~ — combine bar in the UI
  - [ ] **Suppress terminal noise from combine stage; add on_event hook** —
    "cutting segment x/y" prints to terminal because `_logger` in `assembly.py`
    falls back to `print` when no console is passed (UI path). Fix: make the
    no-console case a no-op; add `on_event: Callable[[str], None] | None`
    parameter to `assemble_session` and route log messages through it so the
    CLI refactor can surface them without re-adding print statements.
    (→ CLI — power users)
  - [x] ~~Progress bar and time estimate for export encode (ffmpeg pipe → `out_time_ms`)~~
- [ ] Cleanup
  - [ ] Delete `segments/encoded/` after successful export (grade is baked in, stale on grade change)
  - [ ] `avs clean <session_id>` command for manual cache cleanup

---

## 360° video support

Design notes in `brainstorm/360-video-processing.md`.

- [ ] **Phase 1 — approximate stitch + gyro-driven effects**
  - [ ] Detect `.insv` at ingest; mark clip as `source_format=360`
  - [ ] Parse gyro telemetry track from `.insv` (or `.lrv` sidecar on models that write it there)
  - [ ] Approximate stitch: FFmpeg `v360=dfisheye:equirect` → equirectangular proxy (no calibration needed)
  - [ ] Gyro integration: angular velocity → orientation quaternions (`scipy.spatial.transform`)
  - [ ] Gyro magnitude as scoring signal in `peaks.py` alongside optical flow and audio
  - [ ] Gyro axis analysis per highlight clip → select effect type (high yaw→barrel roll, low→tiny planet, etc.)
  - [ ] Forward-lock framing via gyro orientation (keep virtual camera facing direction of travel)
  - [ ] Effect presets applied as FFmpeg `v360` filter expressions at Combine step
  - [ ] Settings: mount orientation offset (front/chest/top/side)
  - [ ] Verify with real `.insv` footage before committing — FFmpeg dfisheye stream layout may need adjustment
- [ ] **Phase 2 — accurate stitch via Gyroflow lens profiles**
  - [ ] Extract Gyroflow camera profiles (MIT JSON, ~200+ Insta360 models)
  - [ ] Load profile: intrinsic matrix (fx/fy/cx/cy) + distortion coefficients (k1-k4)
  - [ ] `cv2.fisheye.undistortImage()` per frame → accurate equirectangular (replaces dfisheye approximation)
  - [ ] Note: Gyroflow profiles are OpenCV distortion model — do NOT pass to FFmpeg v360 directly
- [ ] **Phase 2 — user POV control**
  - [ ] Yaw/pitch slider at review time to override auto-selected framing
  - [ ] Auto-reframe toward motion (optical flow on sphere regions)
  - [ ] Support `.gyro` sidecar files (some Insta360 models write telemetry separately)

---

## Sport profiles

- [ ] CLI access to scene detection params
  - [ ] Extend `profile` command to show/set `--scene-detector`, `--scene-threshold`, `--scene-min-scene-len`

---

## Vision / content search

- [ ] Semantic scene labelling (Phase 2)
  - [ ] Run LLaVA or Moondream (via Ollama) on first frame of each detected scene
  - [ ] Store label per scene (climbing, descent, crash, crowd, talking, static)
  - [ ] Show labels in review UI
- [ ] Content search
  - [ ] Query clips by scene label ("find the crash", "find talking segments")

---

## Tooling / CI

- [x] ~~**Bump GitHub Actions to Node 24-compatible versions**~~ — shipped 2026-06-14:
  checkout v6, setup-python v6, action-gh-release v3, configure-pages v6,
  upload-pages-artifact v5, deploy-pages v5. Node 20 removal 2026-09-16.

---

## Pending decisions

- [ ] GoPro chapter joining — virtual join at assembly vs physical join at ingest
- [ ] Music — `--music /path/to/track.mp3` flag on `assemble` for user-provided tracks
- [ ] Music browser (Phase 2 UI) — browse/search CC0 sources online, point to track URL
- [ ] LUT assets — commission, adapt open-source pack, or generate via ffmpeg eq/curves

---

## Phase 2 — NiceGUI UI

Superseded by UI redesign v2 (shipped in v0.1.4): the session page covers import
(EMPTY mode), review (REVIEW mode with timeline + cards), and export (options bar).
Kept struck-through for history; footage map remains the one open idea.

- [x] ~~Import screen (folder/SD picker, sport selector)~~
- [ ] Footage Map screen (thumbnail strip, telemetry graph, scene markers)
- [x] ~~Clip Marks screen (card-based accept/reject/trim)~~
- [x] ~~Review Player screen (inline video, coarse refinement controls)~~
- [x] ~~Export screen (aspect ratio selector, progress, output path)~~

---

## CLI — power users (low priority)

The NiceGUI app is the primary interface. Revisit this if/when power users appear.

- [ ] **Refactor `cli.py` to the event-based backend** — the pipeline now exposes
  `on_event`/`on_progress` callbacks, separate proxy/scan/peaks steps, shared task
  state, and session statuses driven by the UI; `cli.py` still calls the older
  combined entry points. Bring it in line: progress output from `on_event`,
  separate analyze steps, status-aware resume.
  - [ ] Replace review HTML temp-file polling (`processing/review.py`) with the
    NiceGUI review flow or an event-based equivalent

---

## Phase 2 — LLM integration

- [ ] `llm/client.py` — Ollama connection and health check
- [ ] `llm/prompts.py` — system prompt and output schema
- [ ] `llm/parser.py` — response → structured edit plan
- [ ] `brief` CLI command — text input → LLM → adjust marks → assemble
- [ ] Graceful fallback when Ollama is not running
