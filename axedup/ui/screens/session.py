"""
Single-page session view: the flat accordion step list that IS the editing UI.
Route: /session/{session_id}
"""
import json
import shutil
import threading
import time
from pathlib import Path

from nicegui import ui

from axedup import config
from axedup.models.db import get_session as db_session
from axedup.models.schema import (
    Clip, Export, Mark, MarkStatus, Profile, Session, SessionStatus,
)
from axedup.ui import state
from axedup.ui.state import StageState
from axedup.ui.layout import sidebar

# ── Constants ─────────────────────────────────────────────────────────────────

_ANALYSIS_STAGES = ['proxy', 'thumbnails', 'scenes', 'motion']
_STAGE_LABEL = {
    'proxy':      'Creating working copy',
    'thumbnails': 'Taking snapshots',
    'scenes':     'Finding scene cuts',
    'motion':     'Finding highlights',
}
_BADGE = (
    'font-size:0.72rem;background:#1e1e1e;'
    'padding:0.1rem 0.4rem;border-radius:3px;display:inline-block;white-space:nowrap'
)
_GRADES = ['punchy', 'cinematic', 'natural', 'warm', 'cool', 'vibrant']
_CARD_BASE = (
    'background:#1e1e1e;border-radius:6px;overflow:hidden;'
    'cursor:pointer;width:190px;flex-shrink:0'
)
_BORDER_ACCEPT = 'border:2px solid #2a7a2a'
_BORDER_REJECT = 'border:2px solid #5a2020'

# ── Badge helpers ─────────────────────────────────────────────────────────────

def _badge_html(s: StageState, label: str, stage: str) -> str:
    if s.status in ('done', 'skipped'):
        return f'<span style="color:#5a9a5a;{_BADGE}">✓ {label}</span>'
    if s.status == 'running':
        if stage == 'proxy' and s.pct is not None:
            detail = f'  {s.pct}%'
        elif stage == 'motion' and s.completed is not None and s.total:
            detail = f'  {s.completed:,}/{s.total:,}'
        elif s.pct is not None:
            detail = f'  {s.pct}%'
        else:
            detail = ''
        return f'<span style="color:#f0a040;{_BADGE}">▶ {label}{detail}</span>'
    return f'<span style="color:#444;{_BADGE}">· {label}</span>'


