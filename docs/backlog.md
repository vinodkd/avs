# AxEdUp — Backlog

Source of truth for priorities and pending work. Struck-through items are committed.

---

## Current priorities (in order)

1. **Signal enrichment** — audio spike detection, combined scoring (motion +
   telemetry + audio), boring-region flagging, manual mark creation
   (→ Review / clip selection, Analysis pipeline → Audio scoring)
2. **Redesign leftovers** — home page style pass; delete superseded screens
   (`load.py`, `scan.py`, `pick.py`, `cut.py`, `save.py`)

Done: installable app — v0.1.4 released with AppImage / Setup.exe / dmg via
GitHub Releases; UI redesign v2 in the same release; Session UI follow-ups
(grade swatches, profile popover, settings screen) shipped 2026-06-12.
Demoted: CLI refactor to the event-based backend — revisit if/when power users
appear (→ CLI — power users).

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
  - [ ] Show timings in `axedup sessions` output
  - [ ] Stage-table "est→actual" times: actuals live in in-process task state, so
        they survive page reloads but are lost on app restart — persist via the
        duration columns above

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
- [ ] Progress and estimates
  - [x] ~~Progress bar for segment encoding (N of M segments)~~ — combine bar in the UI
  - [x] ~~Progress bar and time estimate for export encode (ffmpeg pipe → `out_time_ms`)~~
- [ ] Cleanup
  - [ ] Delete `segments/encoded/` after successful export (grade is baked in, stale on grade change)
  - [ ] `axedup clean <session_id>` command for manual cache cleanup

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

- [ ] **Bump GitHub Actions to Node 24-compatible versions** — v0.1.4 release run
  warned that `actions/checkout@v4`, `actions/setup-python@v5`, and
  `softprops/action-gh-release@v2` run on deprecated Node 20; GitHub forces Node 24
  from 2026-06-16 (removal 2026-09-16). Update pins in `release.yml` (and check
  `pages.yml`) before the next release.

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
