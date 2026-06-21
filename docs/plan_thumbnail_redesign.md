# Thumbnail Redesign + Method Label Clarity

## Status (2026-06-08)

All 5 files changed and compiling. **Not yet tested on real footage.** Pending items before commit:
- Pre-proxy still shown in player, swapped to video when proxy done
- Quick scan shows "Extracting N/T" → "Comparing N/T" in bar
- Mark thumbnails in Pick clips card grid
- Combine/export progress in UI bar (not terminal)
- Header total estimate + live elapsed counter
- Step names: "Create working copy", "Choose sampling method", "Find scenes", "Select scenes"
- Scan start bug fixed: poll timer always created, activated when scan starts from method step

Additionally fixed in 2026-06-08 session (not in original plan):
- Scan button stays clickable after scan started (`_scan_started` ref + timer activation fix)
- Header always shows total estimate (~Xm) and live elapsed time from session creation

---

## Decisions made (do not re-derive)

- **Thumbnails step removed** — 8 steps: Input → Create working copy → Choose sampling method → Find scenes → Select scenes → Pick clips → Combine → Export
- **Pick clips UI**: keep timeline bar strip (widen `min-width` of span blocks from 14px to 40px), add thumbnail card grid below. No visual card↔bar linking for now.
- **Both scan methods use optical flow** — difference is frame sampling only:
  - Quick (`jpg`): ffmpeg extracts 1 JPEG/s from proxy, optical flow on those ~N frames
  - Full (`proxy`): OpenCV decodes every frame sequentially, samples every 0.5s
- **3 thumbnail cases** (replaces blanket 1-per-5s `build_thumbnails` step):
  1. **Pre-proxy still**: one frame from original source file, extracted on import, shown as `<img>` placeholder in player area; swap to `<video>` when first clip proxy is ready
  2. **Mark thumbnails**: after peak detection, one JPEG at each mark's `in_s` from proxy
  3. **Last frame**: last frame of each clip from proxy (extracted in the same pass as mark thumbnails)
- **Quick method progress**: show "Extracting N/T frames" during ffmpeg phase, then "Comparing N/T frames" during optical flow phase — requires `message` field in `StageState`

---

## File changes

### 1. `avs/config.py`

- Add `STILL_DIR = CACHE_DIR / "stills"` after `JPEG_FRAMES_DIR` line
- Add `STILL_DIR` to `ensure_dirs()` list
- Remove `THUMB_INTERVAL = 5` line (no longer used)

### 2. `avs/ui/app.py`

Add after existing `/thumbs` line:
```python
app.add_static_files('/stills', str(config.STILL_DIR))
```

### 3. `avs/ui/state.py`

Add `message: str | None = None` to `StageState` dataclass (after `total`).

In `update_clip_stage`, add `message: str | None = None` kwarg, pass it to `StageState(...)`.

In `get_clip_progress`, add `message=s.message` to the `StageState(...)` copy constructor.

### 4. `avs/processing/analysis.py`

**A. Add `extract_source_still(filepath: Path, dest: Path) -> None`** (new public function):
```python
def extract_source_still(filepath: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [config.FFMPEG_BIN, "-y", "-ss", "1", "-i", str(filepath),
           "-frames:v", "1", "-q:v", "4", str(dest)]
    subprocess.run(cmd, capture_output=True, timeout=30)
    # Silent on failure — placeholder is optional
```

**B. Add private `_extract_frame_at(proxy: Path, t: float, dest: Path) -> None`**:
```python
def _extract_frame_at(proxy: Path, t: float, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [config.FFMPEG_BIN, "-y", "-ss", str(t), "-i", str(proxy),
           "-frames:v", "1", "-q:v", "4", str(dest)]
    subprocess.run(cmd, capture_output=True, timeout=30)
```

**C. Add `extract_mark_thumbnails(session_id: str, on_event: OnEvent | None = None) -> int`** (new public function):
```python
def extract_mark_thumbnails(session_id: str, on_event: OnEvent | None = None) -> int:
    _notify = on_event or _NOOP
    from avs.models.schema import Mark, MarkStatus
    with get_session() as db:
        clips = db.query(Clip).filter(Clip.session_id == session_id).order_by(Clip.clip_order).all()
    total = 0
    for clip in clips:
        proxy_path = config.PROXY_DIR / f"{clip.id}.mp4"
        if not proxy_path.exists():
            continue
        thumb_dir = config.THUMB_DIR / clip.id
        thumb_dir.mkdir(parents=True, exist_ok=True)
        with get_session() as db:
            marks = (db.query(Mark)
                     .filter(Mark.clip_id == clip.id)
                     .filter(Mark.status.in_([MarkStatus.CANDIDATE, MarkStatus.ACCEPTED]))
                     .order_by(Mark.in_s).all())
        for mark in marks:
            dest = thumb_dir / f"mark_{mark.id}.jpg"
            if not dest.exists():
                _extract_frame_at(proxy_path, max(0.0, mark.in_s), dest)
                total += 1
        last_dest = thumb_dir / "last.jpg"
        if not last_dest.exists() and clip.duration_s:
            _extract_frame_at(proxy_path, max(0.0, clip.duration_s - 2), last_dest)
            total += 1
        _notify(clip.id, 'thumbnails', 'done',
                f"{clip.filename}: {len(marks) + 1} thumbnails", None, None)
    return total
```

