# UI Redesign Plan — v2

## Status: Planned, not yet implemented (branch: ui-redesign-2)

---

## Motivation

The current session page (`session.py`) has a fixed 3-pane layout:
- Top-left 60%: video player (black rectangle for 5 of 8 steps)
- Top-right 40%: step list (cramped, subtitles truncated)
- Bottom 40%: detail pane (scrolls badly for Pick step)

Problems:
- Video player wastes space during all processing steps
- Step list runs out of room (8 steps now, more coming)
- Method / Scan / Highlights are 3 separate steps for one background operation
- Detail pane is too compressed for the Pick step
- Timeline strip is duct-taped to the video column, invisible 7/8 steps
- No clear place for upcoming steps (Add text, Add music, Upload)

---

## Home Page

Stays as a **separate full-page screen**. The whole main area is a sessions table — date, sport, clip count, duration, status, Continue button. No persistent session list sidebar cluttering the editing view.

The home page already works reasonably well. Minimal changes needed (style update only, no structural change in this redesign).

---

## Session Page — New Layout

```
┌─────────────────────────────────────────────────────────┐
│  header: sport · date · elapsed · est total             │
├───────────────────┬─────────────────────────────────────┤
│                   │  step options       [Next action →] │
│   Stage table     ├─────────────────────────────────────┤
│   (~300px fixed)  │   Video player area                 │
│                   │   (mode-switches per step)          │
│   Stage  T  N     │                                     │
│   ──────────────  │   EMPTY   → drop zone               │
│   …rows…          │   PREVIEW → passive viewer          │
│                   │   REVIEW  → expanded + timeline     │
│                   │   OUTPUT  → preview/final           │
└───────────────────┴─────────────────────────────────────┘
```

- **Stage table**: fixed ~300px left column. Rows are compact (no subtitles). Time and count columns stay live.
- **Options bar**: top of the player column. Holds the per-step controls (scan method, combine grade, export aspects/folder) and the next-action button at top right — choices are made up top, the video below reacts.
- **Video player area**: fills remaining width below the options bar. Switches mode based on active stage.
- **Left nav drawer**: collapse toggle lives at the top of the drawer itself — hamburger when collapsed, chevron (<) when expanded.

---

## Top-Level Steps

The pipeline is restructured from 8 granular steps to 5 user-intent steps:

| Step | Label | Notes |
|---|---|---|
| 1 | Select video | Replaces the `/session/new` form |
| 2 | Trim video | Contains sub-stages (see table below) |
| 3 | Add text | Title cards — optional, not yet built |
| 4 | Add music | User track selection — not yet built |
| 5 | Export | Aspect ratios, output folder, upload (future) |

"Trim video" is the correct label. Action camera footage is shot continuously — not all of it is interesting. This step trims it down to the highlights.

Optional steps (Add text, Add music) are shown as greyed/togglable rows, not hidden. The user sees the full pipeline and can enable them.

---

## Trim Video — Stage Table

The old Method / Scan / Highlights / Pick / Combine steps become rows in a single table inside the "Trim video" step:

| Stage | Time (est→actual) | Progress | Count | Action |
|---|---|---|---|---|
| Working copy | est ~2m → 1m34s | ████████ 100% | — | — |
| Analyze footage | est ~1m → — | ░░░░░░░░ | — | Method: Quick ▼ |
| Find clips | auto → — | ░░░░░░░░ | 14 found | — |
| Select clips | — | — | 9 in · 3 out | Review → |
| Combine | est ~1m → — | ░░░░░░░░ | — | Grade: Natural ▼ · Combine → |

**Column behaviour:**
- **Est / Act**: separate columns. Est is static per stage; Act fills in live while running and freezes when done (actuals survive page reloads via task state; lost on app restart — DB persistence is a possible later step)
- **Progress**: bar while running, ✓ when done, — when pending
- **Count**: populated by the system (clips found, marks detected) OR by the user (clips accepted/rejected); count column for Select clips updates live as the user reviews
- **Action**: inline compact dropdown or button; disappears or greys out once stage completes

**Future rows** (when boring-region detection is added):
- Select clips count becomes: `9 in · 3 out · 4 skipped`
- "Skipped" = system-flagged boring, still user-overridable from timeline

