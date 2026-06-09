"""
Session view — 3-pane layout.
Routes: /session/{session_id}  (existing session)
        /session/new           (new session — file picker in Input step)

  ┌──────────────────────────┬─────────────────────┐  60 % viewport height
  │  Video player  (60 %w)   │  Step list  (40 %w) │
  │  + timeline strip        │  dot · title ·      │
  │    when Pick selected    │  est→actual · count │
  ├──────────────────────────┴─────────────────────┤  40 % viewport height
  │  Detail pane — progress bars / controls        │
  │                               [Next action →]  │
  └────────────────────────────────────────────────┘

Steps: Input → Proxy → Detect → Pick → Combine → Export
"""
import inspect
import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from nicegui import ui

from axedup import config
from axedup.models.db import get_session as db_session
from axedup.models.schema import (
    Clip, Export, Mark, MarkStatus, Profile, Session, SessionStatus, TelemetryPoint,
)
from axedup.ui import state
from axedup.ui.state import StageState
from axedup.ui.layout import sidebar

# ── Constants ──────────────────────────────────────────────────────────────────

_STEPS = [
    ('input',      'Input videos',           'Select source video files'),
    ('proxy',      'Creating working copy',  'Create lofi copy for processing'),
    ('method',     'Look for scenes by…',    'Choose how frames are sampled for analysis'),
    ('scan',       'Detecting scenes…',      'Detect scenes using Optical flow algorithm'),
    ('highlights', 'Finding clips…',         'Automatic — clips identified from detected scenes'),
    ('pick',       'Select clips',           'Review and select clips to include'),
    ('combine',    'Combining clips…',       'Combining selected clips into output video'),
    ('export',     'Exporting video…',       'Create final video for sharing'),
]

_PROXY_STAGES = ['proxy']
_SCAN_STAGES  = ['scenes', 'motion']

_STAGE_LABEL = {
    'proxy':  'Working copy',
    'scenes': 'Scene cuts',
    'motion': 'Optical flow',
}
_STAGE_BYLINE = {
    'proxy':  '480p transcode — originals are only read once, here',
    'scenes': 'Finds camera cuts and hard transitions',
    'motion': 'Quick: ffmpeg extracts 1 frame/s, optical flow on those frames  ·  Full: OpenCV decodes every frame, sampled every 0.5s',
}

_GRADES   = ['punchy', 'cinematic', 'natural', 'warm', 'cool', 'vibrant']
_SPORT_FB = ['mtb', 'surf', 'ski', 'cycling', 'moto', 'trail', 'skydive']

_HDR_H = 46
_TOP_H = f'calc((100vh - {_HDR_H}px) * 0.60)'
_BOT_H = f'calc((100vh - {_HDR_H}px) * 0.40)'
_TL_H  = f'calc({_TOP_H} * 0.20)'

_ROW_BASE = (
    'padding:0.55rem 0.75rem;align-items:flex-start;gap:0.5rem;'
    'border-bottom:1px solid #141414;cursor:pointer;'
    'flex-shrink:0;flex-wrap:nowrap;border-left:3px solid transparent'
)