**D. Modify `_compute_motion_jpeg`**: add `on_extract_progress: Callable[[int,int],None] | None = None` parameter. Change ffmpeg extraction from `subprocess.run` to Popen with `-progress pipe:1 -nostats`, parse `out_time_ms=` to estimate frames extracted, call `on_extract_progress(done_est, total_est)` as it streams. Then optical flow loop calls `on_progress` as before.

```python
# In the extraction block, REPLACE subprocess.run(cmd, ...) with:
est_total = max(1, int((duration_s or 0) / config.OPTICAL_FLOW_SAMPLE_INTERVAL))
popen_cmd = [config.FFMPEG_BIN, "-y", "-i", str(proxy_path),
             "-vf", f"fps={sample_fps}", "-q:v", "5",
             "-progress", "pipe:1", "-nostats",
             str(frame_dir / "%06d.jpg")]
process = subprocess.Popen(popen_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
deadline = time.time() + extraction_timeout
for line in process.stdout:
    if time.time() > deadline:
        process.kill(); break
    if on_extract_progress and line.startswith("out_time_ms=") and duration_s:
        try:
            out_ms = int(line.split("=",1)[1].strip())
            done_est = min(est_total, int(out_ms / 1e6 / config.OPTICAL_FLOW_SAMPLE_INTERVAL))
            on_extract_progress(done_est, est_total)
        except (ValueError, ZeroDivisionError):
            pass
process.wait()
if process.returncode != 0:
    raise RuntimeError("JPEG frame extraction failed")
```

**E. In `run_motion_scan`** — change quick-method callback section:

Replace the single `_mjpg` callback with two:
```python
def _mjpg_extract(done: int, total: int, _cid: str = clip.id) -> None:
    _notify(_cid, "motion", "progress", "Extracting", done, total)

def _mjpg_flow(done: int, total: int, _cid: str = clip.id) -> None:
    _notify(_cid, "motion", "progress", None, done, total)

motion_points = _compute_motion_jpeg(proxy_path,
    on_progress=_mjpg_flow,
    on_extract_progress=_mjpg_extract,
    duration_s=clip.duration_s)
```

Same change needed in `run_detection` and `_analyze_clip` (for backward compat CLI path).

### 5. `avs/ui/screens/session.py`

**A. `_STEPS`**: Remove the `thumbnails` tuple. Result:
```python
_STEPS = [
    ('input',      'Input',        'Select footage and sport'),
    ('proxy',      'Working copy', 'Transcode footage to 480p proxy'),
    ('method',     'Scan method',  'Choose motion detection speed'),
    ('scan',       'Motion scan',  'Detect scene cuts and score motion'),
    ('highlights', 'Highlights',   'Find candidate moments from motion scores'),
    ('pick',       'Pick clips',   'Review and accept candidate moments'),
    ('combine',    'Combine',      'Colour grade · assemble preview'),
    ('export',     'Export',       'Encode final file for sharing'),
]
```

**B. Remove `_THUMBNAIL_STAGES = ['thumbnails']`**

**C. Remove `thumbnails` entry from `_STAGE_LABEL` and `_STAGE_BYLINE`**

**D. Fix `_STAGE_BYLINE['motion']`**:
```python
'motion': 'Quick: ffmpeg extracts 1 frame/s, optical flow on those frames  ·  Full: OpenCV decodes every frame, sampled every 0.5s',
```

**E. Update `_on_event` in `session_page`** to pass `message` through:
```python
elif evt_status == 'progress' and completed is not None and total:
    pct = int(completed * 100 / total)
    state.update_clip_stage(session_id, clip_id, stage, 'running',
                            pct=pct, completed=completed, total=total,
                            message=message)   # ← add this
```

**F. Update `_bar_html` motion sub-line** to use `s.message`:
```python
if stage == 'motion' and s.completed and s.total:
    phase = s.message or 'Comparing'   # "Extracting" or "Comparing" from on_event
    mode  = '1fps sample' if method == 'jpg' else 'all frames'
    sub   = f'{phase} · {mode} · {s.completed:,}/{s.total:,} frames'
```

**G. Remove all thumbnail task/state variables** (`thumbnail_task`, `thumbnails_task`, `all_thumbnails_done`, `thumbnails_running`).

**H. Update `_step_st`**: remove `thumbnails` case. Update `method` case — it's now active after `all_proxies_done` (not `all_thumbnails_done`):
```python
if sid == 'method':
    return 'done' if (has_motion_data or scan_running or post_analysis) else (
           'active' if all_proxies_done else 'pending')
if sid == 'scan':
    ...active if all_proxies_done...
if sid == 'highlights':
    ...active if has_motion_data...
```

**I. Update `initial` step logic**: remove thumbnail checks. After proxy done → go to `method`.

**J. Update `_refresh_next_btn`**: remove thumbnail case. Proxy done → "Choose scan method →".

