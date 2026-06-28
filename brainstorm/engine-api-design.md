# Engine API Design & Migration Plan

Discussed 2026-06-21.

## What the engine actually is

A layer that the CLI and UI are both thin consumers of. Not "move code out of session.py"
— both CLI and UI call identical engine methods and subscribe to identical event streams.
The engine is real when a CLI command and a UI button trigger the same code path and the
same progress events surface in both interfaces.

Current state: the pipeline logic lives in `processing/`, but the UI (`session.py`) calls
it directly, owns the progress state, manages threading, handles errors, and decides what
"done" means. The CLI calls different entry points. They share algorithms but not the
orchestration layer.

Target state:
```
CLI ──┐
      ├── engine/ ── processing/   (algorithms unchanged)
UI  ──┘
```

## Target structure

```
avs/
  engine/
    sessions.py    — list, get, delete (with cache wipe)
    marks.py       — get marks, set status
    pipeline.py    — run_ingest, run_scan, run_peaks, run_assemble, run_export
    state.py       — StageState, TaskState, subscribe/publish (moves from ui/state.py)
    cancel.py      — CancelToken: .cancel(), .is_cancelled()
  processing/      — unchanged: algorithms live here, engine calls them
  ui/
    screens/       — thin: call engine, subscribe to events, render
    components/    — extracted per slice alongside the engine slice
    theme.py       — color constants (for the reskin)
  utils.py         — fmt_duration(), fmt_timestamp(), is_valid_video() (deduplicated)
  cli/             — calls engine methods, subscribes to on_event/on_progress
  tests/
    fixtures/      — reproducible test sessions at each pipeline stage (see below)
```

## The event protocol

Every pipeline stage returns a `CancelToken` and fires three callbacks:

```python
def run_*(
    ...,
    on_progress: Callable[[StageState], None],  # fired per unit of work
    on_event:    Callable[[str], None],          # fired for ALL log messages (never suppressed)
    on_done:     Callable[[Result | None], None] # fired once on completion/error/cancel
) -> CancelToken
```

`on_event` is always shown — rendered differently per consumer:
- **UI**: status label or collapsible log area below the stage row
- **CLI**: `rich` print, or passed to a progress bar description

The `_logger(console | None)` pattern currently duplicated across `analysis.py`,
`assembly.py`, `ingest.py`, and `export.py` (four copies) is entirely replaced by
`on_event`. All four copies are deleted.

## Cancel: one action, not per-stage buttons

The engine tracks the active `CancelToken` per session internally:

```python
# avs/engine/pipeline.py
_active_tokens: dict[str, CancelToken] = {}

def cancel_current(session_id: str) -> None:
    if token := _active_tokens.get(session_id):
        token.cancel()
```

**UI**: one Cancel button, visible whenever a stage is running, wired to
`engine.cancel_current(session_id)`. Disappears when idle.

**CLI**: `signal.SIGINT` (Ctrl-C) handler calls `engine.cancel_current(session_id)`
then exits cleanly. No per-command cancel plumbing needed.

```python
# avs/engine/cancel.py
class CancelToken:
    def __init__(self): self._event = threading.Event()
    def cancel(self) -> None: self._event.set()
    def is_cancelled(self) -> bool: return self._event.is_set()

# Stages check between units of work and raise CancelledError to exit
```

---

## State of processing/ (pre-refactor assessment)

`processing/` contains sound algorithms but has its own structural problems:

| Issue | Where | Fix |
|---|---|---|
| `_logger(console\|None)` duplicated | analysis, assembly, ingest, export (4×) | Deleted; replaced by `on_event` |
| `_is_valid_video` duplicated | analysis.py:487, assembly.py:259 | Move to `avs/utils.py` |
| Multiple analysis entry points | `build_proxies`, `run_motion_scan`, `analyze_session` | Consolidated behind `run_scan()` |
| `review.py` — dead code | 337-line temp HTTP server for old CLI review | Deprecated; deleted after refactor |
| No cancel mechanism | analysis.py CV loop, assembly parallel workers | CancelToken checked between frames/clips |

The algorithms themselves don't change. The engine wraps `processing/`; it doesn't
rewrite it.

---

## Migration strategy: steel thread first, then fill by urgency

**Do not migrate from end-of-pipeline to start.** Stages aren't independently testable
in isolation — you can't verify an export slice without a session that completed the full
pipeline, which creates a hybrid old/new state that hides bugs.

Instead:

### Step 0 — Steel thread (all stages at once, shallow)