# Method choices for new sessions (set before navigate, read on page load)
_pending_methods: dict[str, str] = {}


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _fmt(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f'{m}m{s:02d}s' if m else f'{s}s'


def _tsfmt(ts: float) -> str:
    m, s = divmod(int(ts), 60)
    return f'{m}:{s:02d}'


def _dot_html(st: str) -> str:
    if st == 'done':
        c, cls = '#5a9a5a', ''
    elif st == 'running':
        c, cls = '#f0a040', 'class="tl-run"'
    elif st == 'active':
        c, cls = '#5a8aaa', ''
    else:
        return ('<span style="width:11px;height:11px;border-radius:50%;'
                'background:#1e1e1e;border:1px solid #2e2e2e;display:inline-block;flex-shrink:0"></span>')
    return (f'<span {cls} style="width:11px;height:11px;border-radius:50%;'
            f'background:{c};display:inline-block;flex-shrink:0"></span>')


def _row_style(selected: bool) -> str:
    bg  = '#1c1c1c' if selected else '#111'
    bdr = '#5a9a5a' if selected else 'transparent'
    return f'{_ROW_BASE};background:{bg};border-left-color:{bdr}'


def _bar_html(s: StageState, label: str, stage: str, method: str = 'proxy') -> str:
    """One progress-bar row: [label 148px] [bar flex] [pct 24px]"""

    if s.status in ('done', 'skipped'):
        return (
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:9px">'
            f'<span style="color:#5a9a5a;font-size:0.78rem;flex-shrink:0;width:148px">{label}</span>'
            f'<div style="flex:1;height:7px;border-radius:4px;background:#1a3a1a;overflow:hidden">'
            f'<div style="height:100%;width:100%;background:#5a9a5a;border-radius:4px"></div></div>'
            f'<span style="color:#3a7a3a;font-size:0.7rem;width:24px;text-align:right">✓</span>'
            f'</div>'
        )

    if s.status == 'running':
        pct = (s.pct if s.pct is not None
               else (int(s.completed / s.total * 100) if s.completed and s.total else 0))
        sub = ''
        if stage == 'motion' and s.completed and s.total:
            phase = s.message or 'Comparing'   # "Extracting" during ffmpeg phase, "Comparing" during flow
            mode  = '1fps sample' if method == 'jpg' else 'all frames'
            sub   = f'{phase} · {mode} · {s.completed:,}/{s.total:,} frames'
        elif stage == 'proxy' and s.pct is not None:
            sub = f'Transcoding {s.pct}% complete'
        return (
            f'<div style="margin-bottom:9px">'
            f'<div style="display:flex;align-items:center;gap:10px">'
            f'<span style="color:#f0a040;font-size:0.78rem;flex-shrink:0;width:148px">{label}</span>'
            f'<div style="flex:1;height:7px;border-radius:4px;background:#1a1a1a;overflow:hidden">'
            f'<div style="height:100%;width:{pct}%;background:#f0a040;'
            f'border-radius:4px;transition:width 0.3s ease"></div></div>'
            f'<span style="color:#a07030;font-size:0.7rem;width:24px;text-align:right">{pct}%</span>'
            f'</div>'
            + (f'<div style="padding-left:158px;margin-top:2px">'
               f'<span style="color:#8a7a5a;font-size:0.68rem">{sub}</span></div>' if sub else '')
            + f'</div>'
        )

    return (
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:9px">'
        f'<span style="color:#484848;font-size:0.78rem;flex-shrink:0;width:148px">{label}</span>'
        f'<div style="flex:1;height:7px;border-radius:4px;background:#161616;overflow:hidden">'
        f'<div style="height:100%;width:0%;background:#1e1e1e;border-radius:4px"></div></div>'
        f'<span style="color:#3e3e3e;font-size:0.7rem;width:24px;text-align:right">—</span>'
        f'</div>'
    )


def _timeline_html(mark_data: list, clip_info: list) -> str:
    marks_by_clip: dict = {}
    for mid, cid, in_s, out_s, *_ in mark_data:
        marks_by_clip.setdefault(cid, []).append((mid, in_s, out_s))

    total_dur = sum(d for _, _, d in clip_info if d)
    if   total_dur <= 60:   tick_iv = 10
    elif total_dur <= 300:  tick_iv = 30
    elif total_dur <= 1800: tick_iv = 60
    else:                   tick_iv = 300

    _BG = ['#1a1a1a', '#171717', '#1c1c1c', '#181818']
    out = [
        '<div style="display:flex;width:100%;height:100%;gap:2px;background:#0a0a0a;'
        'padding:4px 8px;box-sizing:border-box;align-items:stretch;'
        'border:1px solid #2a2a2a;border-radius:3px;overflow:hidden">'
    ]
    clip_start = 0.0
    for i, (cid, fname, dur_s) in enumerate(clip_info):
        if not dur_s: continue
        label = (fname[:10] + '…') if len(fname) > 10 else fname
        out.append(
            f'<div style="flex:{max(dur_s,1.0):.1f};min-width:30px;position:relative;'
            f'border-radius:2px;overflow:hidden;background:{_BG[i%4]}">'
            f'<div style="position:absolute;top:0;left:0;right:0;height:13px;'
            f'background:rgba(0,0,0,0.6);display:flex;align-items:center;padding:0 3px;z-index:1">'
            f'<span style="font-size:0.47rem;color:#999;white-space:nowrap;overflow:hidden;'
            f'text-overflow:ellipsis">{label} · {_fmt(int(dur_s))}</span></div>'
        )
        # Timestamp ticks — align to global time grid so ticks line up across clips
        first_offset = tick_iv - (clip_start % tick_iv)
        if first_offset >= tick_iv: first_offset = 0.0
        t = first_offset if first_offset > 0 else tick_iv
        while t < dur_s:
            tp = t / dur_s * 100
            tick_label = _tsfmt(int(clip_start + t))
            out.append(
                f'<div style="position:absolute;top:14px;left:{tp:.2f}%;width:1px;bottom:0;'
                f'background:rgba(255,255,255,0.07);pointer-events:none">'
                f'<span style="position:absolute;bottom:2px;left:2px;font-size:0.38rem;'
                f'color:rgba(255,255,255,0.28);white-space:nowrap;pointer-events:none">'
                f'{tick_label}</span></div>'
            )
            t += tick_iv
        # Mark bars
        for mid, in_s, out_s in marks_by_clip.get(cid, []):
            ip = in_s / dur_s * 100
            wp = (out_s - in_s) / dur_s * 100
            tip = f'{_tsfmt(in_s)}–{_tsfmt(out_s)} ({out_s-in_s:.1f}s)'
            out.append(
                f'<div id="mark-{mid}" data-mid="{mid}" data-cid="{cid}" data-ins="{in_s}"'
                f' style="position:absolute;top:15px;left:{ip:.2f}%;'
                f'width:max({max(wp, 2):.2f}%,40px);bottom:2px;background:#2a7a2a;'
                f'border-radius:2px;cursor:pointer;transition:background 0.15s;'
                f'display:flex;align-items:center;justify-content:center;overflow:hidden"'
                f' onclick="axedupMarkClick(this)" title="{tip}">'
                f'<span class="mark-icon" style="font-size:0.45rem;color:rgba(255,255,255,0.85);'
                f'pointer-events:none;line-height:1">✓</span></div>'
            )
        out.append('</div>')
        clip_start += dur_s
    out.append('</div>')
    return ''.join(out)


def _show_exports(session_id: str, container) -> None:
    container.clear()
    with container:
        with db_session() as db:
            exports = (db.query(Export).filter(Export.session_id == session_id)
                       .order_by(Export.exported_at.desc()).all())
        if not exports: return
        ui.label('Output files').style('color:#aaa;font-size:0.8rem;margin-bottom:0.3rem')
        for exp in exports:
            with ui.card().style('background:#1a1a1a;padding:0.4rem 0.6rem;margin-bottom:0.25rem'):
                with ui.row().style('align-items:center;gap:0.75rem'):
                    ui.badge(exp.aspect).style('background:#1a2a1a;color:#5a9a5a;font-size:0.7rem')
                    ui.label(exp.filepath).style(
                        'color:#888;font-size:0.75rem;font-family:monospace;flex:1;word-break:break-all'
                    )


# ── Delete helper ──────────────────────────────────────────────────────────────

def _delete_session_button(session_id: str) -> None:
    dlg = ui.dialog()
    with dlg, ui.card().style('background:#1e1e1e;padding:1.25rem;min-width:300px'):
        ui.label('Delete this session?').style('color:#eee;font-weight:600;margin-bottom:0.4rem')
        ui.label('Removes all DB records and cached files.').style(
            'color:#777;font-size:0.78rem;margin-bottom:1rem'
        )
        with ui.row().style('gap:0.5rem;justify-content:flex-end'):
            ui.button('Cancel', on_click=dlg.close).props('flat')
            ui.button('Delete', on_click=lambda: (_do_delete(session_id), dlg.close())).props('color=negative')
    ui.button(icon='delete_outline', on_click=dlg.open).props('flat round dense').style('color:#5a3030').tooltip('Delete')


def _do_delete(session_id: str) -> None:
    with db_session() as db:
        clips    = db.query(Clip).filter(Clip.session_id == session_id).all()
        clip_ids = [c.id for c in clips]
        mark_ids = [m.id for c in clips for m in db.query(Mark).filter(Mark.clip_id == c.id).all()]
        s = db.query(Session).filter(Session.id == session_id).first()
        if s: db.delete(s)
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
        '.q-btn.disabled,.q-btn[disabled]{opacity:0.35!important;cursor:not-allowed!important}'
        '</style>'
    )

    if session_id == 'new':
        _new_session_ui()
        return

    # ── DB load ────────────────────────────────────────────────────────────────
    with db_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            ui.label('Session not found.').style('color:#e57373;padding:2rem')
            return
        status   = session.status
        sport    = session.sport or 'unknown'
        src      = session.source_path or ''
        created  = session.created_at
        clips    = db.query(Clip).filter(Clip.session_id == session_id).order_by(Clip.clip_order).all()
        clip_ids = [c.id for c in clips]
        clip_info = [(c.id, c.filename, c.duration_s) for c in clips]
        total_s  = sum(c.duration_s or 0 for c in clips)
        marks_all = (
            db.query(Mark)
            .join(Clip, Mark.clip_id == Clip.id)
            .filter(Mark.clip_id.in_(clip_ids))
            .filter(Mark.status.in_([MarkStatus.CANDIDATE, MarkStatus.ACCEPTED, MarkStatus.REJECTED]))
            .order_by(Clip.clip_order, Mark.in_s)
            .all()
        ) if clip_ids else []
        mark_data    = [(m.id, m.clip_id, m.in_s, m.out_s, m.score or 0.0, m.source) for m in marks_all]
        rejected_ids = {m.id for m in marks_all if m.status == MarkStatus.REJECTED}
        sports = [p.sport for p in db.query(Profile).order_by(Profile.sport).all()] or _SPORT_FB

    # ── Task / progress state ──────────────────────────────────────────────────
    proxy_task      = state.get_task(f'{session_id}_proxy')
    scan_task       = state.get_task(f'{session_id}_scan')
    highlights_task = state.get_task(f'{session_id}_highlights')
    legacy_task     = state.get_task(session_id)

    all_proxies_done = bool(clip_ids) and all(
        (config.PROXY_DIR / f'{cid}.mp4').exists() for cid in clip_ids
    )
    proxy_running = (
        (proxy_task is not None and not proxy_task.done) or
        (legacy_task is not None and not legacy_task.done and not all_proxies_done)
    )
    with db_session() as db:
        has_motion_data = bool(clip_ids) and (
            db.query(TelemetryPoint)
            .filter(TelemetryPoint.clip_id.in_(clip_ids))
            .filter(
                (TelemetryPoint.motion_intensity.isnot(None)) |
                (TelemetryPoint.motion_intensity_quick.isnot(None))
            ).count() > 0
        )
    scan_running       = scan_task is not None and not scan_task.done
    highlights_running = highlights_task is not None and not highlights_task.done
    post_analysis = status not in (
        SessionStatus.IMPORTING, SessionStatus.INGESTED, SessionStatus.ANALYZING
    )

    preview_path = config.PREVIEW_DIR / f'{session_id}_preview.mp4'
    still_path   = config.STILL_DIR / f'{session_id}_still.jpg'
    detect_method_ref = [_pending_methods.get(session_id, 'proxy')]

    # ── Step status helper ─────────────────────────────────────────────────────
    def _step_st(sid: str) -> str:
        if sid == 'input':
            return 'done' if clip_ids else 'active'
        if sid == 'proxy':
            if all_proxies_done:  return 'done'
            if proxy_running:     return 'running'
            return 'active' if clip_ids else 'pending'
        if sid == 'method':
            if has_motion_data or scan_running or highlights_running or post_analysis:
                return 'done'
            return 'active' if all_proxies_done else 'pending'
        if sid == 'scan':
            if has_motion_data:   return 'done'
            if scan_running:      return 'running'
            return 'active' if all_proxies_done else 'pending'
        if sid == 'highlights':
            if post_analysis:        return 'done'
            if highlights_running:   return 'running'
            return 'active' if has_motion_data else 'pending'
        if sid == 'pick':
            if status in (SessionStatus.ASSEMBLED, SessionStatus.EXPORTED): return 'done'
            return 'active' if post_analysis else 'pending'
        if sid == 'combine':
            if status in (SessionStatus.ASSEMBLED, SessionStatus.EXPORTED): return 'done'
            if preview_path.exists(): return 'done'
            return 'pending'
        if sid == 'export':
            if status == SessionStatus.EXPORTED: return 'done'
            return 'active' if preview_path.exists() else 'pending'
        return 'pending'

    # ── Initial step ───────────────────────────────────────────────────────────
    if not clip_ids:
        initial = 'input'
    elif proxy_running or not all_proxies_done:
        initial = 'proxy'
    elif scan_running:
        initial = 'scan'
    elif highlights_running:
        initial = 'highlights'
    elif post_analysis:
        if status == SessionStatus.ASSEMBLED:
            initial = 'combine'
        elif status == SessionStatus.EXPORTED:
            initial = 'export'
        else:
            initial = 'pick'
    elif has_motion_data:
        initial = 'highlights'
    else:
        initial = 'method'

    def _player_src() -> str:
        if preview_path.exists():
            return f'/previews/{session_id}_preview.mp4'
        p = next((cid for cid in clip_ids if (config.PROXY_DIR / f'{cid}.mp4').exists()), None)
        return f'/proxies/{p}.mp4' if p else ''

    init_src = _player_src()

    # ── Mutable refs ──────────────────────────────────────────────────────────
    selected        = [initial]
    detail_ref      = [None]
    tl_col_ref      = [None]
    tl_html_ref     = [None]
    next_btn_ref    = [None]
    next_action     = {'fn': None}
    hdr_time_ref    = [None]
    hdr_elapsed_ref = [None]
    dot_refs:   dict[str, ui.html]  = {}
    time_refs:  dict[str, ui.label] = {}
    count_refs: dict[str, ui.label] = {}
    row_refs:   dict[str, ui.row]   = {}
    bar_refs:   dict[str, dict[str, ui.html]] = {}
    task_start    = [time.time()]
    _scan_started = [False]
    _timer_ref    = [None]

    # ── Sidebar ────────────────────────────────────────────────────────────────
    _mini = [False]
    drawer = ui.left_drawer(value=True).style('background:#1a1a1a;border-right:1px solid #222')
    drawer.props('breakpoint=0 width=180 mini-width=48')
    with drawer:
        sidebar('session', session_id, status)

    def _toggle_nav() -> None:
        _mini[0] = not _mini[0]
        if _mini[0]: drawer.props(add='mini')
        else:        drawer.props(remove='mini')

    # ── Page shell ─────────────────────────────────────────────────────────────
    with ui.column().style('width:100%;height:100vh;background:#111;padding:0;gap:0;overflow:hidden'):

        # ── Header ────────────────────────────────────────────────────────────
        with ui.row().style(
            f'height:{_HDR_H}px;flex-shrink:0;width:100%;align-items:center;'
            'justify-content:space-between;padding:0 1rem;background:#141414;'
            'border-bottom:1px solid #1a1a1a'
        ):
            with ui.row().style('align-items:center;gap:0.5rem'):
                ui.button(icon='menu', on_click=_toggle_nav).props('flat round dense').style('color:#888')
                with ui.column().style('gap:0.1rem'):
                    ds = created.strftime('%Y-%m-%d %H:%M') if created else ''
                    _est_total_s = max(60, int(total_s)) + max(30, int(total_s // 3)) + 60 + 120
                    with ui.row().style('gap:0.75rem;align-items:baseline'):
                        ui.label(f'{sport}  ·  {ds}  ·  est ~{_fmt(_est_total_s)}').style('color:#eee;font-size:0.88rem;font-weight:600')
                        _he = ui.label('elapsed 0s').style('color:#5a8a9a;font-size:0.78rem')
                        hdr_elapsed_ref[0] = _he
                    with ui.row().style('gap:0.6rem;align-items:baseline'):
                        m0, s0 = divmod(int(total_s), 60)
                        ui.label(
                            f'{len(clip_ids)} clip{"s" if len(clip_ids)!=1 else ""}  ·  {m0}m{s0:02d}s'
                        ).style('color:#666;font-size:0.7rem')
                        _ht = ui.label('').style('color:#4a9a4a;font-size:0.7rem')
                        hdr_time_ref[0] = _ht
            _delete_session_button(session_id)

        # ── Top row ───────────────────────────────────────────────────────────
        with ui.row().style(f'width:100%;height:{_TOP_H};gap:0;flex-shrink:0;overflow:hidden'):

            # Video column 60 %
            with ui.column().style('width:60%;height:100%;gap:0;overflow:hidden;background:#000;flex-shrink:0'):
                with ui.element('div').style('flex:1;min-height:0;position:relative;overflow:hidden;background:#000'):
                    if init_src:
                        ui.html(
                            f'<video id="main-player" src="{init_src}" controls preload="metadata"'
                            f' style="width:100%;height:100%;object-fit:contain;display:block;background:#000"></video>',
                            sanitize=False,
                        )
                    elif still_path.exists():
                        ui.html(
                            f'<img id="player-still" src="/stills/{session_id}_still.jpg"'
                            f' style="width:100%;height:100%;object-fit:contain;display:block;background:#000">'
                            '<video id="main-player" src="" controls preload="none"'
                            ' style="width:100%;height:100%;object-fit:contain;display:none;background:#000"></video>',
                            sanitize=False,
                        )
                    else:
                        ui.html(
                            '<div id="player-ph" style="width:100%;height:100%;display:flex;flex-direction:column;'
                            'align-items:center;justify-content:center;gap:0.5rem;background:#000">'
                            '<span style="color:#3e3e3e;font-size:2.5rem">▷</span>'
                            '<span style="color:#484848;font-size:0.82rem">No footage loaded yet</span>'
                            '<span style="color:#5a5a5a;font-size:0.72rem">→ select Input in the step list</span></div>'
                            '<video id="main-player" src="" controls preload="none"'
                            ' style="width:100%;height:100%;object-fit:contain;display:none;background:#000"></video>',
                            sanitize=False,
                        )
                # Timeline strip (20 % of column height)
                with ui.column().style(
                    f'height:{_TL_H};min-height:50px;flex-shrink:0;'
                    'width:100%;overflow:hidden;background:#0a0a0a;border-top:1px solid #0d0d0d'
                ) as _tl_col:
                    _tl_el = ui.html('', sanitize=False).style('width:100%;height:100%;display:block')
                    tl_html_ref[0] = _tl_el
                _tl_col.set_visibility(False)
                tl_col_ref[0] = _tl_col

            # Step list column 40 %
            with ui.column().style(
                'width:40%;height:100%;gap:0;flex-shrink:0;'
                'border-left:1px solid #1a1a1a;overflow-y:auto;background:#111'
            ):
                with ui.row().style(
                    'padding:0.3rem 0.75rem;background:#0d0d0d;border-bottom:1px solid #1a1a1a;'
                    'align-items:center;flex-shrink:0'
                ):
                    ui.label('Step').style('color:#3e3e3e;font-size:0.67rem;text-transform:uppercase;letter-spacing:0.07em;flex:1')
                    ui.label('Time').style('color:#3e3e3e;font-size:0.67rem;text-transform:uppercase;letter-spacing:0.07em;width:84px;text-align:right')
                    ui.label('Found').style('color:#3e3e3e;font-size:0.67rem;text-transform:uppercase;letter-spacing:0.07em;width:52px;text-align:right')

                for step_id, title, subtitle in _STEPS:
                    st  = _step_st(step_id)
                    est = (f'~{_fmt(max(60, int(total_s)))}' if step_id == 'proxy'
                           else f'~{_fmt(max(30, int(total_s // 3)))}' if step_id == 'scan'
                           else '~1m' if step_id == 'combine'
                           else '~2m' if step_id == 'export' else '')
                    count = (
                        str(len(clip_ids)) if step_id == 'input' and clip_ids
                        else str(len(mark_data)) if step_id in ('highlights', 'pick') and mark_data
                        else ''
                    )
                    with ui.row().style(_row_style(step_id == initial)).on(
                        'click', lambda s=step_id: _select_step(s)
                    ) as _row:
                        row_refs[step_id] = _row
                        _dot = ui.html(_dot_html(st), sanitize=False, tag='span').style('margin-top:3px;flex-shrink:0')
                        dot_refs[step_id] = _dot
                        with ui.column().style('gap:0.06rem;flex:1;min-width:0'):
                            _tc = '#eee' if step_id == initial else '#888'
                            _tw = '600' if step_id == initial else '400'
                            ui.label(title).style(f'font-size:0.83rem;font-weight:{_tw};color:{_tc};white-space:nowrap')
                            ui.label(subtitle).style('color:#888;font-size:0.7rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')
                        _tl = ui.label(est).style('color:#5a5a5a;font-size:0.72rem;width:84px;text-align:right;flex-shrink:0')
                        time_refs[step_id] = _tl
                        _cl = ui.label(count).style('color:#5a5a5a;font-size:0.72rem;width:52px;text-align:right;flex-shrink:0')
                        count_refs[step_id] = _cl

        # ── Bottom row ─────────────────────────────────────────────────────────
        with ui.column().style(f'width:100%;height:{_BOT_H};gap:0;border-top:1px solid #1a1a1a;overflow:hidden'):
            ui.label('Video may take a moment to load.').style(
                'color:#3a3a3a;font-size:0.68rem;text-align:center;padding:0.15rem 0;'
                'flex-shrink:0;background:#111;border-bottom:1px solid #181818'
            )
            with ui.column().style('flex:1;min-height:0;overflow-y:auto;padding:0.75rem 1.25rem;gap:0') as _detail:
                pass
            detail_ref[0] = _detail

            with ui.row().style(
                'height:40px;flex-shrink:0;border-top:1px solid #1a1a1a;background:#141414;'
                'padding:0 1rem;align-items:center;gap:0.75rem;justify-content:flex-end'
            ):
                ui.label('').style('color:#666;font-size:0.78rem;flex:1')

                async def _handle_next_click() -> None:
                    fn = next_action['fn']
                    if not fn: return
                    if inspect.iscoroutinefunction(fn):
                        await fn()
                    else:
                        fn()

                _nbtn = ui.button('…', on_click=_handle_next_click).props('color=positive size=sm')
                _nbtn.set_enabled(False)
                next_btn_ref[0] = _nbtn

    # ── Helper: set next button ────────────────────────────────────────────────
    def _set_next_btn(label: str, enabled: bool, fn) -> None:
        b = next_btn_ref[0]
        if not b: return
        b.set_text(label)
        b.set_enabled(enabled)
        b.props(f'color={"positive" if enabled else "grey-7"}')
        next_action['fn'] = fn

    # ── Step selection ─────────────────────────────────────────────────────────
    def _select_step(step_id: str) -> None:
        selected[0] = step_id
        for sid, row_el in row_refs.items():
            row_el.style(_row_style(sid == step_id))
        tl = tl_col_ref[0]
        if tl is not None:
            show = step_id == 'pick' and bool(mark_data)
            tl.set_visibility(show)
            if show and tl_html_ref[0]:
                tl_html_ref[0].set_content(_timeline_html(mark_data, clip_info))
        bar_refs.clear()
        d = detail_ref[0]
        if d is None: return
        d.clear()
        with d:
            if   step_id == 'input':      _detail_input()
            elif step_id == 'proxy':      _detail_proxy()
            elif step_id == 'method':     _detail_method()
            elif step_id == 'scan':       _detail_scan()
            elif step_id == 'highlights': _detail_highlights()
            elif step_id == 'pick':       _detail_pick()
            elif step_id == 'combine':    _detail_combine()
            elif step_id == 'export':     _detail_export()
        _refresh_next_btn()

    def _refresh_next_btn() -> None:
        step = selected[0]
        if step == 'input':
            if clip_ids: _set_next_btn('See working copy →', True, lambda: _select_step('proxy'))
            else:        _set_next_btn('(choose footage above)', False, None)
        elif step == 'proxy':
            if all_proxies_done:
                _set_next_btn('Look for scenes by… →', True, lambda: _select_step('method'))
            else:
                _set_next_btn('Look for scenes by… →', False, None)
        elif step == 'method':
            if _scan_started[0] or scan_running:
                _set_next_btn('Detecting scenes →', False, None)
            else:
                _set_next_btn('Start scan →', all_proxies_done, _start_scan)
        elif step == 'scan':
            if has_motion_data:
                _set_next_btn('Find clips →', True, lambda: _select_step('highlights'))
            elif scan_running or _scan_started[0]:
                _set_next_btn('Finding clips →', False, None)
            else:
                _set_next_btn('Start scan →', all_proxies_done, _start_scan)
        elif step == 'highlights':
            if post_analysis:
                _set_next_btn('Select clips →', True, lambda: _select_step('pick'))
            else:
                _set_next_btn('Select clips →', False, None)
        elif step == 'pick':
            _set_next_btn('Save & combine clips →', bool(mark_data), _save_and_combine)
        elif step == 'combine':
            _assemble_task = state.get_task(f'assemble_{session_id}')
            if _assemble_task and not _assemble_task.done:
                _set_next_btn('Continue to export →', False, None)
            elif preview_path.exists():
                _set_next_btn('Continue to export →', True, lambda: _select_step('export'))
            else:
                _set_next_btn('Combine clips →', True, _run_combine)
        elif step == 'export':
            _export_task = state.get_task(f'export_{session_id}')
            if _export_task and not _export_task.done:
                _set_next_btn('Exporting…', False, None)
            else:
                _set_next_btn('Export →', True, _do_export_trigger)

    # ── Detail renderers ───────────────────────────────────────────────────────

    def _detail_input() -> None:
        ui.label('Source footage').style('color:#666;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:0.3rem')
        ui.label(src or '(none)').style('color:#888;font-size:0.8rem;font-family:monospace;word-break:break-all;margin-bottom:0.6rem')
        ui.label(f'Sport: {sport}').style('color:#666;font-size:0.8rem;margin-bottom:0.5rem')
        if clip_info:
            ui.label('Clips').style('color:#666;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:0.3rem')
            for cid, fname, dur_s in clip_info:
                with ui.row().style('align-items:center;gap:0.75rem;margin-bottom:0.2rem'):
                    ui.label(fname).style('color:#777;font-size:0.8rem;font-family:monospace;flex:1')
                    ui.label(_fmt(int(dur_s or 0))).style('color:#5a5a5a;font-size:0.78rem')
        else:
            ui.label('No clips — use Start editing from the home page to load footage.').style('color:#888;font-size:0.82rem')

    def _detail_proxy() -> None:
        prog = state.get_clip_progress(session_id)
        if all_proxies_done:
            with ui.row().style('align-items:center;gap:0.5rem;margin-bottom:0.75rem'):
                ui.icon('check_circle').style('color:#5a9a5a;font-size:1rem')
                ui.label('Working copy ready — choose how to look for scenes').style('color:#5a9a5a;font-size:0.82rem')
        else:
            ui.label('Building working copy…').style('color:#f0a040;font-size:0.82rem;margin-bottom:0.5rem')
        first_clip = True
        for cid, fname, _ in clip_info:
            ui.label(fname).style('color:#666;font-size:0.75rem;font-family:monospace;margin-top:0.5rem;margin-bottom:0.25rem')
            cp = prog.get(cid, {})
            bar_refs[cid] = {}
            for stage in _PROXY_STAGES:
                s  = cp.get(stage, StageState())
                el = ui.html(_bar_html(s, _STAGE_LABEL[stage], stage), sanitize=False)
                bar_refs[cid][stage] = el
                if first_clip:
                    ui.label(_STAGE_BYLINE[stage]).style('color:#484848;font-size:0.68rem;margin-bottom:4px;padding-left:2px')
            first_clip = False

    def _detail_method() -> None:
        if not all_proxies_done:
            ui.label('Finish building the working copy first.').style('color:#666;font-size:0.82rem')
            return
        if has_motion_data or post_analysis:
            with ui.row().style('align-items:center;gap:0.5rem;margin-bottom:0.5rem'):
                ui.icon('check_circle').style('color:#5a9a5a;font-size:1rem')
                ui.label('How to look for scenes set — scenes already detected.').style('color:#5a9a5a;font-size:0.82rem')
            return
        ui.label('Both methods use optical flow — the difference is how frames are sampled.').style('color:#aaa;font-size:0.82rem;margin-bottom:0.4rem')
        method_radio = ui.radio(
            options={
                'jpg':   'Quick — 1fps sample  (~15× faster, good for most footage)',
                'proxy': 'Full — all frames  (slower, more accurate for low-contrast clips)',
            },
            value=detect_method_ref[0],
        ).props('dense').style('color:#ccc;margin-bottom:0.4rem')
        method_radio.on_value_change(lambda e: detect_method_ref.__setitem__(0, e.value))
        ui.label('Quick: ffmpeg extracts 1 frame/s, then optical flow compares those frames.  Full: OpenCV decodes every frame and samples every 0.5s.').style(
            'color:#888;font-size:0.73rem'
        )

    def _detail_scan() -> None:
        prog = state.get_clip_progress(session_id)
        if not all_proxies_done:
            ui.label('Finish building the working copy first, then choose how to look for scenes.').style('color:#666;font-size:0.82rem')
            return
        if has_motion_data:
            with ui.row().style('align-items:center;gap:0.5rem;margin-bottom:0.75rem'):
                ui.icon('check_circle').style('color:#5a9a5a;font-size:1rem')
                ui.label('Scenes detected — see Finding clips… for results.').style('color:#5a9a5a;font-size:0.82rem')
        elif scan_running or _scan_started[0]:
            ui.html('<span class="tl-run" style="color:#f0a040;font-size:0.82rem">Detecting scenes…</span>',
                    sanitize=False).style('margin-bottom:0.5rem;display:block')
        else:
            ui.label('Click Start scan → below to begin detecting scenes.').style('color:#666;font-size:0.82rem;margin-bottom:0.5rem')
        # Show bars for all clips as soon as scan is started (pending state until events arrive)
        if not has_motion_data and not scan_running and not _scan_started[0]:
            return
        first_clip = True
        for cid, fname, _ in clip_info:
            cp = prog.get(cid, {})
            ui.label(fname).style('color:#666;font-size:0.75rem;font-family:monospace;margin-top:0.5rem;margin-bottom:0.25rem')
            bar_refs.setdefault(cid, {})
            for stage in _SCAN_STAGES:
                s  = cp.get(stage, StageState())
                el = ui.html(_bar_html(s, _STAGE_LABEL[stage], stage, detect_method_ref[0]), sanitize=False)
                bar_refs[cid][stage] = el
                if first_clip:
                    ui.label(_STAGE_BYLINE[stage]).style('color:#484848;font-size:0.68rem;margin-bottom:4px;padding-left:2px')
            first_clip = False

    def _detail_highlights() -> None:
        ui.label('This step is automatic — no action required.').style('color:#888;font-size:0.78rem;margin-bottom:0.4rem')
        if not has_motion_data:
            ui.label('Waiting for Detecting scenes… to complete first.').style('color:#666;font-size:0.82rem')
            return
        if post_analysis:
            n = len(mark_data)
            with ui.row().style('align-items:center;gap:0.5rem;margin-bottom:0.5rem'):
                ui.icon('check_circle').style('color:#5a9a5a;font-size:1rem')
                ui.label(f'{n} clip{"s" if n!=1 else ""} found — see Select clips to review').style('color:#5a9a5a;font-size:0.82rem')
        elif highlights_running:
            ui.html('<span class="tl-run" style="color:#f0a040;font-size:0.82rem">Finding clips…</span>',
                    sanitize=False).style('display:block;margin-bottom:0.25rem')
            ui.label('Peak detection is fast — usually done in seconds.').style('color:#666;font-size:0.75rem')
        else:
            ui.label('Clip detection runs automatically after scenes are detected.').style('color:#666;font-size:0.82rem')

    _combine_grade_val  = ['natural']
    _combine_source_val = ['All accepted']
    _combine_err_ref    = [None]
    _combine_status_ref = [None]
    _combine_bar_ref    = [None]
    _combine_done_ref   = [False]
    _c_done_ref         = [0]
    _c_total_ref        = [0]

    def _combine_bar_content(done: int, total: int, finished: bool = False) -> str:
        if finished:
            return (
                '<div style="display:flex;align-items:center;gap:10px;margin-bottom:9px">'
                '<span style="color:#5a9a5a;font-size:0.78rem;flex-shrink:0;width:148px">Combining</span>'
                '<div style="flex:1;height:7px;border-radius:4px;background:#1a3a1a">'
                '<div style="height:100%;width:100%;background:#5a9a5a;border-radius:4px"></div></div>'
                '<span style="color:#3a7a3a;font-size:0.7rem;width:24px;text-align:right">✓</span>'
                '</div>'
            )
        if total:
            pct = int(done / total * 100)
            lbl = f'Combining {done}/{total}'
            return (
                f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:9px">'
                f'<span style="color:#f0a040;font-size:0.78rem;flex-shrink:0;width:148px">{lbl}</span>'
                f'<div style="flex:1;height:7px;border-radius:4px;background:#1a1a1a;overflow:hidden">'
                f'<div style="height:100%;width:{pct}%;background:#f0a040;border-radius:4px;'
                f'transition:width 0.3s ease"></div></div>'
                f'<span style="color:#a07030;font-size:0.7rem;width:24px;text-align:right">{pct}%</span>'
                f'</div>'
            )
        return (
            '<div style="display:flex;align-items:center;gap:10px;margin-bottom:9px">'
            '<span style="color:#f0a040;font-size:0.78rem;flex-shrink:0;width:148px">Combining</span>'
            '<div style="flex:1;height:7px;border-radius:4px;background:#1a1a1a;overflow:hidden">'
            '<div style="height:100%;width:40%;background:#f0a040;border-radius:4px;'
            'animation:tl-pulse 1.5s ease-in-out infinite"></div></div>'
            '<span style="color:#a07030;font-size:0.7rem;width:24px;text-align:right">…</span>'
            '</div>'
        )

    def _detail_combine() -> None:
        if preview_path.exists():
            ui.label('Preview ready — adjust settings and combine again, or continue to Export.').style('color:#5a9a5a;font-size:0.8rem;margin-bottom:0.5rem')
        else:
            ui.label('Choose grade and source, then click Combine clips → below.').style('color:#666;font-size:0.78rem;margin-bottom:0.5rem')

        with ui.row().style('gap:1rem;flex-wrap:wrap;align-items:flex-end;margin-bottom:0.5rem'):
            grade_sel  = ui.select(options=_GRADES, value=_combine_grade_val[0], label='Colour grade').style('min-width:130px')
            grade_sel.on_value_change(lambda e: _combine_grade_val.__setitem__(0, e.value))
            source_sel = ui.select(
                options=['All accepted', 'Still-frame picks', 'Motion picks'],
                value=_combine_source_val[0], label='Which picks',
            ).style('min-width:150px')
            source_sel.on_value_change(lambda e: _combine_source_val.__setitem__(0, e.value))
        _cbar    = ui.html('', sanitize=False)
        _cerr    = ui.label('').style('color:#e57373;font-size:0.82rem;min-height:1rem')
        _cstatus = ui.label('').style('color:#777;font-size:0.82rem;min-height:1rem')
        _combine_bar_ref[0]    = _cbar
        _combine_err_ref[0]    = _cerr
        _combine_status_ref[0] = _cstatus
        # Restore current state immediately when re-entering this step
        _ctask = state.get_task(f'assemble_{session_id}')
        if _ctask and not _ctask.done and not _ctask.error:
            _cbar.set_content(_combine_bar_content(_c_done_ref[0], _c_total_ref[0]))
            _cstatus.set_text('Combining…')
        elif preview_path.exists():
            _cbar.set_content(_combine_bar_content(0, 0, finished=True))
            _cstatus.set_text('Done.')

    _export_a16_val    = [True]
    _export_a9_val     = [False]
    _export_outdir_val = [str(config.OUTPUT_DIR)]
    _export_err_ref    = [None]
    _export_status_ref = [None]
    _export_bar_ref    = [None]
    _export_out_ref    = [None]
    _export_pct_ref    = [0]
    _export_aspect_ref = ['']

    def _export_export_bar_content(pct: int, aspect: str, done: bool = False) -> str:
        if done:
            return (
                '<div style="display:flex;align-items:center;gap:10px;margin-bottom:9px">'
                '<span style="color:#5a9a5a;font-size:0.78rem;flex-shrink:0;width:148px">Export</span>'
                '<div style="flex:1;height:7px;border-radius:4px;background:#1a3a1a">'
                '<div style="height:100%;width:100%;background:#5a9a5a;border-radius:4px"></div></div>'
                '<span style="color:#3a7a3a;font-size:0.7rem;width:24px;text-align:right">✓</span>'
                '</div>'
            )
        lbl = f'Exporting {aspect}' if aspect else 'Exporting'
        return (
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:9px">'
            f'<span style="color:#f0a040;font-size:0.78rem;flex-shrink:0;width:148px">{lbl}</span>'
            f'<div style="flex:1;height:7px;border-radius:4px;background:#1a1a1a;overflow:hidden">'
            f'<div style="height:100%;width:{pct}%;background:#f0a040;border-radius:4px;'
            f'transition:width 0.4s ease"></div></div>'
            f'<span style="color:#a07030;font-size:0.7rem;width:24px;text-align:right">{pct}%</span>'
            f'</div>'
        )

    def _detail_export() -> None:
        ui.label('Choose output settings, then click Export → below.').style('color:#666;font-size:0.78rem;margin-bottom:0.5rem')
        ui.label('Aspect ratios').style('color:#aaa;font-size:0.82rem;margin-bottom:0.3rem')
        _a16 = ui.checkbox('16:9  (YouTube / landscape)', value=_export_a16_val[0])
        _a9  = ui.checkbox('9:16  (Reels / portrait)',    value=_export_a9_val[0])
        _a16.on_value_change(lambda e: _export_a16_val.__setitem__(0, e.value))
        _a9.on_value_change(lambda e:  _export_a9_val.__setitem__(0, e.value))
        ui.label('Output folder').style('color:#aaa;font-size:0.78rem;margin-top:0.5rem;margin-bottom:0.2rem')
        with ui.row().style('align-items:center;gap:0.5rem;max-width:440px'):
            _odir = ui.input(value=_export_outdir_val[0]).style('flex:1;color:#eee')
            _odir.on_value_change(lambda e: _export_outdir_val.__setitem__(0, e.value))
            from axedup.ui.filepicker import browse_button
            browse_button(lambda p: (_odir.set_value(p), _export_outdir_val.__setitem__(0, p)), tooltip='Browse')
        _ebar    = ui.html('', sanitize=False)
        _eerr    = ui.label('').style('color:#e57373;font-size:0.82rem;min-height:1rem')
        _estatus = ui.label('').style('color:#777;font-size:0.82rem;min-height:1rem')
        _export_bar_ref[0]    = _ebar
        _export_err_ref[0]    = _eerr
        _export_status_ref[0] = _estatus
        _eout = ui.element('div').style('margin-top:0.5rem')
        _export_out_ref[0] = _eout
        _show_exports(session_id, _eout)
        # Re-entering this step while export is running: restore current progress immediately
        _etask = state.get_task(f'export_{session_id}')
        if _etask and not _etask.done and not _etask.error:
            _ebar.set_content(_export_export_bar_content(_export_pct_ref[0], _export_aspect_ref[0]))
            _estatus.set_text(f'Exporting {_export_aspect_ref[0]}…')
        elif _etask and _etask.done:
            _ebar.set_content(_export_export_bar_content(100, _export_aspect_ref[0], done=True))
            _estatus.set_text('Export complete.')

    def _detail_pick() -> None:
        if not mark_data:
            ui.label('No clips found yet.').style('color:#666;font-size:0.82rem;margin-bottom:0.5rem')
            if scan_running or highlights_running:
                ui.label('Scan is still running — check back shortly.').style('color:#888;font-size:0.78rem')
            return
        n_acc = len(mark_data) - len(rejected_ids)
        n_rej = len(rejected_ids)
        with ui.row().style('align-items:center;gap:1.5rem;margin-bottom:0.75rem'):
            ui.label(f'{len(mark_data)} moments found').style('color:#888;font-size:0.82rem')
            ui.html(
                f'<span id="pick-summary" style="color:#5a8aaa;font-size:0.82rem">'
                f'{n_acc} selected · {n_rej} skipped</span>',
                sanitize=False,
            )
        ui.label('Timeline').style('color:#888;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:0.25rem')
        ui.label(
            'Each bar in the strip above is a moment the app found interesting. '
            'Click a bar to jump to that moment in the player. '
            'Click again to toggle whether it is included in the edit.'
        ).style('color:#888;font-size:0.78rem;line-height:1.5;margin-bottom:0.3rem')
        ui.label('Green ✓ = include  ·  Red striped ✗ = skip  ·  Or click a card below.').style('color:#3e3e3e;font-size:0.73rem;margin-bottom:0.5rem')

        # Thumbnail card grid — raw HTML so onclick works without Python roundtrip
        _cards_parts = ['<div style="display:flex;flex-wrap:wrap;gap:0.4rem;margin-bottom:0.75rem">']
        for mid, cid, in_s, out_s, score, source in mark_data:
            thumb = config.THUMB_DIR / cid / f'mark_{mid}.jpg'
            img_part = (
                f'<img src="/thumbs/{cid}/mark_{mid}.jpg" style="width:100%;height:56px;object-fit:cover;display:block">'
                if thumb.exists() else
                '<div style="width:100%;height:56px;background:#111"></div>'
            )
            ts_label = f'{_tsfmt(in_s)}–{_tsfmt(out_s)}'
            accepted = mid not in rejected_ids
            border_col = '#2a7a2a' if accepted else '#7a2a2a'
            badge_col  = '#2a7a2a' if accepted else '#7a2a2a'
            badge_icon = '✓' if accepted else '✗'
            _cards_parts.append(
                f'<div id="card-{mid}" '
                f'onclick="axedupCardClick(\'{mid}\',\'{cid}\',{in_s})" '
                f'style="width:110px;background:#1a1a1a;border-radius:4px;overflow:hidden;'
                f'cursor:pointer;border:2px solid {border_col};flex-shrink:0;position:relative">'
                f'{img_part}'
                f'<div id="card-badge-{mid}" style="position:absolute;top:3px;right:3px;'
                f'width:16px;height:16px;border-radius:50%;background:{badge_col};'
                f'display:flex;align-items:center;justify-content:center;'
                f'font-size:0.5rem;color:#fff;font-weight:bold;pointer-events:none">'
                f'{badge_icon}</div>'
                f'<div style="padding:0.2rem 0.35rem">'
                f'<div style="color:#777;font-size:0.62rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{ts_label}</div>'
                f'<div style="color:#5a5a5a;font-size:0.58rem">{score:.2f}</div>'
                f'</div></div>'
            )
        _cards_parts.append('</div>')
        ui.html(''.join(_cards_parts), sanitize=False)

        init = {mid: (mid not in rejected_ids) for mid, *_ in mark_data}
        ui.run_javascript(f'''
window.axedup_decisions = {json.dumps(init)};

function _axedupToggle(mid, ok) {{
  window.axedup_decisions[mid] = ok;
  var card = document.getElementById("card-" + mid);
  if (card) card.style.borderColor = ok ? "#2a7a2a" : "#7a2a2a";
  var badge = document.getElementById("card-badge-" + mid);
  if (badge) {{
    badge.style.background = ok ? "#2a7a2a" : "#7a2a2a";
    badge.textContent = ok ? "✓" : "✗";
  }}
  var bar = document.getElementById("mark-" + mid);
  if (bar) {{
    bar.style.background = ok ? "#2a7a2a" : "#7a2a2a";
    bar.style.backgroundImage = ok ? "none"
      : "repeating-linear-gradient(-45deg,transparent,transparent 3px,rgba(0,0,0,0.35) 3px,rgba(0,0,0,0.35) 4px)";
    var ico = bar.querySelector("span.mark-icon");
    if (ico) ico.textContent = ok ? "✓" : "✗";
  }}
  var acc = Object.values(window.axedup_decisions).filter(Boolean).length;
  var s = document.getElementById("pick-summary");
  if (s) s.textContent = acc + " selected · " + (Object.keys(window.axedup_decisions).length - acc) + " skipped";
}}

function _axedupSeek(cid, ins) {{
  var v = document.getElementById("main-player");
  if (!v) return;
  var url = "/proxies/" + cid + ".mp4";
  if (!v.src.endsWith(url)) {{ v.src = url; v.load(); }}
  var seek = function() {{ v.currentTime = ins; v.play().catch(function(){{}}); }};
  if (v.readyState >= 1) seek();
  else v.addEventListener("loadedmetadata", seek, {{once:true}});
}}

window.axedupMarkClick = function(el) {{
  var mid = el.dataset.mid, cid = el.dataset.cid, ins = parseFloat(el.dataset.ins);
  _axedupToggle(mid, !window.axedup_decisions[mid]);
  _axedupSeek(cid, ins);
}};

window.axedupCardClick = function(mid, cid, ins) {{
  _axedupToggle(mid, !window.axedup_decisions[mid]);
  _axedupSeek(cid, ins);
}};
''')

    # ── Action handlers ────────────────────────────────────────────────────────

    def _start_scan() -> None:
        method = detect_method_ref[0]
        _pending_methods[session_id] = method
        state.start_task(f'{session_id}_scan')
        task_start[0] = time.time()

        def _on_event(clip_id, stage, evt_status, message, completed, total):
            if clip_id is None: return
            if evt_status in ('running', 'done', 'skipped'):
                state.update_clip_stage(session_id, clip_id, stage, evt_status)
            elif evt_status == 'progress' and completed is not None and total:
                pct = int(completed * 100 / total)
                state.update_clip_stage(session_id, clip_id, stage, 'running',
                                        pct=pct, completed=completed, total=total,
                                        message=message)

        def _run():
            try:
                from axedup.processing.analysis import run_motion_scan, extract_mark_thumbnails
                from axedup.processing.peaks import detect_peaks
                run_motion_scan(session_id, motion_method=method, on_event=_on_event)
                state.finish_task(f'{session_id}_scan')
                state.start_task(f'{session_id}_highlights')
                detect_peaks(session_id, on_event=_on_event, motion_method=method)
                state.finish_task(f'{session_id}_highlights')
                with db_session() as _db:
                    _sess = _db.query(Session).filter(Session.id == session_id).first()
                    if _sess:
                        _sess.status = SessionStatus.READY
                state.start_task(f'{session_id}_thumbnails')
                extract_mark_thumbnails(session_id, on_event=_on_event)
                state.finish_task(f'{session_id}_thumbnails')
            except Exception as exc:
                state.finish_task(f'{session_id}_scan', error=str(exc))

        threading.Thread(target=_run, daemon=True).start()
        _scan_started[0] = True
        if _timer_ref[0] is not None:
            _timer_ref[0].active = True
        _select_step('scan')

    async def _save_and_combine() -> None:
        raw = await ui.run_javascript('JSON.stringify(window.axedup_decisions || {})')
        js_dec = json.loads(raw)
        acc = rej = 0
        with db_session() as db2:
            for mid2, keep in js_dec.items():
                m2 = db2.query(Mark).filter(Mark.id == mid2).first()
                if m2:
                    m2.status = MarkStatus.ACCEPTED if keep else MarkStatus.REJECTED
                    if keep: acc += 1
                    else:    rej += 1
        ui.notify(f'Saved: {acc} in, {rej} out', type='positive')
        _select_step('combine')

    def _run_combine() -> None:
        _src_map = {'All accepted': None, 'Still-frame picks': 'jpg', 'Motion picks': 'proxy'}
        grade   = _combine_grade_val[0]
        src_val = _src_map.get(_combine_source_val[0])
        nb = next_btn_ref[0]
        if nb: nb.set_enabled(False); nb.set_text('Combining…')
        if _combine_err_ref[0]:    _combine_err_ref[0].set_text('')
        if _combine_status_ref[0]: _combine_status_ref[0].set_text('Combining clips…')
        key = f'assemble_{session_id}'
        t0  = time.time()
        state.start_task(key)
        _combine_done_ref[0] = False

        def _on_combine_progress(done: int, total: int) -> None:
            _c_done_ref[0]  = done
            _c_total_ref[0] = total

        def _run():
            try:
                from axedup.processing.assembly import assemble_session
                assemble_session(session_id, grade_override=grade, source_filter=src_val,
                                 on_progress=_on_combine_progress)
                state.finish_task(key)
            except Exception as exc:
                state.finish_task(key, error=str(exc))
        threading.Thread(target=_run, daemon=True).start()

        def _cpoll():
            t = state.get_task(key)
            if not t: return
            elapsed = _fmt(time.time() - t0)
            done  = _c_done_ref[0]
            total = _c_total_ref[0]
            if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'combining: {elapsed}')
            if t.error:
                if _combine_err_ref[0]:    _combine_err_ref[0].set_text(t.error)
                if hdr_time_ref[0]:        hdr_time_ref[0].set_text('')
                if nb: nb.set_enabled(True); nb.set_text('Combine clips →')
                next_action['fn'] = _run_combine
                _ct.active = False; return
            if t.done:
                _combine_done_ref[0] = True
                if _combine_status_ref[0]: _combine_status_ref[0].set_text(f'Done in {elapsed}.')
                if hdr_time_ref[0]:        hdr_time_ref[0].set_text(f'combined: {elapsed}')
                if _combine_bar_ref[0]:
                    _combine_bar_ref[0].set_content(_combine_bar_content(0, 0, finished=True))
                if nb: nb.set_enabled(True); nb.set_text('Continue to export →')
                next_action['fn'] = lambda: _select_step('export')
                _ct.active = False
                ui.navigate.to(f'/session/{session_id}')
            else:
                if _combine_status_ref[0]: _combine_status_ref[0].set_text(f'Combining… {elapsed} elapsed')
                if _combine_bar_ref[0]:
                    _combine_bar_ref[0].set_content(_combine_bar_content(done, total))
        _ct = ui.timer(2.0, _cpoll)

    def _do_export_trigger() -> None:
        aspects = []
        if _export_a16_val[0]: aspects.append('16:9')
        if _export_a9_val[0]:  aspects.append('9:16')
        if not aspects:
            if _export_err_ref[0]: _export_err_ref[0].set_text('Select at least one aspect ratio')
            ui.notify('Select at least one aspect ratio', type='warning')
            return
        out_dir = _export_outdir_val[0].strip() or None
        nb = next_btn_ref[0]
        if nb: nb.set_enabled(False); nb.set_text('Exporting…'); nb.props('color=grey-7')
        if _export_err_ref[0]:    _export_err_ref[0].set_text('')
        if _export_status_ref[0]: _export_status_ref[0].set_text('Starting encoder…')
        key = f'export_{session_id}'
        t0  = time.time()
        state.start_task(key)

        def _on_progress(aspect: str, pct: int) -> None:
            _export_pct_ref[0]    = pct
            _export_aspect_ref[0] = aspect

        def _run():
            try:
                from axedup.processing.export import export_session
                export_session(
                    session_id, aspects=aspects,
                    output_dir=Path(out_dir) if out_dir else None,
                    on_progress=_on_progress,
                )
                state.finish_task(key)
            except Exception as exc:
                state.finish_task(key, error=str(exc))
        threading.Thread(target=_run, daemon=True).start()

        def _epoll():
            t = state.get_task(key)
            if not t: return
            elapsed = _fmt(time.time() - t0)
            pct = _export_pct_ref[0]
            asp = _export_aspect_ref[0]
            if t.error:
                if _export_err_ref[0]: _export_err_ref[0].set_text(t.error)
                if _export_bar_ref[0]: _export_bar_ref[0].set_content('')
                if hdr_time_ref[0]:    hdr_time_ref[0].set_text('')
                if nb: nb.set_enabled(True); nb.set_text('Export →')
                next_action['fn'] = _do_export_trigger
                _et.active = False; return
            if t.done:
                if _export_status_ref[0]: _export_status_ref[0].set_text(f'Done in {elapsed}.')
                if _export_bar_ref[0]:    _export_bar_ref[0].set_content(_export_export_bar_content(100, asp, done=True))
                if hdr_time_ref[0]:       hdr_time_ref[0].set_text(f'exported: {elapsed}')
                if nb: nb.set_enabled(False); nb.set_text('Exported ✓')
                if 'export'  in dot_refs: dot_refs['export'].set_content(_dot_html('done'))
                if 'combine' in dot_refs: dot_refs['combine'].set_content(_dot_html('done'))
                if 'pick'    in dot_refs: dot_refs['pick'].set_content(_dot_html('done'))
                _elapsed_timer.active = False
                _et.active = False
                if _export_out_ref[0]: _show_exports(session_id, _export_out_ref[0])
            else:
                if _export_status_ref[0]: _export_status_ref[0].set_text(f'Exporting {asp}… {elapsed} elapsed')
                if _export_bar_ref[0]:    _export_bar_ref[0].set_content(_export_export_bar_content(pct, asp))
                if hdr_time_ref[0]:       hdr_time_ref[0].set_text(f'exporting: {elapsed}')
        _et = ui.timer(1.0, _epoll)

    # ── Initial render ─────────────────────────────────────────────────────────
    _select_step(initial)

    # ── Persistent elapsed timer ───────────────────────────────────────────────
    def _elapsed_tick() -> None:
        import datetime
        elapsed_s = max(0, int((datetime.datetime.utcnow() - created).total_seconds())) if created else 0
        m, s = divmod(elapsed_s, 60)
        text = f'elapsed {m}m{s:02d}s' if m else f'elapsed {s}s'
        if hdr_elapsed_ref[0]:
            hdr_elapsed_ref[0].set_text(text)

    _elapsed_timer = ui.timer(1.0, _elapsed_tick)

    # ── Poll timer ──────────────────────────────────────────────────────────────
    _any_bg = proxy_running or scan_running or highlights_running
    _proxy_shown = [bool(init_src)]

    def _poll() -> None:
            tp   = state.get_task(f'{session_id}_proxy')
            ts   = state.get_task(f'{session_id}_scan')
            th   = state.get_task(f'{session_id}_highlights')
            tleg = state.get_task(session_id)

            _p_active = tp   is not None and not tp.done
            _s_active = ts   is not None and not ts.done
            _h_active = th   is not None and not th.done
            _l_active = tleg is not None and not tleg.done
            still_running = _p_active or _s_active or _h_active or _l_active

            prog    = state.get_clip_progress(session_id)
            elapsed = _fmt(time.time() - task_start[0])

            # Header timing + dot updates
            if _p_active:
                est = _fmt(max(60, int(total_s)))
                if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'working copy: {elapsed} / ~{est}')
                if 'proxy' in dot_refs: dot_refs['proxy'].set_content(_dot_html('running'))
            elif _s_active:
                est = _fmt(max(30, int(total_s // 3)))
                if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'scanning: {elapsed} / ~{est}')
                if 'scan'   in dot_refs: dot_refs['scan'].set_content(_dot_html('running'))
                if 'method' in dot_refs: dot_refs['method'].set_content(_dot_html('done'))
            elif _h_active:
                if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'finding clips: {elapsed}')
                if 'highlights' in dot_refs: dot_refs['highlights'].set_content(_dot_html('running'))
                if 'scan'       in dot_refs: dot_refs['scan'].set_content(_dot_html('done'))
                if 'method'     in dot_refs: dot_refs['method'].set_content(_dot_html('done'))

            # Keep completed-step dots green after their task finishes
            if tp and tp.done:
                if 'proxy' in dot_refs: dot_refs['proxy'].set_content(_dot_html('done'))
            if ts and ts.done:
                if 'scan'   in dot_refs: dot_refs['scan'].set_content(_dot_html('done'))
                if 'method' in dot_refs: dot_refs['method'].set_content(_dot_html('done'))
            if th and th.done:
                if 'highlights' in dot_refs: dot_refs['highlights'].set_content(_dot_html('done'))
                if 'scan'       in dot_refs: dot_refs['scan'].set_content(_dot_html('done'))
                if 'method'     in dot_refs: dot_refs['method'].set_content(_dot_html('done'))

            # Reveal proxy player (swap still/placeholder → video) when first proxy is ready
            if not _proxy_shown[0] and clip_ids:
                px_st = prog.get(clip_ids[0], {}).get('proxy', StageState())
                if px_st.status in ('done', 'skipped'):
                    _proxy_shown[0] = True
                    ui.run_javascript(f'''
                      var v=document.getElementById("main-player");
                      var ph=document.getElementById("player-ph");
                      var st=document.getElementById("player-still");
                      if(v){{v.src="/proxies/{clip_ids[0]}.mp4";v.load();v.style.display="block";}}
                      if(ph)ph.style.display="none";
                      if(st)st.style.display="none";
                    ''')

            # Update detail-pane bars
            step_stage_map = {
                'proxy': _PROXY_STAGES,
                'scan':  _SCAN_STAGES,
            }
            if selected[0] in step_stage_map:
                stages = step_stage_map[selected[0]]
                for cid, stage_map in bar_refs.items():
                    cp = prog.get(cid, {})
                    for stage, el in stage_map.items():
                        if stage in stages:
                            el.set_content(_bar_html(
                                cp.get(stage, StageState()),
                                _STAGE_LABEL[stage], stage, detect_method_ref[0],
                            ))

            # Error check
            for t in (tp, ts, th, tleg):
                if t and t.error:
                    ui.notify(f'Error: {t.error}', type='negative', timeout=0)
                    _timer.active = False
                    return

            # Completion
            if not still_running:
                _timer.active = False
                if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'took {elapsed}')
                ui.navigate.to(f'/session/{session_id}')

    _timer = ui.timer(0.5, _poll, active=_any_bg)
    _timer_ref[0] = _timer