**K. Remove `_detail_thumbnails()` function entirely**.

**L. Update `_select_step`**: remove `elif step_id == 'thumbnails': _detail_thumbnails()` branch.

**M. Fix `_detail_method()` radio options**:
```python
options={
    'jpg':   'Quick — 1fps sample  (~15× faster, good for most footage)',
    'proxy': 'Full — all frames  (slower, more accurate for low-contrast clips)',
}
```
Update the description text below the radio to explain both use optical flow.

**N. Pre-proxy still — in `_new_session_ui` / `_do_start`**:

After `ingest_folder` succeeds and `sid` is known, extract the still **before** navigating:
```python
# Get first clip's source filepath from DB
with db_session() as db:
    first_clip = db.query(Clip).filter(Clip.session_id == sid).order_by(Clip.clip_order).first()
if first_clip:
    still_dest = config.STILL_DIR / f"{sid}_still.jpg"
    from avs.processing.analysis import extract_source_still
    await ng_run.io_bound(extract_source_still, Path(first_clip.filepath), still_dest)
```

In `session_page`, use the still if proxy not ready:
```python
still_path = config.STILL_DIR / f"{session_id}_still.jpg"
# In the player area, if not init_src but still_path.exists():
#   show <img src="/stills/{session_id}_still.jpg"> as placeholder
```

In `_poll` (the proxy poll timer), when proxy becomes ready, run JS to swap the img → video:
```javascript
var v = document.getElementById("main-player");
var ph = document.getElementById("player-ph");
var still = document.getElementById("player-still");
if(v){ v.src="/proxies/{clip_id}.mp4"; v.load(); v.style.display="block"; }
if(ph) ph.style.display="none";
if(still) still.style.display="none";
```

The player area HTML needs an `id="player-still"` on the `<img>` element.

**O. `_run_proxy_then_thumbnails` → rename to `_run_proxy`**:

Remove the thumbnail chain — just build proxy:
```python
def _run_proxy():
    try:
        from avs.processing.analysis import build_proxy_only
        build_proxy_only(sid, on_event=_on_event)
        state.finish_task(f'{sid}_proxy')
    except Exception as exc:
        state.finish_task(f'{sid}_proxy', error=str(exc))
threading.Thread(target=_run_proxy, daemon=True).start()
```

**P. After highlights complete, auto-run `extract_mark_thumbnails`**:

In `_run` inside `_start_scan`, after `state.finish_task(f'{session_id}_highlights')`:
```python
state.start_task(f'{session_id}_thumbnails')
from avs.processing.analysis import extract_mark_thumbnails
extract_mark_thumbnails(session_id, on_event=_on_event)
state.finish_task(f'{session_id}_thumbnails')
```

Note: reusing the key `{session_id}_thumbnails` here is fine since the old thumbnails task is removed.

**Q. `_detail_pick()` — add thumbnail card grid**:

Keep timeline bar strip HTML as-is but widen min-width from `14px` to `40px` in `_timeline_html`.

Below the instructions text, add a card grid:
```python
# After the instructions labels, before the JS block:
with db_session() as db2:
    mark_clips = {c.id: c for c in db2.query(Clip).filter(Clip.clip_id.in_([m[1] for m in mark_data])).all()}

with ui.element('div').style('display:flex;flex-wrap:wrap;gap:0.5rem;margin-top:0.5rem'):
    for mid, cid, in_s, out_s, score, source in mark_data:
        thumb = config.THUMB_DIR / cid / f"mark_{mid}.jpg"
        thumb_url = f'/thumbs/{cid}/mark_{mid}.jpg' if thumb.exists() else None
        ts = f'{_tsfmt(in_s)}–{_tsfmt(out_s)}'
        with ui.element('div').style(
            'width:140px;background:#1a1a1a;border-radius:4px;overflow:hidden;'
            'cursor:pointer;border:2px solid #2a2a2a'
        ).on('click', lambda m=mid, c=cid, i=in_s: _mark_card_click(m, c, i)):
            if thumb_url:
                ui.image(thumb_url).style('width:140px;height:79px;object-fit:cover;display:block')
            else:
                ui.element('div').style('width:140px;height:79px;background:#111;display:flex;align-items:center;justify-content:center') \
                    .add(ui.label('▷').style('color:#222;font-size:1.5rem'))
            with ui.element('div').style('padding:0.25rem 0.4rem'):
                ui.label(ts).style('color:#777;font-size:0.7rem')
                ui.label(f'{score:.2f}').style('color:#3a3a3a;font-size:0.65rem')
```

Card click handler `_mark_card_click(mid, cid, in_s)` seeks player to `in_s` (mirrors existing mark click JS).

---

## What does NOT change

- `peaks.py` — no changes
- `assembly.py`, `export.py` — no changes
- `docs/design.md` — update after all code changes confirmed working
- `docs/requirements.md` — update after confirmed

## Order to implement

1. `config.py` → 2. `app.py` → 3. `state.py` → 4. `analysis.py` (all 4 new/modified functions) → 5. `session.py` (tackle in lettered order A through Q)

Start session.py from the top and work down — it's the riskiest file.
