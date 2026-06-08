"""
Session view — ui.stepper workflow.
Route: /session/{session_id}

Steps: Input → Analyze → Pick → Combine → Export
header-nav=false enforces forward-only progression via action-panel buttons.
Done steps show a checkmark and can be revisited via Back buttons.
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
    Clip, Export, Mark, MarkStatus, Session, SessionStatus,
)
from axedup.ui import state
from axedup.ui.state import StageState
from axedup.ui.layout import sidebar

# ── Constants ──────────────────────────────────────────────────────────────────

_STAGES      = ['proxy', 'thumbnails', 'scenes', 'motion']
_STAGE_LABEL = {'proxy': 'Proxy', 'thumbnails': 'Snapshots', 'scenes': 'Scenes', 'motion': 'Motion'}
_GRADES      = ['punchy', 'cinematic', 'natural', 'warm', 'cool', 'vibrant']

# Action panel: fixed right column inside each step
_AP = (
    'width:210px;min-width:210px;background:#141414;border-left:1px solid #1a1a1a;'
    'padding:1rem 0.85rem;display:flex;flex-direction:column;gap:0.6rem'
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def _fmt(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f'{m}m {s:02d}s' if m else f'{s}s'


def _time_fmt(ts: float) -> str:
    m, s = divmod(int(ts), 60)
    return f'{m}:{s:02d}'


def _tl_html(s: StageState) -> str:
    """Traffic-light dot for one pipeline stage."""
    if s.status == 'running':
        detail = f' {s.pct}%' if s.pct is not None else ''
        return (
            f'<span style="display:inline-flex;align-items:center;gap:3px">'
            f'<span class="tl-run" style="width:11px;height:11px;border-radius:50%;'
            f'background:#f0a040;display:inline-block;flex-shrink:0"></span>'
            f'<span style="font-size:0.62rem;color:#f0a040">{detail.strip()}</span>'
            f'</span>'
        )
    if s.status in ('done', 'skipped'):
        return (
            '<span style="width:11px;height:11px;border-radius:50%;'
            'background:#5a9a5a;display:inline-block"></span>'
        )
    if s.status == 'error':
        return (
            '<span style="width:11px;height:11px;border-radius:50%;'
            'background:#c0392b;display:inline-block"></span>'
        )
    return (
        '<span style="width:11px;height:11px;border-radius:50%;'
        'background:#2a2a2a;border:1px solid #3a3a3a;display:inline-block"></span>'
    )


def _timeline_html(mark_data: list, clip_info: list) -> str:
    """Proportional timeline bar — green accepted bars, no thumbnails."""
    marks_by_clip: dict[str, list] = {}
    for mid, cid, in_s, out_s, *_ in mark_data:
        marks_by_clip.setdefault(cid, []).append((mid, in_s, out_s))

    _BG = ['#1a1a1a', '#171717', '#1c1c1c', '#181818']
    out = [
        '<div style="display:flex;width:100%;gap:2px;background:#0a0a0a;'
        'padding:6px 8px 8px;box-sizing:border-box;align-items:stretch">'
    ]
    for i, (clip_id, fname, dur_s) in enumerate(clip_info):
        if not dur_s:
            continue
        label = (fname[:10] + '…') if len(fname) > 10 else fname
        out.append(
            f'<div style="flex:{max(dur_s,1.0):.1f};min-width:16px;position:relative;'
            f'border-radius:3px;overflow:hidden;background:{_BG[i%4]};height:48px">'
            # clip label strip
            f'<div style="position:absolute;top:0;left:0;right:0;height:16px;'
            f'background:rgba(0,0,0,0.55);display:flex;align-items:center;'
            f'padding:0 4px;pointer-events:none">'
            f'<span style="font-size:0.5rem;color:#999;white-space:nowrap;'
            f'overflow:hidden;text-overflow:ellipsis">'
            f'{label} · {_fmt(int(dur_s))}</span></div>'
        )
        for mid, in_s, out_s in marks_by_clip.get(clip_id, []):
            in_pct = in_s / dur_s * 100
            w_pct  = (out_s - in_s) / dur_s * 100
            tip    = f'{_time_fmt(in_s)}–{_time_fmt(out_s)} ({out_s - in_s:.1f}s)'
            out.append(
                f'<div id="mark-{mid}" data-mid="{mid}" data-cid="{clip_id}" data-ins="{in_s}"'
                f' style="position:absolute;top:18px;left:{in_pct:.2f}%;'
                f'width:max({w_pct:.2f}%,6px);bottom:2px;background:#2a7a2a;'
                f'border-radius:2px;cursor:pointer;transition:background 0.15s;'
                f'display:flex;align-items:center;justify-content:center;overflow:hidden"'
                f' onclick="axedupMarkClick(this)" title="{tip}">'
                f'<span class="mark-icon" style="font-size:0.5rem;color:rgba(255,255,255,0.85);'
                f'pointer-events:none;line-height:1">✓</span>'
                f'</div>'
            )
        out.append('</div>')
    out.append('</div>')
    return ''.join(out)


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


# ── Delete ─────────────────────────────────────────────────────────────────────

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
        mark_ids = [m.id for c in clips for m in db.query(Mark).filter(Mark.clip_id == c.id).all()]
        s = db.query(Session).filter(Session.id == session_id).first()
        if s:
            db.delete(s)
    (config.PREVIEW_DIR / f'{session_id}_preview.mp4').unlink(missing_ok=True)
    for cid in clip_ids:
        (config.PROXY_DIR / f'{cid}.mp4').unlink(missing_ok=True)
        shutil.rmtree(config.THUMB_DIR / cid, ignore_errors=True)
        shutil.rmtree(config.JPEG_FRAMES_DIR / cid, ignore_errors=True)
    for mid in mark_ids:
        (config.SEGMENT_DIR / f'{mid}.mp4').unlink(missing_ok=True)
    ui.navigate.to('/')


# ── Main page ──────────────────────────────────────────────────────────────────

@ui.page('/session/{session_id}')
def session_page(session_id: str) -> None:
    ui.dark_mode().enable()
    ui.add_head_html(
        '<style>'
        '@keyframes tl-pulse{0%,100%{opacity:1}50%{opacity:0.35}}'
        '.tl-run{animation:tl-pulse 1s ease-in-out infinite}'
        # Remove Quasar's default stepper content padding so we control layout fully
        '.q-stepper__content{padding:0!important}'
        '.q-stepper__step-inner{padding:0!important}'
        '</style>'
    )

    # ── DB load ────────────────────────────────────────────────────────────────
    with db_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            ui.label('Session not found.').style('color:#e57373; padding:2rem')
            return
        status   = session.status
        sport    = session.sport or 'unknown'
        src      = session.source_path or ''
        created  = session.created_at
        clips    = db.query(Clip).filter(Clip.session_id == session_id).order_by(Clip.clip_order).all()
        clip_ids   = [c.id for c in clips]
        clip_info  = [(c.id, c.filename, c.duration_s) for c in clips]
        clips_dict = {c.id: c for c in clips}
        total_s    = sum(c.duration_s or 0 for c in clips)
        mark_count = db.query(Mark).filter(Mark.clip_id.in_(clip_ids)).count()

    task     = state.get_task(session_id)
    progress = state.get_clip_progress(session_id)

    analyzing     = (status in (SessionStatus.INGESTED, SessionStatus.ANALYZING)
                     and task is not None and not task.done)
    post_analysis = status not in (SessionStatus.IMPORTING, SessionStatus.INGESTED, SessionStatus.ANALYZING)
    preview_path  = config.PREVIEW_DIR / f'{session_id}_preview.mp4'

    # Step completion flags
    analyze_done = post_analysis
    pick_done    = status in (SessionStatus.ASSEMBLED, SessionStatus.EXPORTED)
    combine_done = status == SessionStatus.EXPORTED

    # Which step to open
    if analyzing:
        initial_step = 'analyze'
    elif post_analysis and not pick_done:
        initial_step = 'pick'
    elif pick_done and not combine_done:
        initial_step = 'combine'
    elif combine_done:
        initial_step = 'export'
    else:
        initial_step = 'input'

    # Refs used by the poll timer — must be defined before the stepper block
    timing_lbl       = None   # ui.label inside Analyze step
    tl_els: dict[str, dict[str, ui.html]] = {}   # {clip_id: {stage: ui.html}}
    step_analyze_ref = [None]   # the ui.step element for Analyze
    continue_btn_ref = [None]   # "Continue to Pick" button

    # ── App shell ──────────────────────────────────────────────────────────────
    _mini = [False]
    drawer = ui.left_drawer(value=True).style('background:#1a1a1a; border-right:1px solid #222')
    drawer.props('breakpoint=0 width=180 mini-width=48')
    with drawer:
        sidebar('session', session_id, status)

    def _toggle_nav() -> None:
        _mini[0] = not _mini[0]
        if _mini[0]: drawer.props('mini')
        else: drawer.props(remove='mini')

    with ui.column().style('width:100%; min-height:100vh; background:#111; padding:0; gap:0'):

        # Top header bar
        with ui.row().style(
            'align-items:center; justify-content:space-between; '
            'padding:0.4rem 1rem; border-bottom:1px solid #1a1a1a; background:#141414; flex-shrink:0'
        ):
            with ui.row().style('align-items:center; gap:0.5rem'):
                ui.button(icon='menu', on_click=_toggle_nav).props('flat round dense').style('color:#555').tooltip('Toggle sidebar')
                with ui.column().style('gap:0.02rem'):
                    date_str = created.strftime('%Y-%m-%d  %H:%M') if created else ''
                    ui.label(f'{sport}  ·  {date_str}').style('color:#eee; font-size:0.9rem; font-weight:600')
                    m0, s0 = divmod(int(total_s), 60)
                    ui.label(f'{len(clip_ids)} clip{"s" if len(clip_ids)!=1 else ""}  ·  {m0}m{s0:02d}s').style('color:#555; font-size:0.72rem')
            _delete_session_button(session_id)

        # ── Stepper ────────────────────────────────────────────────────────────
        with ui.stepper(value=initial_step).props(
            'header-nav=false flat animated'
        ).style('width:100%; flex:1; background:#111') as stepper:

            # ── Step 1: Input ──────────────────────────────────────────────────
            with ui.step('input', title='Input', icon='videocam') as _s_input:
                _s_input.props(add='done')   # always done; session exists

                with ui.row().style('width:100%; gap:0'):
                    # Left: video player + clip list
                    with ui.column().style('flex:1; min-width:0; gap:0'):
                        first_proxy = next(
                            (c.id for c in clips if (config.PROXY_DIR / f'{c.id}.mp4').exists()), None
                        )
                        proxy_src = f'/proxies/{first_proxy}.mp4' if first_proxy else ''
                        ui.html(
                            f'<video src="{proxy_src}" controls preload="auto" '
                            f'style="width:100%;height:45vh;display:block;background:#000;object-fit:contain"></video>',
                            sanitize=False,
                        )
                        with ui.column().style('padding:0.75rem 1rem; gap:0.35rem; overflow-y:auto'):
                            ui.label('Source').style('color:#444; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.06em')
                            ui.label(src).style('color:#555; font-size:0.78rem; font-family:monospace; word-break:break-all; margin-bottom:0.35rem')
                            ui.label('Clips').style('color:#444; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.06em')
                            for cid, fname, dur_s in clip_info:
                                with ui.row().style('align-items:center; gap:0.75rem'):
                                    ui.label(fname).style('color:#aaa; font-size:0.82rem; font-family:monospace; flex:1')
                                    ui.label(_fmt(int(dur_s or 0))).style('color:#555; font-size:0.78rem')

                    # Right: action panel
                    with ui.column().style(_AP):
                        ui.label('Input').style('color:#eee; font-weight:600; font-size:0.95rem')
                        ui.badge(sport).style('background:#1a2a1a; color:#5a9a5a; font-size:0.75rem; align-self:flex-start')
                        ui.label(f'{len(clip_ids)} clip{"s" if len(clip_ids)!=1 else ""}  ·  {_fmt(int(total_s))}').style('color:#666; font-size:0.8rem')
                        ui.element('div').style('flex:1')
                        if analyze_done or analyzing:
                            ui.button(
                                'View Analysis →',
                                on_click=lambda: stepper.set_value('analyze'),
                            ).props('flat color=positive size=sm')

            # ── Step 2: Analyze ────────────────────────────────────────────────
            with ui.step('analyze', title='Analyze', icon='analytics') as _s_analyze:
                step_analyze_ref[0] = _s_analyze
                if analyze_done:
                    _s_analyze.props(add='done')

                with ui.row().style('width:100%; gap:0'):
                    # Left: traffic light grid
                    with ui.column().style('flex:1; min-width:0; gap:0'):

                        # Timing / status bar
                        with ui.row().style(
                            'align-items:center; gap:0.75rem; padding:0.5rem 1rem; '
                            'background:#0d0d0d; border-bottom:1px solid #1a1a1a'
                        ):
                            if analyzing:
                                est_s = max(60, int(total_s * 1.0))
                                timing_lbl = ui.label(f'Est. ~{_fmt(est_s)}  ·  Elapsed: 0s').style(
                                    'color:#555; font-size:0.75rem; font-family:monospace'
                                )
                            elif post_analysis:
                                ui.icon('check_circle').style('color:#3a6a3a; font-size:1rem')
                                ui.label(
                                    f'Analysis complete  ·  {mark_count} candidate clip{"s" if mark_count!=1 else ""} found'
                                ).style('color:#3a6a3a; font-size:0.78rem; font-family:monospace')
                            else:
                                ui.label('Analysis not started.').style('color:#444; font-size:0.78rem')

                        # Column headers
                        with ui.row().style(
                            'padding:0.3rem 1rem; gap:0; align-items:center; '
                            'border-bottom:1px solid #1a1a1a; background:#0a0a0a'
                        ):
                            ui.label('Clip').style('color:#333; font-size:0.7rem; letter-spacing:0.06em; text-transform:uppercase; flex:1')
                            for stage in _STAGES:
                                ui.label(_STAGE_LABEL[stage]).style(
                                    'color:#333; font-size:0.7rem; letter-spacing:0.06em; text-transform:uppercase; '
                                    'width:90px; text-align:center'
                                )

                        # One row per clip
                        for clip_id, fname, _dur_s in clip_info:
                            clip_prog = progress.get(clip_id, {})
                            tl_els[clip_id] = {}
                            with ui.row().style(
                                'padding:0.45rem 1rem; gap:0; align-items:center; border-bottom:1px solid #111'
                            ):
                                ui.label(fname).style(
                                    'color:#888; font-size:0.8rem; font-family:monospace; flex:1; '
                                    'overflow:hidden; text-overflow:ellipsis; white-space:nowrap'
                                )
                                for stage in _STAGES:
                                    s = clip_prog.get(stage, StageState())
                                    el = ui.html(_tl_html(s), sanitize=False, tag='span').style(
                                        'width:90px; display:inline-flex; justify-content:center; align-items:center'
                                    )
                                    tl_els[clip_id][stage] = el

                    # Right: action panel
                    with ui.column().style(_AP):
                        ui.label('Analyze').style('color:#eee; font-weight:600; font-size:0.95rem')
                        ui.label('Building a working copy and finding candidate clips.').style('color:#555; font-size:0.75rem')
                        ui.element('div').style('flex:1')
                        ui.button('← Back', on_click=stepper.previous).props('flat size=sm').style('color:#555')
                        _cbtn = ui.button(
                            'Continue to Pick →',
                            on_click=stepper.next,
                        ).props(f'color=positive{"" if analyze_done else " disable"}')
                        continue_btn_ref[0] = _cbtn

            # ── Step 3: Pick ───────────────────────────────────────────────────
            with ui.step('pick', title='Pick', icon='playlist_add_check') as _s_pick:
                if pick_done:
                    _s_pick.props(add='done')

                with db_session() as db:
                    marks = (
                        db.query(Mark)
                        .join(Clip, Mark.clip_id == Clip.id)
                        .filter(Mark.clip_id.in_(clip_ids))
                        .filter(Mark.status.in_([MarkStatus.CANDIDATE, MarkStatus.ACCEPTED, MarkStatus.REJECTED]))
                        .order_by(Clip.clip_order, Mark.in_s)
                        .all()
                    )
                    mark_data  = [(m.id, m.clip_id, m.in_s, m.out_s, m.score or 0.0, m.source) for m in marks]
                    clips_data = {cid: (c.filename, c.proxy_path) for cid, c in clips_dict.items()}

                rejected_ids = {m.id for m in marks if m.status == MarkStatus.REJECTED}
                n_acc = len(mark_data) - len(rejected_ids)

                async def _save_picks(advance: bool = False) -> None:
                    raw = await ui.run_javascript('JSON.stringify(window.axedup_decisions || {})')
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
                    if advance:
                        stepper.next()

                with ui.row().style('width:100%; gap:0'):
                    with ui.column().style('flex:1; min-width:0; gap:0'):
                        if not mark_data:
                            ui.label(
                                'No candidate clips found yet — analysis may still be running.'
                            ).style('color:#666; padding:1rem 1.25rem; font-size:0.85rem')
                        else:
                            # Summary bar
                            with ui.row().style(
                                'align-items:center; justify-content:space-between; padding:0.35rem 0.75rem; '
                                'background:#0d0d0d; border-bottom:1px solid #1a1a1a'
                            ):
                                ui.html(
                                    f'<span id="pick-summary" style="color:#777;font-size:0.82rem">'
                                    f'{n_acc} in  ·  {len(mark_data)-n_acc} out</span>',
                                    sanitize=False,
                                )
                                ui.label('Click green bar to play · click again to skip').style('color:#333; font-size:0.72rem')

                            # Proportional timeline
                            ui.html(
                                _timeline_html(mark_data, clip_info),
                                sanitize=False,
                            ).style('width:100%; display:block')

                            # Proxy video player
                            first_url = next(
                                (f'/proxies/{cid}.mp4' for cid, (_, pp) in clips_data.items() if pp), ''
                            )
                            ui.html(
                                f'<video id="axedup-player" src="{first_url}" controls preload="auto"'
                                f' style="width:100%;height:40vh;display:block;'
                                f'background:#000;object-fit:contain"></video>',
                                sanitize=False,
                            )

                            # JS: decisions dict + click handler
                            init = {mid: (mid not in rejected_ids) for mid, *_ in mark_data}
                            ui.run_javascript(f'''
window.axedup_decisions = {json.dumps(init)};
window.axedupMarkClick = function(el) {{
  var mid = el.dataset.mid, cid = el.dataset.cid, ins = parseFloat(el.dataset.ins);
  window.axedup_decisions[mid] = !window.axedup_decisions[mid];
  var ok = window.axedup_decisions[mid];
  el.style.background = ok ? "#2a7a2a" : "#7a2a2a";
  el.style.backgroundImage = ok ? "none"
    : "repeating-linear-gradient(-45deg,transparent,transparent 3px,rgba(0,0,0,0.35) 3px,rgba(0,0,0,0.35) 4px)";
  var icon = el.querySelector("span.mark-icon");
  if (icon) icon.textContent = ok ? "✓" : "✗";
  var acc = Object.values(window.axedup_decisions).filter(Boolean).length;
  var s = document.getElementById("pick-summary");
  if (s) s.textContent = acc + " in  ·  " + (Object.keys(window.axedup_decisions).length - acc) + " out";
  var v = document.getElementById("axedup-player");
  if (!v) return;
  var url = "/proxies/" + cid + ".mp4";
  if (!v.src.endsWith(url)) {{ v.src = url; v.load(); }}
  var doSeek = function() {{ v.currentTime = ins; v.play().catch(function(){{}}); }};
  if (v.readyState >= 1) doSeek();
  else v.addEventListener("loadedmetadata", doSeek, {{once:true}});
}};
''')

                    # Right: action panel
                    with ui.column().style(_AP):
                        ui.label('Pick clips').style('color:#eee; font-weight:600; font-size:0.95rem')
                        ui.html(
                            f'<span id="pick-count" style="color:#666;font-size:0.8rem">'
                            f'{n_acc} of {len(mark_data)} selected</span>',
                            sanitize=False,
                        )
                        ui.label('Green = include\nRed/striped = skip').style('color:#444; font-size:0.75rem; white-space:pre-line')
                        ui.element('div').style('flex:1')
                        ui.button('← Back', on_click=stepper.previous).props('flat size=sm').style('color:#555')
                        ui.button('Save picks', on_click=lambda: _save_picks(False)).props('flat color=positive size=sm')
                        ui.button('Save & Continue →', on_click=lambda: _save_picks(True)).props('color=positive')

            # ── Step 4: Combine ────────────────────────────────────────────────
            with ui.step('combine', title='Combine', icon='movie_creation') as _s_combine:
                if combine_done:
                    _s_combine.props(add='done')

                comb_err_ref    = [None]
                comb_status_ref = [None]
                comb_btn_ref    = [None]

                with ui.row().style('width:100%; gap:0'):
                    with ui.column().style('flex:1; min-width:0; gap:0'):
                        # Preview player (blank placeholder until assembled)
                        preview_src = f'/previews/{session_id}_preview.mp4' if preview_path.exists() else ''
                        ui.html(
                            f'<video id="preview-player" src="{preview_src}" controls'
                            f' preload="{"auto" if preview_path.exists() else "none"}"'
                            f' style="width:100%;height:50vh;display:block;background:#000;object-fit:contain"></video>',
                            sanitize=False,
                        )
                        with ui.column().style('padding:0.75rem 1rem; gap:0.6rem'):
                            with ui.row().style('gap:1rem; flex-wrap:wrap; align-items:flex-end'):
                                grade_sel = ui.select(options=_GRADES, value='natural', label='Colour grade').style('min-width:140px')
                                source_sel = ui.select(
                                    options=['All accepted', 'Still-frame picks', 'Motion picks'],
                                    value='All accepted', label='Which picks',
                                ).style('min-width:160px')
                            comb_err    = ui.label('').style('color:#e57373; font-size:0.82rem; min-height:1rem')
                            comb_status = ui.label('').style('color:#777; font-size:0.82rem; min-height:1rem')
                            comb_err_ref[0]    = comb_err
                            comb_status_ref[0] = comb_status

                    with ui.column().style(_AP):
                        ui.label('Combine').style('color:#eee; font-weight:600; font-size:0.95rem')
                        ui.label('Choose a colour grade and build the preview.').style('color:#555; font-size:0.75rem')
                        ui.element('div').style('flex:1')
                        ui.button('← Back', on_click=stepper.previous).props('flat size=sm').style('color:#555')

                        _src_map = {'All accepted': None, 'Still-frame picks': 'jpg', 'Motion picks': 'proxy'}

                        def _start_combine() -> None:
                            btn = comb_btn_ref[0]
                            grade   = grade_sel.value
                            src_val = _src_map.get(source_sel.value)
                            btn.set_enabled(False)
                            btn.set_text('Combining…')
                            if comb_err_ref[0]:    comb_err_ref[0].set_text('')
                            if comb_status_ref[0]: comb_status_ref[0].set_text('Cutting and encoding preview…')

                            task_key   = f'assemble_{session_id}'
                            start_time = time.time()
                            state.start_task(task_key)

                            def _run() -> None:
                                try:
                                    from axedup.processing.assembly import assemble_session
                                    assemble_session(session_id, grade_override=grade, source_filter=src_val)
                                    state.finish_task(task_key)
                                except Exception as exc:
                                    state.finish_task(task_key, error=str(exc))
                            threading.Thread(target=_run, daemon=True).start()

                            def _cpoll() -> None:
                                t       = state.get_task(task_key)
                                elapsed = _fmt(time.time() - start_time)
                                if not t: return
                                if t.error:
                                    if comb_err_ref[0]:    comb_err_ref[0].set_text(t.error)
                                    btn.set_enabled(True); btn.set_text('Retry')
                                    _ct.active = False; return
                                if t.done:
                                    if comb_status_ref[0]: comb_status_ref[0].set_text(f'Done in {elapsed}.')
                                    btn.set_enabled(True); btn.set_text('Re-combine')
                                    _ct.active = False
                                    ui.navigate.to(f'/session/{session_id}')
                                else:
                                    if comb_status_ref[0]: comb_status_ref[0].set_text(f'Encoding… {elapsed} elapsed')
                            _ct = ui.timer(2.0, _cpoll)

                        comb_btn = ui.button(
                            'Re-combine' if preview_path.exists() else 'Combine clips',
                            on_click=_start_combine,
                        ).props('color=positive')
                        comb_btn_ref[0] = comb_btn

                        if preview_path.exists():
                            ui.button('Continue to Export →', on_click=stepper.next).props('flat color=positive')

            # ── Step 5: Export ─────────────────────────────────────────────────
            with ui.step('export', title='Export', icon='file_download') as _s_export:

                exp_err_ref    = [None]
                exp_status_ref = [None]
                exp_btn_ref    = [None]

                with ui.row().style('width:100%; gap:0'):
                    with ui.column().style('flex:1; min-width:0; gap:0'):
                        preview_src2 = f'/previews/{session_id}_preview.mp4' if preview_path.exists() else ''
                        ui.html(
                            f'<video src="{preview_src2}" controls'
                            f' preload="{"auto" if preview_path.exists() else "none"}"'
                            f' style="width:100%;height:50vh;display:block;background:#000;object-fit:contain"></video>',
                            sanitize=False,
                        )
                        with ui.column().style('padding:0.75rem 1rem; gap:0.5rem'):
                            ui.label('Aspect ratios').style('color:#aaa; font-size:0.82rem')
                            aspect_16 = ui.checkbox('16:9  (YouTube / landscape)', value=True)
                            aspect_9  = ui.checkbox('9:16  (Reels / portrait)',    value=False)
                            ui.label('Output folder').style('color:#aaa; font-size:0.78rem; margin-top:0.4rem')
                            with ui.row().style('align-items:center; gap:0.5rem; max-width:440px'):
                                out_input = ui.input(value=str(config.OUTPUT_DIR)).style('flex:1; color:#eee')
                                from axedup.ui.filepicker import browse_button
                                browse_button(lambda p: out_input.set_value(p), tooltip='Browse output folder')
                            exp_err    = ui.label('').style('color:#e57373; font-size:0.82rem; min-height:1rem')
                            exp_status = ui.label('').style('color:#777; font-size:0.82rem; min-height:1rem')
                            exp_err_ref[0]    = exp_err
                            exp_status_ref[0] = exp_status
                            exp_out = ui.element('div')
                            _show_exports(session_id, exp_out)

                    with ui.column().style(_AP):
                        ui.label('Export').style('color:#eee; font-weight:600; font-size:0.95rem')
                        ui.label('Encode the final file ready for sharing.').style('color:#555; font-size:0.75rem')
                        ui.element('div').style('flex:1')
                        ui.button('← Back', on_click=stepper.previous).props('flat size=sm').style('color:#555')

                        def _start_export() -> None:
                            btn = exp_btn_ref[0]
                            aspects = []
                            if aspect_16.value: aspects.append('16:9')
                            if aspect_9.value:  aspects.append('9:16')
                            if not aspects:
                                if exp_err_ref[0]: exp_err_ref[0].set_text('Select at least one aspect ratio')
                                return
                            out_dir = out_input.value.strip() or None
                            btn.set_enabled(False); btn.set_text('Exporting…')
                            if exp_err_ref[0]:    exp_err_ref[0].set_text('')
                            if exp_status_ref[0]: exp_status_ref[0].set_text('Encoding…')

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

                            def _epoll() -> None:
                                t       = state.get_task(task_key)
                                elapsed = _fmt(time.time() - start_time)
                                if not t: return
                                if t.error:
                                    if exp_err_ref[0]: exp_err_ref[0].set_text(t.error)
                                    btn.set_enabled(True); btn.set_text('Export')
                                    _et.active = False; return
                                if t.done:
                                    if exp_status_ref[0]: exp_status_ref[0].set_text(f'Done in {elapsed}.')
                                    btn.set_enabled(True); btn.set_text('Export again')
                                    _et.active = False
                                    _show_exports(session_id, exp_out)
                                else:
                                    if exp_status_ref[0]: exp_status_ref[0].set_text(f'Encoding… {elapsed} elapsed')
                            _et = ui.timer(2.0, _epoll)

                        exp_btn = ui.button('Export', on_click=_start_export).props('color=positive')
                        exp_btn_ref[0] = exp_btn

    # ── Analysis poll timer ────────────────────────────────────────────────────
    if analyzing:
        _poll_start = time.time()
        _est_str    = _fmt(max(60, int(total_s * 1.0)))

        def _poll() -> None:
            cur_task = state.get_task(session_id)
            prog     = state.get_clip_progress(session_id)

            if timing_lbl is not None:
                timing_lbl.set_text(f'Est. ~{_est_str}  ·  Elapsed: {_fmt(time.time() - _poll_start)}')

            for cid, stage_els in tl_els.items():
                for stage, el in stage_els.items():
                    el.set_content(_tl_html(prog.get(cid, {}).get(stage, StageState())))

            if cur_task and cur_task.error:
                ui.notify(f'Analysis error: {cur_task.error}', type='negative', timeout=0)
                _timer.active = False
                return

            if cur_task and cur_task.done:
                # Mark Analyze step done and unlock Continue button
                sa = step_analyze_ref[0]
                if sa:
                    sa.props(add='done')
                cb = continue_btn_ref[0]
                if cb:
                    cb.props(remove='disable')
                _timer.active = False

        _timer = ui.timer(0.5, _poll)