def _fmt(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f'{m}m {s:02d}s' if m else f'{s}s'


def _thumb_url(clip_id: str, ts: float) -> str:
    idx = max(1, round(ts / config.THUMB_INTERVAL))
    thumb_dir = config.THUMB_DIR / clip_id
    for off in range(6):
        for sign in ([0] if off == 0 else [1, -1]):
            p = thumb_dir / f'{idx + sign*off:04d}.jpg'
            if p.exists():
                return f'/thumbs/{clip_id}/{p.name}'
    return 'data:image/gif;base64,R0lGODlhAQABAIAAAMLCwgAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw=='


def _time_fmt(ts) -> str:
    m, s = divmod(int(ts), 60)
    return f'{m}:{s:02d}'

# ── Step expansion factory ────────────────────────────────────────────────────

def _step(title: str, subtitle: str, is_done: bool, is_active: bool, is_open: bool):
    """Return a styled ui.expansion for one step."""
    if is_done:
        icon, hcolor = 'check_circle', '#5a9a5a'
    elif is_active:
        icon, hcolor = 'radio_button_checked', '#f0a040'
    else:
        icon, hcolor = 'radio_button_unchecked', '#444'

    exp = ui.expansion(title, caption=subtitle, icon=icon, value=is_open)
    exp.style('width:100%; border-bottom:1px solid #1a1a1a')
    exp.props(
        f'header-style="color:{hcolor};background:#141414;padding:0.6rem 1rem" '
        f'expand-icon-color="{hcolor}" dense'
    )
    return exp

# ── Step 1 — Choose video (always collapsed, summary only) ────────────────────

def _render_step_choose(source_path: str, sport: str, clip_info: list, total_s: float) -> None:
    with _step('Choose video', 'Pick footage files and settings',
               is_done=True, is_active=False, is_open=False):
        with ui.column().style('padding:0.5rem 1rem 0.75rem; gap:0.4rem'):
            with ui.column().style('gap:0.15rem; color:#777; font-size:0.82rem'):
                ui.label(f'Source: {source_path}')
                m, s = divmod(int(total_s), 60)
                ui.label(f'{len(clip_info)} clips  ·  {m}m{s:02d}s  ·  sport: {sport}')

            # Thumbnail strip — visible when analysis has run
            thumbs = [(cid, fname, dur_s, _thumb_url(cid, (dur_s or 0) / 2))
                      for cid, fname, dur_s in clip_info]
            has_thumbs = any(not t.startswith('data:') for *_, t in thumbs)
            if has_thumbs:
                with ui.row().style('gap:0.5rem; flex-wrap:wrap; margin-top:0.1rem'):
                    for clip_id, fname, dur_s, thumb in thumbs:
                        with ui.column().style('gap:2px; align-items:flex-start'):
                            ui.html(
                                f'<img src="{thumb}" style="width:128px;height:72px;'
                                f'object-fit:cover;border-radius:3px;display:block;background:#1a1a1a">',
                                sanitize=False,
                            )
                            ui.label(fname).style(
                                'font-family:monospace;font-size:0.62rem;color:#666;'
                                'max-width:128px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'
                            )
                            ui.label(_fmt(int(dur_s or 0))).style('font-size:0.6rem;color:#444')
            else:
                with ui.column().style('gap:0.1rem; color:#555; font-size:0.75rem'):
                    for clip_id, fname, dur_s in clip_info:
                        ui.label(f'  {fname}  ({_fmt(int(dur_s or 0))})').style('font-family:monospace')

# ── Step 2 — Create working copy ──────────────────────────────────────────────

def _render_step_working_copy(
    session_id: str, clip_info: list,
    is_done: bool, is_active: bool, is_open: bool,
    progress: dict,
) -> dict:
    """Returns {clip_id: ui.html element} for proxy badges — polled by timer.
    When done, returns an empty dict (static ✓ badges, no polling needed)."""
    badge_els: dict[str, ui.html] = {}

    with _step('Create working copy',
               'Compresses footage to a smaller version we can process quickly',
               is_done=is_done, is_active=is_active, is_open=is_open):
        with ui.column().style('padding:0.5rem 1rem 0.75rem; gap:0.35rem; width:100%'):
            for clip_id, fname, _ in clip_info:
                with ui.row().style('align-items:center; gap:0.5rem; flex-wrap:nowrap'):
                    ui.label(fname).style(
                        'color:#888; font-size:0.78rem; font-family:monospace; '
                        'width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap'
                    )
                    if is_done:
                        # Static ✓ — no polling needed
                        ui.html(
                            _badge_html(StageState(status='done'), _STAGE_LABEL['proxy'], 'proxy'),
                            sanitize=False, tag='span',
                        )
                    else:
                        s = progress.get(clip_id, {}).get('proxy', StageState())
                        el = ui.html(
                            _badge_html(s, _STAGE_LABEL['proxy'], 'proxy'),
                            sanitize=False, tag='span',
                        )
                        badge_els[clip_id] = el

    return badge_els

# ── Step 3 — Split into clips ─────────────────────────────────────────────────

def _render_step_split(
    session_id: str, clip_info: list, step_label: str,
    is_done: bool, is_active: bool, is_open: bool,
    progress: dict, mark_count: int,
) -> dict:
    """Returns {clip_id: {stage: ui.html}} for non-proxy badges, or empty dict when done."""
    badge_els: dict[str, dict[str, ui.html]] = {}

    subtitle = 'Using still frame analysis to find scene boundaries and exciting moments'
    if 'motion' in step_label.lower():
        subtitle = 'Using motion analysis to find scene boundaries and exciting moments'

    with _step(step_label, subtitle,
               is_done=is_done, is_active=is_active, is_open=is_open):
        with ui.column().style('padding:0.5rem 1rem 0.75rem; gap:0.35rem; width:100%'):
            if is_done:
                ui.label(
                    f'✓ {mark_count} candidate clip{"s" if mark_count != 1 else ""} found'
                ).style('color:#5a9a5a; font-size:0.82rem; margin-bottom:0.2rem')
            for clip_id, fname, _ in clip_info:
                with ui.row().style('align-items:center; gap:0.4rem; flex-wrap:wrap'):
                    ui.label(fname).style(
                        'color:#888; font-size:0.78rem; font-family:monospace; '
                        'width:220px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap'
                    )
                    if is_done:
                        # Static ✓ badges — no polling needed
                        for stage in ['thumbnails', 'scenes', 'motion']:
                            ui.html(
                                _badge_html(StageState(status='done'), _STAGE_LABEL[stage], stage),
                                sanitize=False, tag='span',
                            )
                    else:
                        clip_badges: dict[str, ui.html] = {}
                        for stage in ['thumbnails', 'scenes', 'motion']:
                            s = progress.get(clip_id, {}).get(stage, StageState())
                            el = ui.html(
                                _badge_html(s, _STAGE_LABEL[stage], stage),
                                sanitize=False, tag='span',
                            )
                            clip_badges[stage] = el
                        badge_els[clip_id] = clip_badges

    return badge_els

# ── Step 4 — Pick clips ───────────────────────────────────────────────────────

def _timeline_html(mark_data: list, clip_info: list, total_s: float) -> str:
    """Proportional timeline — no thumbnails, pure bar layout.

    Layout (48px total height):
      top 14px  — clip label strip (filename, duration)
      middle 6px — thin clip separator line
      bottom 28px — mark bars, full height of segment area
    Each clip block flex-grows proportional to its duration.
    """
    marks_by_clip: dict[str, list] = {}
    for mid, cid, in_s, out_s, _score, _src in mark_data:
        marks_by_clip.setdefault(cid, []).append((mid, in_s, out_s))

    # Clip separator colors cycling through a subtle palette
    _CLIP_BG = ['#1a1a1a', '#171717', '#1c1c1c', '#181818']

    out = [
        '<div style="display:flex;width:100%;gap:2px;background:#0a0a0a;'
        'padding:6px 8px 8px;box-sizing:border-box;align-items:stretch">'
    ]

    for i, (clip_id, fname, dur_s) in enumerate(clip_info):
        if not dur_s:
            continue
        flex   = max(dur_s, 1.0)
        label  = (fname[:10] + '…') if len(fname) > 10 else fname
        bg     = _CLIP_BG[i % len(_CLIP_BG)]
        clip_marks = marks_by_clip.get(clip_id, [])

        out.append(
            f'<div style="flex:{flex:.1f};min-width:16px;position:relative;'
            f'border-radius:3px;overflow:hidden;background:{bg};height:48px">'
        )
        # Clip label (top strip)
        out.append(
            f'<div style="position:absolute;top:0;left:0;right:0;height:16px;'
            f'background:rgba(0,0,0,0.55);display:flex;align-items:center;'
            f'padding:0 4px;overflow:hidden;pointer-events:none">'
            f'<span style="font-size:0.5rem;color:#999;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis">'
            f'{label} · {_fmt(int(dur_s))}</span></div>'
        )
        # Mark bars (lower 28px)
        for mid, in_s, out_s in clip_marks:
            in_pct = in_s / dur_s * 100
            w_pct  = (out_s - in_s) / dur_s * 100
            tip    = f'{_time_fmt(in_s)}–{_time_fmt(out_s)}  ({out_s - in_s:.1f}s)'
            out.append(
                f'<div id="mark-{mid}" data-mid="{mid}" data-cid="{clip_id}" '
                f'data-ins="{in_s}" '
                f'style="position:absolute;top:18px;left:{in_pct:.2f}%;'
                f'width:max({w_pct:.2f}%,5px);bottom:2px;background:#2a7a2a;'
                f'border-radius:2px;cursor:pointer;transition:background 0.1s" '
                f'onclick="axedupMarkClick(this)" title="{tip}"></div>'
            )
        out.append('</div>')  # clip block

    out.append('</div>')
    return ''.join(out)


def _render_step_pick(
    session_id: str, clip_ids: list, clip_info: list, clips_dict: dict,
    is_done: bool, is_active: bool, is_open: bool,
    total_s: float,
) -> None:
    with _step('Pick clips to use in video',
               'Click a green bar to play it — click again to skip (red)',
               is_done=is_done, is_active=is_active, is_open=is_open):

        with db_session() as db:
            marks = (
                db.query(Mark)
                .join(Clip, Mark.clip_id == Clip.id)
                .filter(Mark.clip_id.in_(clip_ids))
                .filter(Mark.status.in_([MarkStatus.CANDIDATE, MarkStatus.ACCEPTED,
                                         MarkStatus.REJECTED]))
                .order_by(Clip.clip_order, Mark.in_s)
                .all()
            )
            mark_data = [
                (m.id, m.clip_id, m.in_s, m.out_s, m.score or 0.0, m.source)
                for m in marks
            ]
            clips_data = {cid: (c.filename, c.proxy_path) for cid, c in clips_dict.items()}

        if not mark_data:
            ui.label('No candidate clips found yet. Analysis may still be running.').style(
                'color:#666; padding:0.75rem 1rem; font-size:0.85rem'
            )
            return

        # All marks start accepted unless already explicitly rejected in DB
        rejected_ids = {m.id for m in marks if m.status == MarkStatus.REJECTED}

        with ui.column().style('width:100%; padding:0'):

            # Top bar
            with ui.row().style(
                'align-items:center; justify-content:space-between; '
                'padding:0.4rem 0.75rem; border-bottom:1px solid #1a1a1a; background:#111'
            ):
                n_acc = len(mark_data) - len(rejected_ids)
                n_rej = len(rejected_ids)
                ui.html(
                    f'<span id="pick-summary" style="color:#777;font-size:0.82rem">'
                    f'{n_acc} in  ·  {n_rej} out</span>',
                    sanitize=False,
                )
                ui.label('Click bar to play · click again to toggle skip').style(
                    'color:#444; font-size:0.72rem'
                )

                async def _apply() -> None:
                    raw = await ui.run_javascript(
                        'JSON.stringify(window.axedup_decisions || {})'
                    )
                    js_dec = json.loads(raw)
                    acc = rej = 0
                    with db_session() as db2:
                        for mid2, keep in js_dec.items():
                            m2 = db2.query(Mark).filter(Mark.id == mid2).first()
                            if m2:
                                m2.status = MarkStatus.ACCEPTED if keep else MarkStatus.REJECTED
                                if keep: acc += 1
                                else: rej += 1
                    ui.notify(f'Saved: {acc} in, {rej} out', type='positive')

                ui.button('Save picks', on_click=_apply).props('color=positive size=sm')

            # ── Proportional timeline ─────────────────────────────────────────
            ui.html(
                _timeline_html(mark_data, clip_info, total_s),
                sanitize=False,
            ).style('width:100%; display:block')

            # Inject JS: state dict + axedupMarkClick function
            init = {mid: (mid not in rejected_ids) for mid, *_ in mark_data}
            ui.run_javascript(f'''
window.axedup_decisions = {json.dumps(init)};

window.axedupMarkClick = function(el) {{
  var mid = el.dataset.mid;
  var cid = el.dataset.cid;
  var ins = parseFloat(el.dataset.ins);

  window.axedup_decisions[mid] = !window.axedup_decisions[mid];
  el.style.background = window.axedup_decisions[mid] ? "#2a7a2a" : "#7a2a2a";

  var acc = Object.values(window.axedup_decisions).filter(Boolean).length;
  var tot = Object.keys(window.axedup_decisions).length;
  var s = document.getElementById("pick-summary");
  if (s) s.textContent = acc + " in  ·  " + (tot - acc) + " out";

  var v = document.getElementById("axedup-player");
  if (!v) return;
  var url = "/proxies/" + cid + ".mp4";
  var doSeek = function() {{ v.currentTime = ins; v.play(); }};
  if (v.src.endsWith(url)) {{
    doSeek();
  }} else {{
    v.src = url; v.load();
    if (v.readyState >= 1) {{ doSeek(); }}
    else {{ v.addEventListener("loadedmetadata", doSeek, {{once: true}}); }}
  }}
}};
''')

            # ── Video player ──────────────────────────────────────────────────
            first_url = next(
                (f'/proxies/{cid}.mp4' for cid, (_, pp) in clips_data.items() if pp), ''
            )
            ui.html(
                f'<video id="axedup-player" src="{first_url}" controls preload="auto"'
                f' style="width:100%;max-height:40vh;display:block;background:#000"></video>',
                sanitize=False,
            )

# ── Step 5 — Combine clips ────────────────────────────────────────────────────

def _render_step_combine(
    session_id: str,
    is_done: bool, is_active: bool, is_open: bool,
) -> None:
    with _step('Combine clips',
               'Choose a colour grade, then build the preview',
               is_done=is_done, is_active=is_active, is_open=is_open):

        with ui.column().style('padding:0.75rem 1rem; gap:0.6rem; width:100%'):

            # Show existing preview if already assembled
            preview_path = config.PREVIEW_DIR / f'{session_id}_preview.mp4'
            if preview_path.exists():
                ui.html(
                    f'<video src="/previews/{session_id}_preview.mp4" controls preload="metadata"'
                    f' style="width:100%;max-height:45vh;display:block;background:#000;margin-bottom:0.5rem"></video>',
                    sanitize=False,
                )

            with ui.row().style('gap:1rem; align-items:flex-end; flex-wrap:wrap'):
                grade_sel = ui.select(options=_GRADES, value='natural', label='Colour grade').style('min-width:140px')
                source_sel = ui.select(
                    options=['All accepted', 'Still-frame picks', 'Motion picks', 'Telemetry picks'],
                    value='All accepted',
                    label='Which picks',
                ).style('min-width:160px')
                # music_input placeholder — assembly does not yet support music
                music_input = ui.input(value='').style('display:none')

            err_lbl    = ui.label('').style('color:#e57373; font-size:0.82rem; min-height:1rem')
            status_lbl = ui.label('').style('color:#777; font-size:0.82rem; min-height:1rem')

            assemble_btn = ui.button(
                'Re-assemble' if preview_path.exists() else 'Combine clips',
                on_click=lambda: _start_assemble(session_id, grade_sel, source_sel, music_input,
                                                  assemble_btn, err_lbl, status_lbl),
            ).props('color=positive')


def _start_assemble(session_id, grade_sel, source_sel, music_input,
                    btn, err_lbl, status_lbl) -> None:
    source_map = {
        'All accepted':       None,
        'Still-frame picks':  'jpg',
        'Motion picks':       'proxy',
        'Telemetry picks':    'telemetry',
    }
    grade   = grade_sel.value
    src_val = source_map.get(source_sel.value)

    btn.set_enabled(False)
    btn.set_text('Combining…')
    err_lbl.set_text('')
    status_lbl.set_text('Cutting segments and encoding preview…')

    task_key   = f'assemble_{session_id}'
    start_time = time.time()
    state.start_task(task_key)

    def _run() -> None:
        try:
            from axedup.processing.assembly import assemble_session
            assemble_session(session_id, grade_override=grade,
                             source_filter=src_val)
            state.finish_task(task_key)
        except Exception as exc:
            state.finish_task(task_key, error=str(exc))

    threading.Thread(target=_run, daemon=True).start()

    def _poll() -> None:
        task = state.get_task(task_key)
        if not task:
            return
        if task.error:
            err_lbl.set_text(task.error)
            btn.set_enabled(True)
            btn.set_text('Retry')
            poll_timer.active = False
            return
        elapsed = _fmt(time.time() - start_time)
        if task.done:
            status_lbl.set_text(f'Done in {elapsed} — preview ready.')
            btn.set_enabled(True)
            btn.set_text('Re-assemble')
            poll_timer.active = False
            ui.navigate.to(f'/session/{session_id}')
        else:
            status_lbl.set_text(f'Cutting segments and encoding preview… {elapsed} elapsed')

    poll_timer = ui.timer(2.0, _poll)

# ── Step 6 — Export video ─────────────────────────────────────────────────────

def _render_step_export(
    session_id: str,
    is_done: bool, is_active: bool, is_open: bool,
) -> None:
    with _step('Export video',
               'Encode the final file ready for sharing',
               is_done=is_done, is_active=is_active, is_open=is_open):

        with ui.column().style('padding:0.75rem 1rem; gap:0.5rem; width:100%'):
            ui.label('Aspect ratios').style('color:#aaa; font-size:0.82rem')
            aspect_16 = ui.checkbox('16:9  (YouTube / landscape)', value=True)
            aspect_9  = ui.checkbox('9:16  (Reels / portrait)', value=False)

            ui.separator().style('margin:0.4rem 0; border-color:#222')

            ui.label('Output folder').style('color:#aaa; font-size:0.78rem')
            with ui.row().style('align-items:center; gap:0.5rem; width:100%; max-width:440px'):
                out_input = ui.input(value=str(config.OUTPUT_DIR)).style('flex:1; color:#eee')
                from axedup.ui.filepicker import browse_button
                browse_button(lambda p: out_input.set_value(p), tooltip='Browse output folder')

            err_lbl    = ui.label('').style('color:#e57373; font-size:0.82rem; min-height:1rem')
            status_lbl = ui.label('').style('color:#777; font-size:0.82rem; min-height:1rem')
            out_container = ui.element('div')

            export_btn = ui.button(
                'Export',
                on_click=lambda: _start_export(session_id, aspect_16, aspect_9, out_input,
                                               export_btn, err_lbl, status_lbl, out_container),
            ).props('color=positive').style('margin-top:0.25rem')

            _show_exports(session_id, out_container)


def _start_export(session_id, aspect_16, aspect_9, out_input,
                  btn, err_lbl, status_lbl, out_container) -> None:
    aspects = []
    if aspect_16.value: aspects.append('16:9')
    if aspect_9.value:  aspects.append('9:16')
    if not aspects:
        err_lbl.set_text('Select at least one aspect ratio')
        return

    out_dir = out_input.value.strip() or None
    btn.set_enabled(False)
    btn.set_text('Exporting…')
    err_lbl.set_text('')
    status_lbl.set_text('Encoding…')

    task_key   = f'export_{session_id}'
    start_time = time.time()
    state.start_task(task_key)

    def _run() -> None:
        try:
            from axedup.processing.export import export_session
            export_session(session_id, aspects=aspects,
                           output_dir=Path(out_dir) if out_dir else None)
            state.finish_task(task_key)
        except Exception as exc:
            state.finish_task(task_key, error=str(exc))

    threading.Thread(target=_run, daemon=True).start()

    def _poll() -> None:
        task = state.get_task(task_key)
        if not task:
            return
        elapsed = _fmt(time.time() - start_time)
        if task.error:
            err_lbl.set_text(task.error)
            btn.set_enabled(True)
            btn.set_text('Export')
            poll_timer.active = False
            return
        if task.done:
            status_lbl.set_text(f'Done in {elapsed}.')
            btn.set_enabled(True)
            btn.set_text('Export again')
            poll_timer.active = False
            _show_exports(session_id, out_container)
        else:
            status_lbl.set_text(f'Encoding… {elapsed} elapsed')

    poll_timer = ui.timer(2.0, _poll)


def _show_exports(session_id: str, container) -> None:
    container.clear()
    with container:
        with db_session() as db:
            exports = (
                db.query(Export)
                .filter(Export.session_id == session_id)
                .order_by(Export.exported_at.desc())
                .all()
            )
        if not exports:
            return
        ui.label('Output files').style('color:#aaa; font-size:0.8rem; margin-top:0.5rem; margin-bottom:0.3rem')
        for exp in exports:
            with ui.card().style('background:#1a1a1a; margin-bottom:0.3rem; padding:0.4rem 0.6rem'):
                with ui.row().style('align-items:center; gap:0.75rem'):
                    ui.badge(exp.aspect).style('background:#1a2a1a; color:#5a9a5a; font-size:0.7rem')
                    ui.label(exp.filepath).style(
                        'color:#777; font-size:0.75rem; font-family:monospace; flex:1; word-break:break-all'
                    )

# ── Delete / stop control ─────────────────────────────────────────────────────

def _delete_session_button(session_id: str) -> None:
    dlg = ui.dialog()
    with dlg, ui.card().style('background:#1e1e1e; padding:1.25rem; min-width:300px'):
        ui.label('Delete this session?').style('color:#eee; font-weight:600; margin-bottom:0.4rem')
        ui.label('Removes all DB records and cached files (proxies, thumbnails, preview).').style(
            'color:#777; font-size:0.78rem; margin-bottom:1rem'
        )
        with ui.row().style('gap:0.5rem; justify-content:flex-end'):
            ui.button('Cancel', on_click=dlg.close).props('flat')
            ui.button('Delete', on_click=lambda: (_do_delete(session_id), dlg.close())).props('color=negative')

    ui.button(icon='delete_outline', on_click=dlg.open).props('flat round dense').style('color:#5a3030').tooltip('Delete session')


def _do_delete(session_id: str) -> None:
    with db_session() as db:
        clips    = db.query(Clip).filter(Clip.session_id == session_id).all()
        clip_ids = [c.id for c in clips]
        mark_ids = [
            m.id
            for c in clips
            for m in db.query(Mark).filter(Mark.clip_id == c.id).all()
        ]
        s = db.query(Session).filter(Session.id == session_id).first()
        if s:
            db.delete(s)

    # Wipe cached files
    (config.PREVIEW_DIR / f'{session_id}_preview.mp4').unlink(missing_ok=True)
    for cid in clip_ids:
        (config.PROXY_DIR / f'{cid}.mp4').unlink(missing_ok=True)
        shutil.rmtree(config.THUMB_DIR / cid, ignore_errors=True)
        shutil.rmtree(config.JPEG_FRAMES_DIR / cid, ignore_errors=True)
    for mid in mark_ids:
        (config.SEGMENT_DIR / f'{mid}.mp4').unlink(missing_ok=True)

    ui.navigate.to('/')

# ── Main session page ─────────────────────────────────────────────────────────

@ui.page('/session/{session_id}')
def session_page(session_id: str) -> None:
    ui.dark_mode().enable()

    with db_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            ui.label('Session not found.').style('color:#e57373; padding:2rem')
            return
        status  = session.status
        sport   = session.sport or 'unknown'
        src     = session.source_path or ''
        created = session.created_at
        clips   = (
            db.query(Clip)
            .filter(Clip.session_id == session_id)
            .order_by(Clip.clip_order).all()
        )
        clip_ids    = [c.id for c in clips]
        clip_info   = [(c.id, c.filename, c.duration_s) for c in clips]
        clips_dict  = {c.id: c for c in clips}
        total_s     = sum(c.duration_s or 0 for c in clips)
        mark_count  = db.query(Mark).filter(Mark.clip_id.in_(clip_ids)).count()
        # Determine motion method from mark sources
        sample_mark = (
            db.query(Mark)
            .join(Clip, Mark.clip_id == Clip.id)
            .filter(Clip.session_id == session_id)
            .first()
        )

    task     = state.get_task(session_id)
    progress = state.get_clip_progress(session_id)

    # Determine motion label
    if sample_mark and 'jpg' in (sample_mark.source or ''):
        split_label = 'Split into clips (with still frames)'
    elif sample_mark:
        split_label = 'Split into clips (with motion)'
    else:
        split_label = 'Split into clips'   # analysis not yet done

    # Step status calculations
    analyzing = status in (SessionStatus.INGESTED, SessionStatus.ANALYZING) and task is not None
    post_analysis = status not in (
        SessionStatus.IMPORTING, SessionStatus.INGESTED, SessionStatus.ANALYZING
    )

    s1_done  = True
    s2_done  = post_analysis
    s3_done  = post_analysis
    s4_done  = status in (SessionStatus.ASSEMBLED, SessionStatus.EXPORTED)
    s5_done  = status == SessionStatus.EXPORTED
    s6_done  = False   # re-exportable at any time

    # Drive step headers from actual live progress at page-load time.
    # The pipeline is per-clip sequential: proxy first, then thumbnails/scenes/motion.
    # Step 2 is orange while proxies are still pending/running; step 3 goes orange once
    # any split stage (thumbnails/scenes/motion) has started.
    _split_started = analyzing and any(
        progress.get(cid, {}).get(stage, StageState()).status in ('running', 'done', 'skipped')
        for cid in clip_ids
        for stage in ('thumbnails', 'scenes', 'motion')
    )
    s2_active = analyzing and not _split_started
    s3_active = analyzing and _split_started
    s4_active = status == SessionStatus.READY
    s5_active = status in (SessionStatus.READY, SessionStatus.ASSEMBLED, SessionStatus.EXPORTED)
    s6_active = status in (SessionStatus.ASSEMBLED, SessionStatus.EXPORTED)

    # ── Layout ────────────────────────────────────────────────────────────────
    _mini = [False]

    drawer = ui.left_drawer(value=True).style(
        'background:#1a1a1a; border-right:1px solid #222'
    )
    drawer.props('breakpoint=0 width=180 mini-width=48')
    with drawer:
        sidebar('session', session_id, status)

    def _toggle_nav() -> None:
        _mini[0] = not _mini[0]
        if _mini[0]:
            drawer.props('mini')
        else:
            drawer.props(remove='mini')

    with ui.column().style('width:100%; min-height:100vh; background:#111; padding:0'):

        # Header
        with ui.row().style(
            'align-items:center; justify-content:space-between; '
            'padding:0.5rem 1rem; border-bottom:1px solid #1a1a1a; '
            'background:#141414; flex-shrink:0'
        ):
            with ui.row().style('align-items:center; gap:0.5rem'):
                ui.button(icon='menu', on_click=_toggle_nav).props('flat round dense').style('color:#555').tooltip('Collapse/expand sidebar')
                with ui.column().style('gap:0.05rem'):
                    date_str = created.strftime('%Y-%m-%d  %H:%M') if created else ''
                    ui.label(f'{sport}  ·  {date_str}').style('color:#eee; font-size:0.95rem; font-weight:600')
                    m, s = divmod(int(total_s), 60)
                    ui.label(f'{len(clip_ids)} clips  ·  {m}m{s:02d}s').style('color:#555; font-size:0.75rem')
            with ui.row().style('gap:0.35rem; align-items:center'):
                ui.button(icon='pause_circle', on_click=lambda: ui.notify('Pause not yet available', type='info')).props('flat round dense').style('color:#666').tooltip('Pause (coming soon)')
                _delete_session_button(session_id)

        # ── Timing bar — shown during analysis; persists as final time when done ─
        timing_lbl = None
        _est_s = max(60, int(total_s * 1.0))
        _est_str = _fmt(_est_s)
        with ui.row().style(
            'padding:0.3rem 1rem; background:#0d0d0d; border-bottom:1px solid #1a1a1a;'
            'align-items:center; gap:1rem'
        ):
            if analyzing:
                timing_lbl = ui.label(f'Estimated: ~{_est_str}  ·  Elapsed: 0s').style(
                    'color:#555; font-size:0.75rem; font-family:monospace'
                )
            elif post_analysis:
                ui.label(f'Analysis complete  ·  Estimated: ~{_est_str}').style(
                    'color:#3a5a3a; font-size:0.75rem; font-family:monospace'
                )

        # ── Step accordion ────────────────────────────────────────────────────
        with ui.column().style('width:100%; gap:0; padding:0'):

            _render_step_choose(src, sport, clip_info, total_s)

            badge_els_s2 = _render_step_working_copy(
                session_id, clip_info,
                is_done=s2_done, is_active=s2_active,
                is_open=analyzing,   # open during analysis; closed when done
                progress=progress,
            )

            badge_els_s3 = _render_step_split(
                session_id, clip_info, split_label,
                is_done=s3_done, is_active=s3_active, is_open=analyzing,
                progress=progress, mark_count=mark_count,
            )

            _render_step_pick(
                session_id, clip_ids, clip_info, clips_dict,
                is_done=s4_done, is_active=s4_active, is_open=s4_active,
                total_s=total_s,
            )

            _render_step_combine(
                session_id,
                is_done=s5_done, is_active=s5_active,
                is_open=s6_active and not s4_active,
            )

            _render_step_export(
                session_id,
                is_done=s6_done, is_active=s6_active, is_open=s6_active,
            )

    # ── Polling timer — only during active analysis ───────────────────────────
    if analyzing:
        _poll_start = time.time()
        _est_str    = _fmt(max(60, int(total_s * 1.0)))

        def poll() -> None:
            cur_task = state.get_task(session_id)
            prog     = state.get_clip_progress(session_id)

            # Update timing label
            if timing_lbl is not None:
                elapsed = _fmt(time.time() - _poll_start)
                timing_lbl.set_text(f'Estimated: ~{_est_str}  ·  Elapsed: {elapsed}')

            # Update step-2 proxy badges
            for cid, el in badge_els_s2.items():
                s = prog.get(cid, {}).get('proxy', StageState())
                el.set_content(_badge_html(s, _STAGE_LABEL['proxy'], 'proxy'))

            # Update step-3 thumbnails/scenes/motion badges
            for cid, stage_els in badge_els_s3.items():
                for stage, el in stage_els.items():
                    s = prog.get(cid, {}).get(stage, StageState())
                    el.set_content(_badge_html(s, _STAGE_LABEL[stage], stage))

            if cur_task and cur_task.error:
                ui.notify(f'Analysis error: {cur_task.error}', type='negative', timeout=0)
                timer.active = False
                return

            if cur_task and cur_task.done:
                timer.active = False
                ui.navigate.to(f'/session/{session_id}')

        timer = ui.timer(0.5, poll)