---

## Video Player Modes

The player area is a state machine. Mode is set by the active stage:

### EMPTY mode (before footage is loaded)
- Centred placeholder in the player area ("No footage loaded yet")
- Path field, Browse button, and sport selector live in the options bar above
- **No drag-and-drop** — removed: pywebview's default drop behavior navigates the
  app away to fullscreen video playback with no way back; default drop is
  blocked window-wide instead
- Import → creates session → kicks off Working copy immediately → mode switches to PREVIEW

### PREVIEW mode (Working copy / Analyze / Find clips)
- Shows a still from the first clip as soon as files are loaded (extracted at ingest)
- Once first proxy is ready: player switches to the live proxy video
- User can scrub/watch their footage while background work runs
- No special overlays — player is passive
- All activity is reported in the stage table rows

### REVIEW mode (Select clips — triggered by Review →)
- Activated when user clicks **Review →** in the stage table
- Stage table compresses to a slim status strip at the top of the table column (one line per completed stage, collapsed)
- Player expands vertically to fill the freed space
- Timeline strip appears immediately below the player (full width of player column)
- Thumbnail cards appear below the timeline in a scrollable area
- A **← Back to summary** breadcrumb returns to full table view
- Stage table count column (`9 in · 3 out`) updates live as the user picks/rejects
- Timeline behaviour:
  - Green bars = included marks
  - Red/striped bars = rejected marks
  - Dark gaps = unselected footage (future: clickable to create a new mark)
  - Future: hatched bars = system-flagged boring (auto-rejected, user-overridable)

### OUTPUT mode (Combine / Export)
- Triggered automatically when Combine finishes: player loads the preview without user action
- This is the payoff moment — preview just appears
- Player shows preview for Combine review and Export confirmation
- When Export finishes, the exported file itself loads in the player (served via a
  per-file media route, so any output folder works)
- Export settings (aspect ratios, output folder) live inline in the options bar above the player — no dialog
- Combine shows a progress bar ("x of y segments") in the strip above the player

### Player frame label
The player sits in a thin frame with a label strip stating what is on screen:
"Static preview of original" → "Working copy" → "Selected clips, combined" → "Exported".

---

## New Session Flow (replaces /session/new form)

Current flow: Home → "Start editing →" → form page → Import → navigate to session

New flow: Home → "Start editing →" → session page in EMPTY mode → pick path / Browse → Import → session created → PREVIEW mode

The options bar above the player IS the import UI (path field, Browse, sport selector, Import button). No separate form page needed.

---

## Future Steps (not built yet)

### Add text
- Player mode: Annotate
- Player shows preview with text overlaid live as user types
- Controls: title text, font size, position (top/centre/bottom), start time, duration
- Implementation: FFmpeg `drawtext` filter

### Add music
- Player mode: Audio preview
- Player plays preview with selected track
- Controls: file picker for track, volume, trim/offset
- Implementation: FFmpeg `amix`

### Upload
- Added as a sub-row in Export, or a 6th top-level step
- Platform buttons (YouTube, Instagram, Strava)
- OAuth flow opens browser on first use

---

## Backlog Items Captured During This Discussion

See `docs/backlog.md` → "Review / clip selection" section:

1. **Manual mark creation from dead zones** — gaps between marks in the timeline should be clickable to create a new mark. User should be able to include footage the system didn't flag.

2. **Boring-region detection and auto-rejection** — flag low-activity segments as `MarkStatus.BORING`. Third bucket in Select clips count. User can override from timeline.

---

## Implementation Order

1. New `session.py` layout shell (table + player area, no logic yet)
2. EMPTY mode drop zone (replaces `/session/new`)
3. PREVIEW mode (proxy/still loading, existing logic ported)
4. Stage table rows with progress bars and live count
5. REVIEW mode (expand/compress, timeline, cards)
6. OUTPUT mode (preview autoload on combine complete)
7. Home page style update (minimal, structural change not needed)
8. Delete old screens: `load.py`, `scan.py`, `pick.py`, `cut.py`, `save.py` (replaced by session.py)