Define all engine API stubs. Wire the UI and CLI to call them. Stubs fall through to
existing `processing/` calls — nothing changes functionally. Proves the plumbing works
end-to-end before any real migration begins.

```python
# avs/engine/pipeline.py (stub)
def run_scan(session_id, method, on_progress, on_event, on_done) -> CancelToken:
    # falls through to existing processing.analysis.analyze_session()
    # on_event wired to replace _logger; on_progress wired to replace update_clip_stage
    token = CancelToken()
    threading.Thread(target=_run_scan_impl, args=(session_id, method, on_progress,
                                                   on_event, on_done, token)).start()
    _active_tokens[session_id] = token
    return token
```

After Step 0: UI and CLI use engine calls. Old `processing/` still does all the work.
Cancel button exists but does nothing yet (token is never checked). `on_event` is wired
but messages aren't surfaced in the UI yet.

### Step 1 — Scan (most urgent user pain)

**Customer outcome:** Cancel button works during the proxy build and motion scan.

The scan is the longest-running stage, the most requested cancellable operation, and the
hardest integration (cancel token must propagate into the OpenCV frame loop and the
PySceneDetect pass). Do it first to validate the cancel architecture on the hardest case.

CancelToken is checked:
- Between clips in the proxy build loop
- Between frames in `_compute_motion()` and `_compute_motion_jpeg()`
- Between clips in the scene detection pass

On cancel: stage is marked as interrupted. `on_done(None)` fires. UI shows "Scan
cancelled — partial results available" and offers Resume or Restart.

**UI component extracted:** Scan progress panel
(`avs/ui/components/scan_progress.py`) — the multi-bar proxy/scenes/motion/audio display.

**CLI gain:** `avs analyze <session>` now responds to Ctrl-C cleanly.

### Step 2 — Ingest

**Customer outcome:** Cancel during proxy generation on a large import.

Simpler than scan (no OpenCV). CancelToken checked between clips in the proxy build.
Also: `run_ingest()` is the clean entry point for new session creation — replaces the
current `session.py` inline threading setup.

**UI component extracted:** Drop zone + file picker (`avs/ui/components/drop_zone.py`).

### Step 3 — Peaks

**Customer outcome:** Cancel available (short stage, low value, but completes the cancel
coverage). More importantly: this is where the scene-aware clip model lands
(see `brainstorm/clip-selection-model.md`).

Short stage. Low integration risk. CancelToken checked between clips.

**UI component extracted:** Stage action bar (`avs/ui/components/stage_bar.py`) —
the Next/Cancel bar that appears at each stage.

### Step 4 — Assemble

**Customer outcome:**
- Terminal noise fixed ("cutting segment x/y" now surfaces in both UI and CLI)
- UI instability during long assembles fixed (parallel workers no longer write directly
  to NiceGUI elements from worker threads)

The parallel encoding workers write progress through `engine.state` (not directly to
NiceGUI). The UI subscribes to `on_progress` via `ui.run_coroutine()` — main thread
only. The `_logger` in `assembly.py` is replaced by `on_event` — messages appear in the
UI status area and the CLI terminal.

**UI component extracted:** Combine progress + grade swatch strip
(`avs/ui/components/combine.py`).

### Step 5 — Export

**Customer outcome:** Export progress visible in both UIs (the "cutting segment x/y"
style messages from ffmpeg now show in the UI as status text, not just in the terminal).
Timer stops when export completes (the backlog bug).

Note: export DOES have meaningful progress to report — the per-aspect encode percentage
and the final concat. `on_event` surfaces these in both UIs; neither suppresses them.

**UI component extracted:** Export progress bar (`avs/ui/components/progress.py`).

### Step 6 — Session management

**Customer outcome:** Source filename shown on home page and session header (fixes
backlog item — data was always in the DB, just never surfaced).

`SessionSummary.source_path` is already in the DB. The engine's `list_sessions()` exposes
it; the UI displays it. No pipeline work needed.

Also in this step: `delete_session()` consolidated from the two `_do_delete` copies in
`home.py` and `session.py` into one engine method.

**UI component extracted:** Session card (`avs/ui/components/session_card.py`),
confirm-delete dialog (`avs/ui/components/confirm_dialog.py`).

### Step 7 — Marks and review flow

**Customer outcome:** Review flow driven entirely through the engine. Mark writes go
through one path.

`avs/ui/state.py` is deleted in this step — all state is now owned by
`avs/engine/state.py`. The UI subscribes via `subscribe_progress`.

