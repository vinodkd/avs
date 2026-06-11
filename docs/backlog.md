# AxEdUp — Backlog

Struck-through items are committed.

---

## Review / clip selection

- [ ] **Manual mark creation from dead zones** — gaps between system-detected marks in the timeline should be clickable and draggable to create a new mark. User should be able to include footage the system didn't flag. (Prerequisite for boring-region feature below.)
- [ ] **Boring-region detection and auto-rejection** — flag segments where all signals (motion, audio, telemetry) are below threshold as `MarkStatus.BORING`. These appear as a third bucket in the Select clips count ("9 in · 3 out · 4 skipped"). User can override any boring-flagged segment by clicking it in the timeline to include it. Boring regions are visually distinct (e.g. hatched or dimmed) but still interactive.

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
- [ ] Optical flow optimisation (`--jpg` / `--proxy` flag on `analyze`)
  - [ ] Extract sample frames as JPEGs via ffmpeg (`fps=2`) instead of decoding every frame
  - [ ] Run Farneback on JPEG pairs — ~15× faster for sparse sampling
  - [ ] Store results in `motion_intensity_quick` (separate from proxy `motion_intensity`)
  - [ ] Peak detection runs per-method, marks tagged `motion_peak_proxy` vs `motion_peak_jpg`
  - [ ] Review shows two sections when both sets of marks exist

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
  - [ ] Progress bar for segment encoding (N of M segments)
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

## Pending decisions

- [ ] GoPro chapter joining — virtual join at assembly vs physical join at ingest
- [ ] Music — `--music /path/to/track.mp3` flag on `assemble` for user-provided tracks
- [ ] Music browser (Phase 2 UI) — browse/search CC0 sources online, point to track URL
- [ ] LUT assets — commission, adapt open-source pack, or generate via ffmpeg eq/curves

---

## Phase 2 — NiceGUI UI

- [ ] Import screen (folder/SD picker, sport selector)
- [ ] Footage Map screen (thumbnail strip, telemetry graph, scene markers)
- [ ] Clip Marks screen (card-based accept/reject/trim)
- [ ] Review Player screen (inline video, coarse refinement controls)
- [ ] Export screen (aspect ratio selector, progress, output path)
- [ ] Replace review HTML temp-file polling with NiceGUI event handler

---

## Phase 2 — LLM integration

- [ ] `llm/client.py` — Ollama connection and health check
- [ ] `llm/prompts.py` — system prompt and output schema
- [ ] `llm/parser.py` — response → structured edit plan
- [ ] `brief` CLI command — text input → LLM → adjust marks → assemble
- [ ] Graceful fallback when Ollama is not running