# ── New session view (/session/new) ────────────────────────────────────────────

def _new_session_ui() -> None:
    """3-pane layout for a brand-new session (no DB record yet).
    File picker + sport + method live in the Input step's detail pane.
    On Import, ingest runs, proxy task begins, then navigates to /session/{id}.
    """
    with db_session() as db:
        sports = [p.sport for p in db.query(Profile).order_by(Profile.sport).all()] or _SPORT_FB

    sel_files: list[Path] = []
    path_input_ref = [None]
    sport_sel_ref  = [None]
    err_ref        = [None]
    start_btn_ref  = [None]
    start_lbl_ref  = [None]

    async def _do_start() -> None:
        pi = path_input_ref[0]; ss = sport_sel_ref[0]; er = err_ref[0]
        sb = start_btn_ref[0]; sl = start_lbl_ref[0]
        if not pi or not pi.value.strip():
            if er: er.set_text('Enter a path or use the browse button')
            return
        src = Path(pi.value.strip())
        if not src.exists():
            if er: er.set_text('Path not found — check and try again')
            return
        if er: er.set_text('')
        if sb: sb.set_enabled(False)
        if sl: sl.set_text('Importing clips…')

        files_to_import = sel_files[:] if sel_files else None
        try:
            from axedup.processing.ingest import ingest_folder
            from nicegui import run as ng_run
            session_obj = await ng_run.io_bound(ingest_folder, src, ss.value if ss else 'unknown', None, files_to_import)
        except Exception as exc:
            if sb: sb.set_enabled(True)
            if sl: sl.set_text('')
            if er: er.set_text(str(exc))
            return

        sid = session_obj.id

        # Extract a still from first source file for the player placeholder
        if sl: sl.set_text('Extracting preview frame…')
        with db_session() as db:
            first_clip = db.query(Clip).filter(Clip.session_id == sid).order_by(Clip.clip_order).first()
        if first_clip:
            still_dest = config.STILL_DIR / f'{sid}_still.jpg'
            from axedup.processing.analysis import extract_source_still
            await ng_run.io_bound(extract_source_still, Path(first_clip.filepath), still_dest)

        state.start_task(f'{sid}_proxy')

        def _on_event(clip_id, stage, evt_status, message, completed, total):
            if clip_id is None: return
            if evt_status in ('running', 'done', 'skipped'):
                state.update_clip_stage(sid, clip_id, stage, evt_status)
            elif evt_status == 'progress' and completed is not None and total:
                pct = int(completed * 100 / total)
                state.update_clip_stage(sid, clip_id, stage, 'running',
                                        pct=pct, completed=completed, total=total, message=message)

        def _run_proxy():
            try:
                from axedup.processing.analysis import build_proxy_only
                build_proxy_only(sid, on_event=_on_event)
                state.finish_task(f'{sid}_proxy')
            except Exception as exc:
                state.finish_task(f'{sid}_proxy', error=str(exc))

        threading.Thread(target=_run_proxy, daemon=True).start()
        ui.navigate.to(f'/session/{sid}')

    _mini = [False]
    drawer = ui.left_drawer(value=True).style('background:#1a1a1a;border-right:1px solid #222')
    drawer.props('breakpoint=0 width=180 mini-width=48')
    with drawer:
        sidebar('home')

    def _toggle_nav() -> None:
        _mini[0] = not _mini[0]
        if _mini[0]: drawer.props(add='mini')
        else:        drawer.props(remove='mini')

    with ui.column().style('width:100%;height:100vh;background:#111;padding:0;gap:0;overflow:hidden'):
        # Header
        with ui.row().style(
            f'height:{_HDR_H}px;flex-shrink:0;width:100%;align-items:center;'
            'justify-content:space-between;padding:0 1rem;background:#141414;border-bottom:1px solid #1a1a1a'
        ):
            with ui.row().style('align-items:center;gap:0.5rem'):
                ui.button(icon='menu', on_click=_toggle_nav).props('flat round dense').style('color:#888')
                ui.label('New session').style('color:#eee;font-size:0.88rem;font-weight:600')
            ui.button('← Home', on_click=lambda: ui.navigate.to('/')).props('flat size=sm').style('color:#888')

        # Top row
        with ui.row().style(f'width:100%;height:{_TOP_H};gap:0;flex-shrink:0;overflow:hidden'):
            # Video placeholder
            with ui.column().style(
                'width:60%;height:100%;background:#000;'
                'align-items:center;justify-content:center;flex-shrink:0'
            ):
                ui.html(
                    '<div style="display:flex;flex-direction:column;align-items:center;gap:0.5rem">'
                    '<span style="color:#5a5a5a;font-size:2.5rem">▷</span>'
                    '<span style="color:#5a5a5a;font-size:0.82rem">Preview will appear here</span></div>',
                    sanitize=False,
                )
            # Step list
            with ui.column().style(
                'width:40%;height:100%;gap:0;flex-shrink:0;'
                'border-left:1px solid #1a1a1a;overflow-y:auto;background:#111'
            ):
                with ui.row().style(
                    'padding:0.3rem 0.75rem;background:#0d0d0d;border-bottom:1px solid #1a1a1a;flex-shrink:0'
                ):
                    ui.label('Step').style('color:#3e3e3e;font-size:0.67rem;text-transform:uppercase;letter-spacing:0.07em')
                for step_id, title, subtitle in _STEPS:
                    st = 'active' if step_id == 'input' else 'pending'
                    with ui.row().style(_row_style(step_id == 'input')):
                        ui.html(_dot_html(st), sanitize=False, tag='span').style('margin-top:3px;flex-shrink:0')
                        with ui.column().style('gap:0.06rem;flex:1;min-width:0'):
                            tc = '#eee' if step_id == 'input' else '#444'
                            tw = '600' if step_id == 'input' else '400'
                            ui.label(title).style(f'font-size:0.83rem;font-weight:{tw};color:{tc}')
                            ui.label(subtitle).style('color:#888;font-size:0.7rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis')

        # Bottom detail
        with ui.column().style(f'width:100%;height:{_BOT_H};gap:0;border-top:1px solid #1a1a1a;overflow:hidden'):
            with ui.column().style('flex:1;min-height:0;overflow-y:auto;padding:0.75rem 1.25rem;gap:0'):
                ui.label('Select footage').style('color:#aaa;font-size:0.85rem;font-weight:600;margin-bottom:0.4rem')
                ui.label('Pick one or more video files, or a folder to import everything in it.').style(
                    'color:#888;font-size:0.77rem;margin-bottom:0.5rem'
                )
                with ui.row().style('align-items:center;gap:0.5rem;max-width:480px'):
                    _pi = ui.input(placeholder='/path/to/clip.mp4  or  /media/SDCARD/DCIM').style('flex:1;color:#eee')
                    path_input_ref[0] = _pi
                    _hint = ui.label('').style('color:#888;font-size:0.78rem')

                    async def _browse() -> None:
                        try:
                            from nicegui import app as nicegui_app
                            import webview
                            result = await nicegui_app.native.main_window.create_file_dialog(
                                webview.FileDialog.OPEN, allow_multiple=True,
                                file_types=('Video files (*.mp4;*.MP4;*.mov;*.MOV;*.avi)',),
                            )
                        except Exception as exc:
                            ui.notify(f'File picker unavailable: {exc}', type='warning')
                            return
                        if result:
                            paths = [Path(r) for r in result]
                            sel_files.clear(); sel_files.extend(paths)
                            _pi.set_value(str(paths[0].parent))
                            _hint.set_text(f'{len(paths)} file(s) selected')
                        else:
                            try:
                                from nicegui import app as nicegui_app
                                import webview
                                folder = await nicegui_app.native.main_window.create_file_dialog(
                                    webview.FileDialog.FOLDER, allow_multiple=False)
                            except Exception as exc:
                                ui.notify(f'Folder picker unavailable: {exc}', type='warning')
                                return
                            if folder:
                                _pi.set_value(folder[0])
                                sel_files.clear()
                                _hint.set_text('All video files in this folder will be imported')

                    ui.button(icon='folder_open', on_click=_browse).props('flat round dense').tooltip('Browse')

                with ui.row().style('gap:1.5rem;margin-top:0.6rem;flex-wrap:wrap;align-items:flex-end'):
                    _ss = ui.select(options=sports, value=sports[0], label='Sport').style('min-width:130px')
                    sport_sel_ref[0] = _ss

                _er = ui.label('').style('color:#e57373;font-size:0.82rem;min-height:1rem;margin-top:0.25rem')
                err_ref[0] = _er

            with ui.row().style(
                'height:40px;flex-shrink:0;border-top:1px solid #1a1a1a;background:#141414;'
                'padding:0 1rem;align-items:center;gap:0.75rem;justify-content:flex-end'
            ):
                _sl = ui.label('').style('color:#666;font-size:0.78rem;flex:1')
                start_lbl_ref[0] = _sl
                _sb = ui.button('Import & build working copy →', on_click=_do_start).props('color=positive size=sm')
                start_btn_ref[0] = _sb