**UI component extracted:** Timeline bar (`avs/ui/components/timeline.py`),
mark cards (`avs/ui/components/mark_card.py`).

### Step 9 — Finish session.py: remaining inline DB queries and path checks

**Customer outcome:** `session.py` imports no ORM models and no config paths.
The five remaining violations identified post-Step-8:

1. **Inline DB load** (`Session`, `Clip`, `Profile`, `TelemetryPoint` queries at page load)
   → `engine.sessions.get_session()`, `get_session_clips()`, `list_sports()`, `has_motion_data()`
2. **`clip_audio_spikes()` called inline** in the load block
   → `engine.marks.get_audio_spikes(clip_ids)`
3. **`config.PROXY_DIR` path checks scattered** in `_stage_st()`, `_player_src()`, stage table
   → `engine.sessions.proxy_path()`, `count_proxies_done()`
4. **`config.PREVIEW_DIR` / `config.STILL_DIR` path assignments**
   → `engine.sessions.preview_path()`, `still_path()`
5. **`_profile_info_html()` making a direct DB query**
   → `engine.sessions.get_profile_info(sport)`

After this step: `session.py` imports only `MarkStatus`, `SessionStatus` from schema
(enum constants needed for comparisons, not queries). No `db_session`, no `config`,
no `processing/` modules.

### Step 8 — Cleanup and reskin

**Customer outcome:** Periwinkle blue reskin + logo.

```python
# avs/ui/theme.py
BG_PAGE    = '#111'
BG_CARD    = '#1e1e1e'
ACCENT     = '#6a7fc8'   # periwinkle (was #5a9a5a green)
TEXT_DIM   = '#aaa'
TEXT_MUTED = '#666'
```

Also: `fmt_duration()` / `fmt_timestamp()` to `avs/utils.py`, `_GRADES` import
deduplicated, `page_shell()` helper for the repeated dark-mode+drawer+sidebar boilerplate,
`review.py` deleted.

---

## Engine API surface (full)

```python
# avs/engine/sessions.py
def list_sessions() -> list[SessionSummary]: ...
def get_session(session_id: str) -> SessionDetail | None: ...
def delete_session(session_id: str) -> None: ...

# avs/engine/marks.py
def get_marks(session_id: str) -> list[MarkSummary]: ...
def set_mark_status(mark_id: str, status: str) -> None: ...
def set_all_mark_statuses(session_id: str, statuses: dict[str, str]) -> None: ...

# avs/engine/pipeline.py
def run_ingest(source_path, sport, on_progress, on_event, on_done) -> CancelToken: ...
def run_scan(session_id, method, on_progress, on_event, on_done) -> CancelToken: ...
def run_peaks(session_id, on_progress, on_event, on_done) -> CancelToken: ...
def run_assemble(session_id, grade, music_path, on_progress, on_event, on_done) -> CancelToken: ...
def run_export(session_id, aspects, output_dir, on_progress, on_event, on_done) -> CancelToken: ...
def cancel_current(session_id: str) -> None: ...
```

---

## What session.py looks like after all steps

~150 lines. Pure rendering. No DB imports. No threading. No `config` path manipulation.
No business logic. Each stage section is one engine call + one component render.

## What the CLI gets

After Step 0, the CLI calls engine methods and is never behind the UI. The CLI's
`on_event` prints to the terminal; the UI's `on_event` updates a status area.
Same engine, different rendering.

## 360° support on this foundation

`run_ingest()` detects `.insv` and routes to an `ingest_360` adapter that stitches the
proxy. The UI and CLI never know the difference. New format support = new ingest adapter.

---

## Test fixtures

A set of reproducible sessions at each pipeline stage, available to any developer.
The engine doesn't know about them — they're test infrastructure only.

```
tests/fixtures/
  source.mp4               — short source video (~60s, genuine motion variety)
  README.md                — what the video contains, expected output (peak count, timestamps)
  setup.py                 — script: ingests source.mp4 fresh, produces DB sessions at each stage
```

`setup.py` rather than SQL dumps — absolute paths in the DB make SQL snapshots
non-portable. The script runs the engine against `source.mp4` and checkpoints the DB
after each stage, giving a reproducible session at ingested / analyzed / ready /
assembled that any developer can use to test a specific stage without running the full
pipeline.

Usage:
```bash
python tests/fixtures/setup.py          # builds all stages
python tests/fixtures/setup.py --stage scan  # builds up to scan only
avs ui                                  # fixture sessions appear in the home screen
```
