"""
Session view — stage-table + player-area layout.
Routes: /session/{session_id}  (existing session)
        /session/new           (new session — EMPTY player mode)

  ┌─────────────────────────────────────────────────────────┐
  │  sport · date · elapsed · est total           [delete]  │
  ├──────────────────┬──────────────────────────────────────┤
  │  Stage table     │  step options        [Next action →] │
  │  (300px)         ├──────────────────────────────────────┤
  │                  │  Video player area                   │
  │  Select video    │  EMPTY | PREVIEW | REVIEW | OUTPUT   │
  │  Trim video      │                                      │
  │    Create copy   │                                      │
  │    Detect scenes │                                      │
  │    Find clips    │                                      │
  │    Select clips  │                                      │
  │    Combine clips ├──────────────────────────────────────┤
  │  [Add text]      │  (REVIEW: timeline + thumbnail       │
  │  [Add music]     │   cards below the player)            │
  │  Export          │                                      │
  └──────────────────┴──────────────────────────────────────┘
  Hamburger / chevron toggle lives at the top of the left nav drawer.
"""
import inspect
import json
import shutil
import time
from pathlib import Path

from nicegui import ui

from avs import config
from avs.models.db import get_session as db_session
from avs.models.schema import (
    Clip, Export, Mark, MarkStatus, Profile, Session, SessionStatus, TelemetryPoint,
)
from avs.prefs import get_prefs
from avs.presets.sports import display_name
from avs.ui import state
from avs.ui.state import StageState
from avs.ui.layout import sidebar

# ── Constants ──────────────────────────────────────────────────────────────────

_GRADES   = ['punchy', 'cinematic', 'natural', 'warm', 'cool', 'vibrant']
_SPORT_FB = ['moto', 'mtb', 'surf', 'ski', 'cycling', 'trail', 'skydive']


def _sport_order(sports: list[str]) -> list[str]:
    """Motorcycle first (per user preference, it's the default), rest alphabetical."""
    return sorted(sports, key=lambda s: (s != 'moto', s))

_PROXY_STAGES = ['proxy']
_SCAN_STAGES  = ['scenes', 'motion', 'audio']
_STAGE_LABEL  = {'proxy': 'Working copy', 'scenes': 'Scene cuts',
                 'motion': 'Optical flow', 'audio': 'Audio energy'}
_STAGE_BYLINE = {
    'proxy':  '480p transcode — originals are only read once',
    'scenes': 'Finds camera cuts and hard transitions',
    'motion': 'Quick: 1fps sample  ·  Full: every frame',
    'audio':  'RMS loudness from proxy audio',
}

_HDR_H    = 46
_TABLE_W  = 300

_CSS = """
@keyframes tl-pulse{0%,100%{opacity:1}50%{opacity:0.35}}
.tl-run{animation:tl-pulse 1s ease-in-out infinite}
.q-btn.disabled,.q-btn[disabled]{opacity:0.35!important;cursor:not-allowed!important}

/* ── Stage table ────────────────────────────────────────────────────────── */
.ax2-table{
  width:300px;min-width:300px;height:100%;background:#0d0d0d;
  border-right:1px solid #222;display:flex;flex-direction:column;
  flex-shrink:0;transition:width 0.2s ease,min-width 0.2s ease;overflow:hidden
}
.ax2-table.ax2-review{width:190px;min-width:190px}

/* Column header */
.ax2-col-hdr{
  display:grid;grid-template-columns:1fr 44px 52px 40px;
  padding:0.22rem 0.7rem 0.22rem 0.9rem;background:#0a0a0a;
  border-bottom:1px solid #1e1e1e;flex-shrink:0;gap:0.25rem
}
.ax2-col-hdr span{
  font-size:0.58rem;text-transform:uppercase;letter-spacing:0.08em;color:#333;text-align:right
}
.ax2-col-hdr span:first-child{text-align:left}

/* Section header rows (Select video, Trim video, Export) */
.ax2-section{
  padding:0.5rem 0.7rem;background:#151515;border-bottom:1px solid #1e1e1e;
  font-size:0.82rem;font-weight:700;color:#ccc;letter-spacing:0.01em;
  display:flex;align-items:center;gap:0.45rem;flex-shrink:0;
  white-space:nowrap;overflow:hidden
}
.ax2-section.active{color:#fff;border-left:3px solid #ff8c00;padding-left:calc(0.7rem - 3px)}
.ax2-section.done{color:#3aaa3a}
.ax2-section.future{color:#333;font-style:italic}

/* Sub-rows (Create working copy, Detect scenes, etc.) */
.ax2-sub{
  display:grid;grid-template-columns:12px 1fr 44px 52px 40px;
  align-items:center;gap:0.3rem;
  padding:0.38rem 0.7rem 0.38rem 1.5rem;
  border-bottom:1px solid #181818;
  font-size:0.79rem;color:#aaa;flex-shrink:0;
  transition:background 0.1s
}
.ax2-sub:not(.pending){cursor:pointer}
.ax2-sub:hover:not(.pending){background:#181818}
.ax2-sub.active{background:#1a1a1a;color:#fff;border-left:3px solid #ff8c00;padding-left:calc(1.5rem - 3px)}
.ax2-sub.done{color:#4a8a4a}
.ax2-sub.running{color:#e09030}
.ax2-sub.pending{color:#3a3a3a}

.ax2-sub-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ax2-sub-est{text-align:right;font-size:0.68rem;color:#555;overflow:hidden;white-space:nowrap}
.ax2-sub-act{text-align:right;font-size:0.68rem;color:#6a8a9a;overflow:hidden;white-space:nowrap}
.ax2-sub-count{text-align:right;font-size:0.68rem;color:#888;overflow:hidden;white-space:nowrap}
.ax2-sub.active .ax2-sub-est{color:#888}
.ax2-sub.active .ax2-sub-count{color:#ccc}
.ax2-sub.done .ax2-sub-est{color:#3a6a3a}
.ax2-sub.done .ax2-sub-act,.ax2-sub.done .ax2-sub-count{color:#3a6a3a}

/* Section est/act/count labels */
.ax2-sec-est{width:44px;text-align:right;font-size:0.68rem;color:#555;flex-shrink:0}
.ax2-sec-act{width:52px;text-align:right;font-size:0.68rem;color:#6a8a9a;flex-shrink:0}
.ax2-sec-count{width:40px;text-align:right;font-size:0.68rem;color:#888;flex-shrink:0}

/* Hide est/act (keep counts) when table is compressed (REVIEW mode) */
.ax2-table.ax2-review .ax2-sub-est,
.ax2-table.ax2-review .ax2-sub-act,
.ax2-table.ax2-review .ax2-sec-est,
.ax2-table.ax2-review .ax2-sec-act{display:none}
.ax2-table.ax2-review .ax2-sub{
  grid-template-columns:12px 1fr 40px;padding-right:0.4rem
}
.ax2-table.ax2-review .ax2-col-hdr{display:none}

/* ── Player column ──────────────────────────────────────────────────────── */
.ax2-player-col{
  flex:1;min-width:0;height:100%;display:flex;flex-direction:column;overflow:hidden
}
.ax2-player-frame{
  flex:3;min-height:0;display:flex;flex-direction:column;
  border:1px solid #262626;border-radius:4px;margin:0.45rem;overflow:hidden
}
.ax2-player-tag{
  height:22px;flex-shrink:0;background:#0d0d0d;border-bottom:1px solid #1e1e1e;
  display:flex;align-items:center;padding:0 0.6rem;
  font-size:0.64rem;letter-spacing:0.07em;text-transform:uppercase;color:#777
}
.ax2-player-main{
  flex:1;min-height:0;position:relative;overflow:hidden;background:#000
}
.ax2-player-main video,.ax2-player-main img{
  position:absolute;top:0;left:0;width:100%;height:100%;
  object-fit:contain;display:block;background:#000
}
.ax2-review-panel{
  display:none;flex-direction:column;flex:2;min-height:0;
  border-top:1px solid #1a1a1a;background:#0a0a0a;overflow:hidden
}
.ax2-review-panel.visible{display:flex}
.ax2-action-bar{
  min-height:48px;flex-shrink:0;border-bottom:1px solid #222;background:#141414;
  padding:0.2rem 0.9rem;display:flex;align-items:center;gap:0.6rem
}

/* ── Drop zone (EMPTY mode) ─────────────────────────────────────────────── */
.ax2-dz{
  position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:0.75rem;background:#050505
}
.ax2-dz-ring{
  width:80px;height:80px;border-radius:50%;border:2px dashed #2a2a2a;
  display:flex;align-items:center;justify-content:center;color:#3a3a3a;font-size:2rem
}
.ax2-dz-label{color:#555;font-size:0.88rem;letter-spacing:0.03em}
.ax2-dz-sub{color:#333;font-size:0.72rem}
"""

_pending_methods: dict[str, str] = {}

# filepath → served URL, so repeat page loads don't register duplicate routes
_media_urls: dict[str, str] = {}


def _media_url(path: Path) -> str:
    key = str(path)
    if key not in _media_urls:
        from nicegui import app as ng_app
        _media_urls[key] = ng_app.add_media_file(local_file=path)
    return _media_urls[key]


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _fmt(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    if h:
        return f'{h}h {m}m {s}s'
    return f'{m}m {s}s' if m else f'{s}s'


def _tsfmt(ts: float) -> str:
    m, s = divmod(int(ts), 60)
    return f'{m}:{s:02d}'


def _dot_html(st: str) -> str:
    if st == 'done':
        c, cls = '#3aaa3a', ''
    elif st == 'running':
        c, cls = '#f0a040', 'class="tl-run"'
    elif st == 'active':
        c, cls = '#6a9aaa', ''
    else:
        return ('<span style="width:9px;height:9px;border-radius:50%;'
                'background:#1c1c1c;border:1px solid #2a2a2a;display:inline-block"></span>')
    return (f'<span {cls} style="width:9px;height:9px;border-radius:50%;'
            f'background:{c};display:inline-block"></span>')


def _bar_html(s: StageState, label: str, stage: str, method: str = 'proxy') -> str:
    """PREVIEW overlay progress bar — [label 148px] [bar flex] [pct 24px]"""
    if s.status in ('done', 'skipped'):
        return (
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:9px">'
            f'<span style="color:#3aaa3a;font-size:0.78rem;flex-shrink:0;width:148px">{label}</span>'
            f'<div style="flex:1;height:7px;border-radius:4px;background:#1a3a1a;overflow:hidden">'
            f'<div style="height:100%;width:100%;background:#3aaa3a;border-radius:4px"></div></div>'
            f'<span style="color:#2a7a2a;font-size:0.7rem;width:24px;text-align:right">✓</span>'
            f'</div>'
        )
    if s.status == 'running':
        pct = (s.pct if s.pct is not None
               else (int(s.completed / s.total * 100) if s.completed and s.total else 0))
        sub = ''
        if stage == 'motion' and s.completed and s.total:
            phase = s.message or 'Comparing'
            mode  = '1fps sample' if method == 'jpg' else 'all frames'
            sub   = f'{phase} · {mode} · {s.completed:,}/{s.total:,}'
        elif stage == 'proxy' and s.pct is not None:
            sub = f'Transcoding {s.pct}%'
        elif s.message:
            sub = s.message
        return (
            f'<div style="margin-bottom:9px">'
            f'<div style="display:flex;align-items:center;gap:10px">'
            f'<span style="color:#f0a040;font-size:0.78rem;flex-shrink:0;width:148px">{label}</span>'
            f'<div style="flex:1;height:7px;border-radius:4px;background:#1a1a1a;overflow:hidden">'
            f'<div style="height:100%;width:{pct}%;background:#f0a040;border-radius:4px;transition:width 0.3s ease"></div></div>'
            f'<span style="color:#a07030;font-size:0.7rem;width:24px;text-align:right">{pct}%</span>'
            f'</div>'
            + (f'<div style="padding-left:158px;margin-top:2px">'
               f'<span style="color:#8a7a5a;font-size:0.68rem">{sub}</span></div>' if sub else '')
            + '</div>'
        )
    return (
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:9px">'
        f'<span style="color:#484848;font-size:0.78rem;flex-shrink:0;width:148px">{label}</span>'
        f'<div style="flex:1;height:7px;border-radius:4px;background:#161616;overflow:hidden"></div>'
        f'<span style="color:#3e3e3e;font-size:0.7rem;width:24px;text-align:right">—</span>'
        f'</div>'
    )


# Visuals per review state: (bar/border colour, hatch background-image, badge icon)
_PICK_STYLE = {
    'in':   ('#2a7a2a', 'none', '✓'),
    'out':  ('#7a2a2a',
             'repeating-linear-gradient(-45deg,transparent,transparent 3px,'
             'rgba(0,0,0,0.35) 3px,rgba(0,0,0,0.35) 4px)', '✗'),
    'skip': ('#8a6a18',
             'repeating-linear-gradient(45deg,transparent,transparent 4px,'
             'rgba(0,0,0,0.3) 4px,rgba(0,0,0,0.3) 6px)', 'z'),
    'dull': ('#a8541d', 'none', '–'),
}


def _timeline_html(mark_data: list, clip_info: list, statuses: dict | None = None) -> str:
    statuses = statuses or {}
    marks_by_clip: dict = {}
    for mid, cid, in_s, out_s, _score, src in mark_data:
        marks_by_clip.setdefault(cid, []).append((mid, in_s, out_s, src))
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
        for mid, in_s, out_s, src in marks_by_clip.get(cid, []):
            ip = in_s / dur_s * 100
            wp = (out_s - in_s) / dur_s * 100
            st = statuses.get(mid, 'in')
            color, hatch, icon = _PICK_STYLE[st]
            tip = f'{_tsfmt(in_s)}–{_tsfmt(out_s)} ({out_s-in_s:.1f}s)'
            if src == 'audio_spike':
                tip += ' — found by audio'
            if st == 'skip':
                tip += ' — flagged boring, click to include'
            elif st == 'dull':
                tip += ' — dull (unclassified), click to include'
            out.append(
                f'<div id="mark-{mid}" data-mid="{mid}" data-cid="{cid}" data-ins="{in_s}"'
                f' style="position:absolute;top:15px;left:{ip:.2f}%;'
                f'width:max({max(wp,2):.2f}%,40px);bottom:2px;background:{color};'
                f'background-image:{hatch};'
                f'border-radius:2px;cursor:pointer;transition:background 0.15s;'
                f'display:flex;align-items:center;justify-content:center;overflow:hidden"'
                f' onclick="avsMarkClick(this)" title="{tip}">'
                f'<span class="mark-icon" style="font-size:0.45rem;color:rgba(255,255,255,0.85);'
                f'pointer-events:none">{icon}</span></div>'
            )
        out.append('</div>')
        clip_start += dur_s
    out.append('</div>')
    return ''.join(out)


def _profile_info_html(sport: str) -> str:
    """What the sport profile actually does to the pipeline, in plain words.
    Lists only fields that are wired in today; the rest are called out as inert."""
    from avs.presets.sports import DEFAULT_PROFILES
    with db_session() as db:
        p = db.query(Profile).filter(Profile.sport == sport).first()
        vals = (
            {'color_grade': p.color_grade, 'motion_threshold': p.motion_threshold,
             'scene_detector': p.scene_detector, 'scene_threshold': p.scene_threshold,
             'scene_min_scene_len': p.scene_min_scene_len}
            if p else DEFAULT_PROFILES.get(sport)  # same fallback the pipeline uses
        )
    if not vals:
        return ('<div style="color:#888;font-size:0.75rem;padding:0.6rem">'
                f'No profile found for "{sport}" — pipeline defaults apply.</div>')
    det = vals.get('scene_detector') or 'content'
    if vals.get('scene_threshold') is not None:
        det += f' @ {vals["scene_threshold"]:g}'
    if vals.get('scene_min_scene_len') is not None:
        det += f' · min {vals["scene_min_scene_len"]} frames'
    mt = vals.get('motion_threshold')
    rows = [
        ('Default grade', vals.get('color_grade') or 'natural',
         'starting colour grade at the Combine step (changeable there)'),
        ('Motion threshold', f'{mt:g}' if mt is not None else '—',
         'how much motion counts as a highlight — lower finds more clips'),
        ('Scene detection', det,
         'how camera cuts are found when scanning'),
    ]
    out = [
        '<div style="max-width:340px;padding:0.6rem 0.75rem;font-size:0.75rem;color:#bbb">',
        f'<div style="font-weight:700;color:#ddd;margin-bottom:0.45rem">What the '
        f'<span style="color:#5a9a5a">{display_name(sport)}</span> profile sets</div>',
    ]
    for name, val, why in rows:
        out.append(
            f'<div style="margin-bottom:0.4rem">'
            f'<span style="color:#eee">{name}:</span> '
            f'<span style="color:#e09030">{val}</span><br>'
            f'<span style="color:#777;font-size:0.7rem">{why}</span></div>'
        )
    out.append(
        '<div style="border-top:1px solid #333;margin-top:0.5rem;padding-top:0.4rem;'
        'color:#666;font-size:0.68rem">Stored but not used by the pipeline yet: '
        'clip length bounds, target durations, music energy, telemetry overlays, '
        'speed threshold.</div></div>'
    )
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
                    ui.badge(exp.aspect).style('background:#1a2a1a;color:#3aaa3a;font-size:0.7rem')
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
    (config.STILL_DIR / f'{session_id}_still.jpg').unlink(missing_ok=True)
    for sw in config.STILL_DIR.glob(f'{session_id}_grade_*.jpg'):
        sw.unlink(missing_ok=True)
    for cid in clip_ids:
        (config.PROXY_DIR / f'{cid}.mp4').unlink(missing_ok=True)
        shutil.rmtree(config.THUMB_DIR / cid, ignore_errors=True)
        shutil.rmtree(config.JPEG_FRAMES_DIR / cid, ignore_errors=True)
    for mid in mark_ids:
        (config.SEGMENT_DIR / f'{mid}.mp4').unlink(missing_ok=True)
        (config.SEGMENT_DIR / 'encoded' / f'{mid}.mp4').unlink(missing_ok=True)
        for enc in (config.SEGMENT_DIR / 'encoded').glob(f'{mid}_*.mp4'):
            enc.unlink(missing_ok=True)
    ui.navigate.to('/')


# ── Main page ──────────────────────────────────────────────────────────────────

@ui.page('/session/{session_id}')
def session_page(session_id: str) -> None:
    ui.dark_mode().enable()
    ui.add_head_html(f'<style>{_CSS}</style>')
    _prefs = get_prefs()
    # Block the webview's default file-drop behavior — without this, dropping a
    # video onto the window navigates away from the app to fullscreen playback.
    ui.add_head_html(
        '<script>'
        "window.addEventListener('dragover',function(e){e.preventDefault();});"
        "window.addEventListener('drop',function(e){e.preventDefault();});"
        '</script>'
    )

    is_new = (session_id == 'new')

    # ── DB load ────────────────────────────────────────────────────────────────
    if is_new:
        status = sport = src = created = None
        clip_ids = clip_info = mark_data = []
        total_s = 0.0
        rejected_ids: set = set()
        boring_ids: set = set()
        dull_ids: set = set()
        all_proxies_done = proxy_running = scan_running = highlights_running = False
        has_motion_data = post_analysis = False
        preview_path = Path('/nonexistent/_preview.mp4')
        still_path   = Path('/nonexistent/_still.jpg')
        detect_method_ref = [_prefs['default_scan_method']]
        with db_session() as db:
            sports = _sport_order([p.sport for p in db.query(Profile).order_by(Profile.sport).all()] or _SPORT_FB)
    else:
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
            total_s   = sum(c.duration_s or 0 for c in clips)
            marks_all = (
                db.query(Mark)
                .join(Clip, Mark.clip_id == Clip.id)
                .filter(Mark.clip_id.in_(clip_ids))
                .filter(Mark.status.in_([MarkStatus.CANDIDATE, MarkStatus.ACCEPTED,
                                         MarkStatus.REJECTED, MarkStatus.BORING,
                                         MarkStatus.DULL]))
                .order_by(Clip.clip_order, Mark.in_s)
                .all()
            ) if clip_ids else []
            mark_data    = [(m.id, m.clip_id, m.in_s, m.out_s, m.score or 0.0, m.source) for m in marks_all]
            from avs.processing.audio import clip_audio_spikes
            from avs.prefs import get_prefs as _get_prefs
            _spike_k = float(_get_prefs().get('audio_spike_k', 3.0))
            _audio_spikes: dict[str, list[float]] = {
                cid: clip_audio_spikes(cid, _spike_k) for cid in clip_ids
            }
            rejected_ids = {m.id for m in marks_all if m.status == MarkStatus.REJECTED}
            boring_ids   = {m.id for m in marks_all if m.status == MarkStatus.BORING}
            dull_ids     = {m.id for m in marks_all if m.status == MarkStatus.DULL}
            sports = _sport_order([p.sport for p in db.query(Profile).order_by(Profile.sport).all()] or _SPORT_FB)

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
        detect_method_ref = [_pending_methods.get(session_id, _prefs['default_scan_method'])]

    # Review state per mark: 'in' | 'out' | 'skip' (boring) | 'dull' (unclaimed gap)
    _statuses = {
        mid: ('out' if mid in rejected_ids else
              'skip' if mid in boring_ids else
              'dull' if mid in dull_ids else 'in')
        for mid, *_ in mark_data
    }

    # ── Stage status ───────────────────────────────────────────────────────────

    def _stage_st(sid: str) -> str:
        if is_new:
            return 'active' if sid == 'input' else 'pending'
        if sid == 'input':
            return 'done' if clip_ids else 'active'
        if sid == 'proxy':
            if all_proxies_done:  return 'done'
            if proxy_running:     return 'running'
            return 'active' if clip_ids else 'pending'
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
            t = state.get_task(f'assemble_{session_id}')
            if t and not t.done: return 'running'
            if status in (SessionStatus.ASSEMBLED, SessionStatus.EXPORTED): return 'done'
            if preview_path.exists(): return 'done'
            return 'pending'
        if sid == 'export':
            if status == SessionStatus.EXPORTED: return 'done'
            t = state.get_task(f'export_{session_id}')
            if t and not t.done: return 'running'
            return 'active' if preview_path.exists() else 'pending'
        return 'pending'

    if is_new:
        initial_stage = 'input'
    elif not clip_ids:
        initial_stage = 'input'
    elif proxy_running or not all_proxies_done:
        initial_stage = 'proxy'
    elif scan_running:
        initial_stage = 'scan'
    elif highlights_running:
        initial_stage = 'highlights'
    elif post_analysis:
        if status == SessionStatus.EXPORTED:
            initial_stage = 'export'
        elif status == SessionStatus.ASSEMBLED or preview_path.exists():
            initial_stage = 'combine'
        else:
            initial_stage = 'pick'
    elif has_motion_data:
        initial_stage = 'highlights'
    else:
        initial_stage = 'scan'

    # A combine/export started on a previous page view may still be running —
    # land on that stage so its watcher can re-attach.
    if not is_new:
        _t_asm0 = state.get_task(f'assemble_{session_id}')
        _t_exp0 = state.get_task(f'export_{session_id}')
        if _t_exp0 and not _t_exp0.done:
            initial_stage = 'export'
        elif _t_asm0 and not _t_asm0.done:
            initial_stage = 'combine'

    # Latest exported file, served via a dedicated media route (exports may live
    # outside the static dirs; users can choose any output folder)
    export_url = None
    if not is_new and status == SessionStatus.EXPORTED:
        with db_session() as db:
            _last_exp = (db.query(Export).filter(Export.session_id == session_id)
                         .order_by(Export.exported_at.desc()).first())
            _last_exp_path = Path(_last_exp.filepath) if _last_exp else None
        if _last_exp_path and _last_exp_path.exists():
            export_url = _media_url(_last_exp_path)

    def _player_src() -> str:
        if export_url:
            return export_url
        if not is_new and preview_path.exists():
            return f'/previews/{session_id}_preview.mp4'
        p = next((cid for cid in clip_ids if (config.PROXY_DIR / f'{cid}.mp4').exists()), None)
        return f'/proxies/{p}.mp4' if p else ''

    # While proxies are still building, a half-written proxy file already exists
    # on disk — don't mount it; show the still and let _poll swap the video in.
    init_src = '' if (is_new or proxy_running) else _player_src()

    if is_new or not init_src:
        init_tag = 'Static preview of original' if (not is_new and still_path.exists()) else 'No video yet'
    elif export_url and init_src == export_url:
        init_tag = 'Exported'
    elif init_src.startswith('/previews/'):
        init_tag = 'Selected clips, combined'
    else:
        init_tag = 'Working copy'

    # ── Mutable refs ──────────────────────────────────────────────────────────
    review_mode      = [False]
    combining_lock   = [False]   # True while assemble is running → blocks re-entering review
    hdr_elapsed_ref  = [None]
    hdr_time_ref     = [None]
    next_btn_ref     = [None]
    cancel_btn_ref   = [None]
    next_action      = {'fn': None}
    menu_btn_ref     = [None]
    dot_refs:        dict[str, object] = {}
    act_refs:        dict[str, object] = {}   # stage_id → "actual time" cell
    count_refs:      dict[str, object] = {}
    player_tag_ref   = [None]
    strip_ref        = [None]
    task_bar_ref  = [None]
    row_refs:        dict[str, object] = {}   # stage_id → ui.element for class updates
    bar_refs:        dict[str, dict]   = {}
    tl_html_ref      = [None]
    cards_html_ref   = [None]
    review_panel_ref = [None]
    task_start       = [time.time()]
    _scan_started    = [False]
    _timer_ref       = [None]

    # new-session form refs
    _new_path_ref  = [None]
    _new_sport_ref = [None]
    _new_err_ref   = [None]
    _new_hint_ref  = [None]
    _new_files:    list = []

    # combine refs
    _combine_grade_val  = [_prefs['default_grade']
                           if _prefs['default_grade'] in _GRADES else 'natural']
    _combine_source_val = ['All accepted']
    _swatch_row_ref     = [None]
    _swatch_built       = [False]
    _swatch_cards:      dict[str, object] = {}
    _swatch_paths:      dict[str, Path] = {}
    grade_prev_ref      = [None]
    _tag_before_preview = [None]

    # export refs
    _export_a16_val    = [bool(_prefs['export_16_9'])]
    _export_a9_val     = [bool(_prefs['export_9_16'])]
    _export_outdir_val = [_prefs['output_dir'] or str(config.OUTPUT_DIR)]
    _export_ctl_refs:  list = []

    # ── Sidebar — starts collapsed on session pages ────────────────────────────
    _mini = [True]
    drawer = ui.left_drawer(value=True).style('background:#1a1a1a;border-right:1px solid #222')
    drawer.props('breakpoint=0 width=180 mini-width=48 mini')

    def _toggle_nav() -> None:
        _mini[0] = not _mini[0]
        if _mini[0]:
            drawer.props(add='mini')
        else:
            drawer.props(remove='mini')
        mb = menu_btn_ref[0]
        if mb:
            mb.props(f'icon={"menu" if _mini[0] else "chevron_left"}')

    with drawer:
        # Hamburger (collapsed) / chevron (expanded) lives at the top of the nav
        with ui.row().style('width:100%;justify-content:flex-end;padding:0.2rem 0.3rem;margin:0'):
            _mb = ui.button(icon='menu', on_click=_toggle_nav).props(
                'flat round dense size=sm'
            ).style('color:#666')
            menu_btn_ref[0] = _mb
        sidebar('session' if not is_new else 'home',
                *((session_id, status) if not is_new else ()))

    # ── Page shell ─────────────────────────────────────────────────────────────
    with ui.column().style('width:100%;height:100vh;background:#111;padding:0;gap:0;overflow:hidden'):

        # ── Header ────────────────────────────────────────────────────────────
        with ui.row().style(
            f'height:{_HDR_H}px;flex-shrink:0;width:100%;align-items:center;'
            'justify-content:space-between;padding:0 0.75rem;background:#141414;'
            'border-bottom:1px solid #1a1a1a'
        ):
            with ui.row().style('align-items:center;gap:0.4rem'):
                if is_new:
                    ui.label('New session').style('color:#ddd;font-size:0.88rem;font-weight:600')
                else:
                    ds = created.strftime('%Y-%m-%d %H:%M') if created else ''
                    _est = max(60, int(total_s)) + max(30, int(total_s // 3)) + 180
                    with ui.row().style('gap:0.6rem;align-items:baseline'):
                        ui.label(f'{display_name(sport)}  ·  {ds}  ·  est ~{_fmt(_est)}').style(
                            'color:#ddd;font-size:0.85rem;font-weight:600'
                        )
                        with ui.button(icon='info_outline').props(
                            'flat round dense size=xs'
                        ).style('color:#555').tooltip('What this sport profile does'):
                            with ui.menu().style('background:#1c1c1c;border:1px solid #333'):
                                ui.html(_profile_info_html(sport), sanitize=False)
                        _he = ui.label('').style('color:#5a8a9a;font-size:0.75rem')
                        hdr_elapsed_ref[0] = _he
                    _ht = ui.label('').style('color:#4a9a4a;font-size:0.72rem;margin-left:0.25rem')
                    hdr_time_ref[0] = _ht

            if is_new:
                ui.button('← Home', on_click=lambda: ui.navigate.to('/')).props('flat size=sm').style('color:#777')
            else:
                _delete_session_button(session_id)

        # ── Body ──────────────────────────────────────────────────────────────
        with ui.row().style(
            f'width:100%;height:calc(100vh - {_HDR_H}px);gap:0;overflow:hidden;flex-shrink:0'
        ):

            # ── Stage table ────────────────────────────────────────────────────
            with ui.element('div').classes('ax2-table'):

                # Column header
                with ui.element('div').classes('ax2-col-hdr'):
                    ui.html('<span>Stage</span><span>Est</span><span>Act</span><span>N</span>',
                            sanitize=False)

                # helper: build one sub-row
                def _sub_row(stage_id: str, label: str, est: str, actual: str, count_str: str):
                    st = _stage_st(stage_id)
                    css = f'ax2-sub {st}'
                    with ui.element('div').classes(css) as _row:
                        row_refs[stage_id] = _row
                        _d = ui.html(_dot_html(st), sanitize=False, tag='span')
                        dot_refs[stage_id] = _d
                        ui.label(label).classes('ax2-sub-name')
                        ui.label(est).classes('ax2-sub-est')
                        _a = ui.label(actual).classes('ax2-sub-act')
                        act_refs[stage_id] = _a
                        _c = ui.label(count_str).classes('ax2-sub-count')
                        count_refs[stage_id] = _c

                # ── Select video ───────────────────────────────────────────────
                _in_st = _stage_st('input')
                _in_css = f'ax2-section {_in_st}'
                with ui.element('div').classes(_in_css) as _row_input:
                    row_refs['input'] = _row_input
                    _in_dot = ui.html(_dot_html(_in_st), sanitize=False, tag='span')
                    dot_refs['input'] = _in_dot
                    ui.label('Select video').style('flex:1')
                    ui.label('').classes('ax2-sec-est')
                    ui.label('').classes('ax2-sec-act')
                    _in_c = ui.label(str(len(clip_ids)) if clip_ids else '').classes('ax2-sec-count')
                    count_refs['input'] = _in_c

                # ── Trim video header ──────────────────────────────────────────
                _trim_done = status in (SessionStatus.ASSEMBLED, SessionStatus.EXPORTED) if not is_new else False
                _trim_active = initial_stage in ('proxy', 'scan', 'highlights', 'pick', 'combine')
                _trim_css = 'ax2-section ' + ('done' if _trim_done else 'active' if _trim_active else '')
                with ui.element('div').classes(_trim_css):
                    ui.label('').style('width:9px;flex-shrink:0')
                    ui.label('Trim video').style('flex:1;color:inherit')

                # Sub-rows under Trim video
                # Time column always shows the estimate; "est→actual" once known.
                _est_str = {
                    'proxy':      f'~{_fmt(max(60, int(total_s)))}' if total_s else '~2m',
                    'scan':       f'~{_fmt(max(30, int(total_s // 3)))}' if total_s else '~1m',
                    'highlights': 'auto',
                    'pick':       '',
                    'combine':    '~1m',
                    'export':     '~2m',
                }
                _TASK_KEYS = {
                    'proxy':      f'{session_id}_proxy',
                    'scan':       f'{session_id}_scan',
                    'highlights': f'{session_id}_highlights',
                    'combine':    f'assemble_{session_id}',
                    'export':     f'export_{session_id}',
                }

                def _init_act(stage: str) -> str:
                    t = state.get_task(_TASK_KEYS[stage]) if not is_new else None
                    return _fmt(t.elapsed) if t and t.elapsed is not None else ''

                _n_prox_done = sum(
                    1 for cid in clip_ids if (config.PROXY_DIR / f'{cid}.mp4').exists()
                )
                _sub_row('proxy', 'Create working copy', _est_str['proxy'], _init_act('proxy'),
                         f'{_n_prox_done}/{len(clip_ids)}' if clip_ids and not all_proxies_done
                         else (str(len(clip_ids)) if clip_ids else ''))

                _sub_row('scan', 'Detect scenes', _est_str['scan'], _init_act('scan'),
                         str(len(clip_ids)) if has_motion_data else '')

                _n_in   = sum(1 for s in _statuses.values() if s == 'in')
                _n_out  = sum(1 for s in _statuses.values() if s == 'out')
                _n_skip = sum(1 for s in _statuses.values() if s == 'skip')
                _n_dull = sum(1 for s in _statuses.values() if s == 'dull')
                _n_found = len(mark_data) - len(boring_ids) - len(dull_ids)

                _sub_row('highlights', 'Find clips', _est_str['highlights'], _init_act('highlights'),
                         str(_n_found) if mark_data else '')

                _pick_count = f'{_n_in}·{_n_out}'
                if boring_ids: _pick_count += f'·{_n_skip}'
                if dull_ids:   _pick_count += f'·{_n_dull}'
                _sub_row('pick', 'Select clips',
                         '', '',
                         _pick_count if mark_data else '')

                _sub_row('combine', 'Combine clips', _est_str['combine'], _init_act('combine'), '')

                # ── Future steps ───────────────────────────────────────────────
                with ui.element('div').classes('ax2-section future'):
                    ui.label('').style('width:9px;flex-shrink:0')
                    ui.label('Add text').style('flex:1')

                with ui.element('div').classes('ax2-section future'):
                    ui.label('').style('width:9px;flex-shrink:0')
                    ui.label('Add music').style('flex:1')

                # ── Export section row ─────────────────────────────────────────
                _ex_st = _stage_st('export')
                _ex_css = f'ax2-section {_ex_st}'
                with ui.element('div').classes(_ex_css) as _row_export:
                    row_refs['export'] = _row_export
                    _ex_dot = ui.html(_dot_html(_ex_st), sanitize=False, tag='span')
                    dot_refs['export'] = _ex_dot
                    ui.label('Export video').style('flex:1')
                    ui.label(_est_str['export']).classes('ax2-sec-est')
                    _ex_a = ui.label(_init_act('export')).classes('ax2-sec-act')
                    act_refs['export'] = _ex_a
                    _ex_c = ui.label('').classes('ax2-sec-count')
                    count_refs['export'] = _ex_c

                # Spacer
                with ui.element('div').style('flex:1'):
                    pass

            # ── Player column ──────────────────────────────────────────────────
            with ui.element('div').classes('ax2-player-col'):

                # ── Action bar — step controls + next button, above the player ─
                with ui.element('div').classes('ax2-action-bar'):

                    if is_new:
                        from avs.ui.components.drop_zone import new_session_controls
                        _dz = new_session_controls(
                            sports=sports,
                            default_sport=(_prefs['default_sport']
                                           if _prefs['default_sport'] in sports
                                           else (sports[0] if sports else 'unknown')),
                            profile_info_html_fn=_profile_info_html,
                        )
                        _new_path_ref[0]  = _dz['path_ref'][0]
                        _new_sport_ref[0] = _dz['sport_ref'][0]
                        _new_files        = _dz['files']
                        _new_hint_ref[0]  = _dz['hint_ref'][0]
                        _new_err_ref[0]   = _dz['err_ref'][0]
                        next_action['fn'] = None  # will be set by _do_start wiring below

                    else:
                        # Status label + per-step controls (shown per active stage)
                        _ab_status = ui.label('').style('flex:1;color:#666;font-size:0.78rem')

                        _method_sel = ui.select(
                            options={'jpg': 'Quick (1fps)', 'proxy': 'Full (all frames)'},
                            value=detect_method_ref[0],
                        ).style('min-width:140px').props('dense outlined')
                        _method_sel.on_value_change(lambda e: detect_method_ref.__setitem__(0, e.value))
                        _method_sel_ref = [_method_sel]

                        _grade_sel = ui.select(
                            options=_GRADES, value=_combine_grade_val[0], label='Grade',
                        ).style('min-width:110px').props('dense outlined')
                        _grade_sel.on_value_change(
                            lambda e: (_combine_grade_val.__setitem__(0, e.value),
                                       _highlight_swatch(e.value),
                                       _show_grade_preview(e.value))
                        )
                        _grade_sel_ref = [_grade_sel]

                        # Export controls — inline, shown only on the Export stage
                        _ea16 = ui.checkbox('16:9', value=_export_a16_val[0]).props('dense')
                        _ea16.on_value_change(lambda e: _export_a16_val.__setitem__(0, e.value))
                        _ea9 = ui.checkbox('9:16', value=_export_a9_val[0]).props('dense')
                        _ea9.on_value_change(lambda e: _export_a9_val.__setitem__(0, e.value))
                        _eodir = ui.input(label='Output folder', value=_export_outdir_val[0]).style(
                            'min-width:260px'
                        ).props('dense outlined')
                        _eodir.on_value_change(lambda e: _export_outdir_val.__setitem__(0, e.value))
                        _export_ctl_refs.extend([_ea16, _ea9, _eodir])

                    # Cancel button — visible only while a stage is running
                    if not is_new:
                        def _do_cancel():
                            from avs.engine import pipeline as engine
                            engine.cancel_current(session_id)
                        _cbtn = ui.button('Cancel', on_click=_do_cancel).props(
                            'color=negative flat size=sm'
                        )
                        _cbtn.set_visibility(False)
                        cancel_btn_ref[0] = _cbtn

                    # Next-action button (rightmost — top right of the pane)
                    _nbtn = ui.button(
                        'Import & build working copy →' if is_new else '…',
                        on_click=lambda: _handle_next_click(),
                    ).props('color=positive size=sm')
                    if not is_new:
                        _nbtn.set_enabled(False)
                    next_btn_ref[0] = _nbtn

                # ── Grade swatch strip — shown at the Combine stage, built lazily ─
                if not is_new:
                    _sw_row = ui.row().style(
                        'flex-shrink:0;gap:0.55rem;padding:0.45rem 0.9rem;align-items:flex-start;'
                        'background:#0f0f0f;border-bottom:1px solid #1a1a1a;flex-wrap:nowrap;'
                        'overflow-x:auto'
                    )
                    _swatch_row_ref[0] = _sw_row
                    _sw_row.set_visibility(False)

                # ── Progress strip — above player. Per-clip proxy/scan bars at
                #    page load; combine bar filled dynamically by its watcher. ──
                if not is_new:
                    _bg_running = proxy_running or scan_running or highlights_running
                    _strip = ui.element('div').style(
                        'flex-shrink:0;background:#0d0d0d;border-bottom:1px solid #1a1a1a;'
                        'padding:0.6rem 1rem 0.2rem'
                    )
                    strip_ref[0] = _strip
                    with _strip:
                        if _bg_running:
                            prog = state.get_clip_progress(session_id)
                            for cid, fname, _ in clip_info:
                                bar_refs.setdefault(cid, {})
                                cp = prog.get(cid, {})
                                stages = _PROXY_STAGES if proxy_running else _SCAN_STAGES
                                for stage in stages:
                                    s  = cp.get(stage, StageState())
                                    el = ui.html(_bar_html(s, _STAGE_LABEL[stage], stage, detect_method_ref[0]),
                                                 sanitize=False)
                                    bar_refs[cid][stage] = el
                        _cb = ui.html('', sanitize=False)
                        task_bar_ref[0] = _cb
                    if not _bg_running:
                        _strip.set_visibility(False)

                # ── Player frame: label strip + video area ─────────────────────
                with ui.element('div').classes('ax2-player-frame'):
                    _ptag = ui.label(init_tag).classes('ax2-player-tag')
                    player_tag_ref[0] = _ptag

                    with ui.element('div').classes('ax2-player-main'):

                        if is_new:
                            from avs.ui.components.drop_zone import drop_zone_placeholder
                            drop_zone_placeholder()

                        elif init_src:
                            ui.html(
                                f'<video id="main-player" src="{init_src}" controls preload="metadata"'
                                ' style="position:absolute;top:0;left:0;width:100%;height:100%;'
                                'object-fit:contain;display:block;background:#000"></video>',
                                sanitize=False,
                            )
                        elif still_path.exists():
                            ui.html(
                                f'<img id="player-still" src="/stills/{session_id}_still.jpg"'
                                ' style="position:absolute;top:0;left:0;width:100%;height:100%;object-fit:contain;">'
                                '<video id="main-player" src="" controls preload="none"'
                                ' style="position:absolute;top:0;left:0;width:100%;height:100%;'
                                'object-fit:contain;display:none;background:#000"></video>',
                                sanitize=False,
                            )
                        else:
                            ui.html(
                                '<div id="player-ph" style="position:absolute;inset:0;display:flex;'
                                'flex-direction:column;align-items:center;justify-content:center;'
                                'gap:0.5rem;background:#000">'
                                '<span style="color:#3e3e3e;font-size:2.5rem">▷</span>'
                                '<span style="color:#484848;font-size:0.82rem">Building working copy…</span></div>'
                                '<video id="main-player" src="" controls preload="none"'
                                ' style="position:absolute;top:0;left:0;width:100%;height:100%;'
                                'object-fit:contain;display:none;background:#000"></video>',
                                sanitize=False,
                            )

                        # Full-size grade preview overlay — shown when a swatch
                        # is selected; click to return to the video
                        if not is_new:
                            _gp = ui.image('').props('fit=contain').style(
                                'position:absolute;top:0;left:0;width:100%;height:100%;'
                                'background:#000;z-index:6;cursor:pointer'
                            ).tooltip('Click to return to the video')
                            _gp.on('click', lambda: _hide_grade_preview())
                            _gp.set_visibility(False)
                            grade_prev_ref[0] = _gp

                # ── Review panel ───────────────────────────────────────────────
                with ui.element('div').classes('ax2-review-panel') as _review_panel:
                    review_panel_ref[0] = _review_panel
                    _tl = ui.html(
                        _timeline_html(mark_data, clip_info, _statuses) if mark_data else '',
                        sanitize=False,
                    ).style('width:100%;height:68px;flex-shrink:0;display:block;'
                            'padding:4px 6px;box-sizing:border-box')
                    tl_html_ref[0] = _tl
                    with ui.element('div').style('flex:1;min-height:0;overflow-y:auto;'
                                                 'padding:0.4rem 0.5rem'):
                        _ca = ui.html('', sanitize=False)
                        cards_html_ref[0] = _ca

    # ── Wire new-session start ─────────────────────────────────────────────────
    if is_new:
        async def _do_start() -> None:
            pi = _new_path_ref[0]; ss = _new_sport_ref[0]; er = _new_err_ref[0]
            if not pi or not pi.value.strip():
                if er: er.set_text('Enter a path or use Browse')
                return
            src_p = Path(pi.value.strip())
            if not src_p.exists():
                if er: er.set_text('Path not found')
                return
            if er: er.set_text('')
            nb = next_btn_ref[0]
            if nb: nb.set_enabled(False); nb.set_text('Importing…')
            files_to_import = _new_files[:] if _new_files else None
            try:
                from avs.engine import pipeline as engine
                from nicegui import run as ng_run
                session_obj = await ng_run.io_bound(
                    engine.ingest_session, src_p, ss.value if ss else 'unknown', files_to_import
                )
            except Exception as exc:
                if nb: nb.set_enabled(True); nb.set_text('Import & build working copy →')
                if er: er.set_text(str(exc))
                return
            sid = session_obj.id
            state.start_task(f'{sid}_proxy')

            def _on_proxy_progress(clip_id, stage, evt_status, message, completed, total):
                if clip_id is None: return
                if evt_status in ('running', 'done', 'skipped'):
                    state.update_clip_stage(sid, clip_id, stage, evt_status)
                elif evt_status == 'progress' and completed is not None and total:
                    pct = int(completed * 100 / total)
                    state.update_clip_stage(sid, clip_id, stage, 'running',
                                            pct=pct, completed=completed, total=total, message=message)

            engine.run_proxy(
                sid,
                on_progress=_on_proxy_progress,
                on_done=lambda err: state.finish_task(f'{sid}_proxy', error=err),
            )
            ui.navigate.to(f'/session/{sid}')

        next_action['fn'] = _do_start

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _handle_next_click() -> None:
        fn = next_action['fn']
        if not fn: return
        if inspect.iscoroutinefunction(fn):
            await fn()
        else:
            fn()

    def _set_next_btn(label: str, enabled: bool, fn) -> None:
        b = next_btn_ref[0]
        if not b: return
        b.set_text(label)
        b.set_enabled(enabled)
        b.props(f'color={"positive" if enabled else "grey-7"}')
        next_action['fn'] = fn

    def _set_act(stage: str, actual_s: float | None) -> None:
        """Update a stage's Act cell; Est cells are static."""
        lbl = act_refs.get(stage)
        if not lbl: return
        lbl.set_text(_fmt(actual_s) if actual_s is not None else '')

    def _set_player_tag(text: str) -> None:
        if player_tag_ref[0]:
            player_tag_ref[0].set_text(text)

    # ── Grade swatches ─────────────────────────────────────────────────────────

    def _swatch_style(selected: bool) -> str:
        bc = '#ff8c00' if selected else '#2a2a2a'
        return (f'border:2px solid {bc};border-radius:4px;overflow:hidden;cursor:pointer;'
                'flex-shrink:0;background:#161616;padding:0')

    def _highlight_swatch(grade: str) -> None:
        for g, card in _swatch_cards.items():
            card.style(replace=_swatch_style(g == grade))

    def _select_grade(grade: str) -> None:
        # set_value triggers the select's on_value_change → updates val + highlight.
        # Show the preview directly too: re-clicking the already-selected swatch
        # fires no value-change event but should still bring the preview up.
        _grade_sel_ref[0].set_value(grade)
        _show_grade_preview(grade)

    def _show_grade_preview(grade: str) -> None:
        gp = grade_prev_ref[0]
        p  = _swatch_paths.get(grade)
        if gp is None or p is None: return
        cur = player_tag_ref[0].text if player_tag_ref[0] else ''
        if not cur.startswith('Grade preview'):
            _tag_before_preview[0] = cur
        gp.set_source(f'/stills/{p.name}')
        gp.set_visibility(True)
        _set_player_tag(f'Grade preview: {grade} — click image to return to the video')
        ui.run_javascript('var v=document.getElementById("main-player"); if(v) v.pause();')

    def _hide_grade_preview() -> None:
        gp = grade_prev_ref[0]
        if gp is None: return
        gp.set_visibility(False)
        if _tag_before_preview[0] is not None:
            _set_player_tag(_tag_before_preview[0])

    async def _ensure_swatches() -> None:
        sw = _swatch_row_ref[0]
        if sw is None: return
        if _swatch_built[0]:
            sw.set_visibility(True)
            return
        src = still_path if still_path.exists() else None
        if src is None:
            for mid, cid, *_ in mark_data:
                p = config.THUMB_DIR / cid / f'mark_{mid}.jpg'
                if p.exists():
                    src = p
                    break
        if src is None:
            return
        from nicegui import run as ng_run
        from avs.processing.assembly import render_grade_swatches
        try:
            paths = await ng_run.io_bound(render_grade_swatches, src, config.STILL_DIR, session_id)
        except Exception as exc:
            ui.notify(f'Grade preview failed: {exc}', type='warning')
            return
        _swatch_built[0] = True
        _swatch_paths.update(paths)
        with sw:
            for g in _GRADES:
                p = paths.get(g)
                if not p or not p.exists():
                    continue
                card = ui.element('div').style(_swatch_style(g == _combine_grade_val[0]))
                with card:
                    ui.image(f'/stills/{p.name}').style(
                        'width:104px;height:58px;display:block;object-fit:cover'
                    )
                    ui.label(g).style(
                        'font-size:0.62rem;color:#999;text-align:center;width:100%;'
                        'padding:1px 0 2px'
                    )
                card.on('click', lambda g=g: _select_grade(g))
                _swatch_cards[g] = card
        sw.set_visibility(True)

    def _set_active_row(stage_id: str) -> None:
        """Highlight one stage-table row as active, clear all others."""
        # Sub-row stages
        sub_stages = ('proxy', 'scan', 'highlights', 'pick', 'combine')
        sec_stages = ('input', 'export')
        for sid, el in row_refs.items():
            if sid in sub_stages:
                base = f'ax2-sub {_stage_st(sid)}'
                el.classes(replace=base + (' active' if sid == stage_id else ''))
            elif sid in sec_stages:
                st = _stage_st(sid)
                base = f'ax2-section {st}'
                el.classes(replace=base + (' active' if sid == stage_id else ''))

    def _update_action_bar_for_stage(stage: str) -> None:
        if is_new: return
        _set_active_row(stage)
        # Cancel button: visible whenever a background stage is actively running
        _stage_running = (
            (stage == 'proxy' and not all_proxies_done) or
            (stage == 'scan' and (_scan_started[0] or scan_running)) or
            (stage == 'highlights' and not post_analysis) or
            (stage == 'combine' and combining_lock[0]) or
            (stage == 'export' and (lambda t: t is not None and not t.done)(
                state.get_task(f'export_{session_id}')))
        )
        if cancel_btn_ref[0]:
            cancel_btn_ref[0].set_visibility(_stage_running)
        # Show/hide optional controls
        _method_sel_ref[0].set_visibility(
            stage == 'scan' and not (scan_running or _scan_started[0])
        )
        _grade_sel_ref[0].set_visibility(stage == 'combine' and not combining_lock[0])
        _etask = state.get_task(f'export_{session_id}')
        _exporting = _etask is not None and not _etask.done
        for _c in _export_ctl_refs:
            _c.set_visibility(stage == 'export' and not _exporting)
        # Grade swatch strip — visible at Combine; rendered lazily on first show
        if _swatch_row_ref[0]:
            if stage == 'combine' and not combining_lock[0]:
                ui.timer(0.05, _ensure_swatches, once=True)
            else:
                _swatch_row_ref[0].set_visibility(False)
                _hide_grade_preview()

        if stage == 'input':
            _set_next_btn('Working copy ready →' if clip_ids else '(load footage first)', bool(clip_ids), None)
            _ab_status.set_text(f'{len(clip_ids)} clip(s) · {_fmt(int(total_s))}' if clip_ids else '')
        elif stage == 'proxy':
            if all_proxies_done:
                _set_next_btn('Start scan →', True, _start_scan)
            else:
                _set_next_btn('Building working copy…', False, None)
            _ab_status.set_text('')
        elif stage == 'scan':
            if _scan_started[0] or scan_running:
                _set_next_btn('Detecting scenes…', False, None)
            else:
                _set_next_btn('Start scan →', all_proxies_done, _start_scan)
            _ab_status.set_text(f'Method: {"Quick" if detect_method_ref[0]=="jpg" else "Full"}')
        elif stage == 'highlights':
            if post_analysis and mark_data:
                _set_next_btn('Review clips →', True, _enter_review)
            else:
                _set_next_btn('Finding clips…', False, None)
            _ab_status.set_text(f'{len(mark_data)} clips found' if mark_data else '')
        elif stage == 'pick':
            if review_mode[0]:
                n_in2   = sum(1 for s in _statuses.values() if s == 'in')
                n_out2  = sum(1 for s in _statuses.values() if s == 'out')
                n_skip2 = sum(1 for s in _statuses.values() if s == 'skip')
                n_dull2 = sum(1 for s in _statuses.values() if s == 'dull')
                _set_next_btn('Save & combine clips →', bool(mark_data), _save_and_combine)
                _ab_status.set_text(f'{n_in2} in · {n_out2} out'
                                    + (f' · {n_skip2} skipped' if boring_ids else '')
                                    + (f' · {n_dull2} dull' if dull_ids else ''))
            else:
                can_review = post_analysis and bool(mark_data) and not combining_lock[0]
                _set_next_btn('Review clips →', can_review, _enter_review)
                _ab_status.set_text('')
        elif stage == 'combine':
            assemble_task = state.get_task(f'assemble_{session_id}')
            if assemble_task and not assemble_task.done:
                _set_next_btn('Combining…', False, None)
            elif preview_path.exists():
                _set_next_btn('Continue to export →', True, lambda: _update_action_bar_for_stage('export'))
            else:
                _set_next_btn('Combine clips →', bool(mark_data), _run_combine)
            _ab_status.set_text(f'Grade: {_combine_grade_val[0]}')
        elif stage == 'export':
            export_task = state.get_task(f'export_{session_id}')
            if export_task and not export_task.done:
                _set_next_btn('Exporting…', False, None)
            else:
                _set_next_btn('Export →', True, _do_export_start)
            _ab_status.set_text('')

    # ── REVIEW mode ────────────────────────────────────────────────────────────

    def _enter_review() -> None:
        if combining_lock[0]:
            ui.notify('Wait for combine to finish before reviewing again', type='warning')
            return
        review_mode[0] = True
        _set_player_tag('Working copy')   # review plays from proxies
        ui.run_javascript("document.querySelector('.ax2-table').classList.add('ax2-review')")
        rp = review_panel_ref[0]
        if rp: rp.classes(add='visible')
        if tl_html_ref[0]:
            tl_html_ref[0].set_content(_timeline_html(mark_data, clip_info, _statuses) if mark_data else '')
        if cards_html_ref[0]:
            cards_html_ref[0].set_content(_build_cards_html())
        _update_action_bar_for_stage('pick')
        _init_pick_js()

    def _exit_review() -> None:
        review_mode[0] = False
        ui.run_javascript("document.querySelector('.ax2-table').classList.remove('ax2-review')")
        rp = review_panel_ref[0]
        if rp: rp.classes(remove='visible')
        _update_action_bar_for_stage('pick')

    def _build_cards_html() -> str:
        parts = ['<div style="display:flex;flex-wrap:wrap;gap:0.4rem">']
        for mid, cid, in_s, out_s, score, source in mark_data:
            thumb = config.THUMB_DIR / cid / f'mark_{mid}.jpg'
            img_part = (
                f'<img src="/thumbs/{cid}/mark_{mid}.jpg" style="width:100%;height:60px;object-fit:cover;display:block">'
                if thumb.exists() else
                '<div style="width:100%;height:60px;background:#111"></div>'
            )
            ts_label = f'{_tsfmt(in_s)}–{_tsfmt(out_s)}'
            st = _statuses.get(mid, 'in')
            bc, _, bi = _PICK_STYLE[st]
            spikes = _audio_spikes.get(cid, [])
            has_audio = (source == 'audio_spike' or
                         any(in_s <= t <= out_s for t in spikes))
            hint = (' title="Flagged boring — click to include"' if st == 'skip' else
                    ' title="Dull (unclassified) — click to include"' if st == 'dull' else
                    ' title="Found by audio"' if has_audio else '')
            mic = ('<span class="material-icons" style="font-size:0.72rem;color:#6a9ab8;'
                   'vertical-align:text-bottom;margin-left:2px">mic</span>'
                   if has_audio else '')
            parts.append(
                f'<div id="card-{mid}" onclick="avsCardClick(\'{mid}\',\'{cid}\',{in_s})"{hint} '
                f'style="width:110px;background:#1a1a1a;border-radius:4px;overflow:hidden;'
                f'cursor:pointer;border:2px solid {bc};flex-shrink:0;position:relative">'
                f'{img_part}'
                f'<div id="card-badge-{mid}" style="position:absolute;top:3px;right:3px;'
                f'width:16px;height:16px;border-radius:50%;background:{bc};'
                f'display:flex;align-items:center;justify-content:center;'
                f'font-size:0.5rem;color:#fff;font-weight:bold;pointer-events:none">{bi}</div>'
                f'<div style="padding:0.2rem 0.35rem">'
                f'<div style="color:#888;font-size:0.62rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{ts_label}{mic}</div>'
                f'<div style="color:#555;font-size:0.58rem">{score:.2f}</div>'
                f'</div></div>'
            )
        parts.append('</div>')
        return ''.join(parts)

    def _init_pick_js() -> None:
        # Decisions are 'in' | 'out' | 'skip' | 'dull'. System-flagged marks
        # cycle back to their origin state (never red); normal marks cycle in↔out.
        boring_origin = {mid: True for mid, _, _, _, _, src in mark_data
                         if src == 'boring_motion'}
        dull_origin = {mid: True for mid, _, _, _, _, src in mark_data
                       if src == 'dull_gap'}
        pick_count_id = f'c{count_refs["pick"].id}' if 'pick' in count_refs else ''
        styles_js = json.dumps({st: {'c': c, 'img': img, 'icon': icon}
                                for st, (c, img, icon) in _PICK_STYLE.items()})
        ui.run_javascript(f'''
window.avs_decisions = {json.dumps(_statuses)};
window.avs_boring = {json.dumps(boring_origin)};
window.avs_dull = {json.dumps(dull_origin)};
var _AX_STYLES = {styles_js};

function _avsSet(mid, st) {{
  window.avs_decisions[mid] = st;
  var s = _AX_STYLES[st];
  var card = document.getElementById("card-" + mid);
  if (card) card.style.borderColor = s.c;
  var badge = document.getElementById("card-badge-" + mid);
  if (badge) {{ badge.style.background = s.c; badge.textContent = s.icon; }}
  var bar = document.getElementById("mark-" + mid);
  if (bar) {{
    bar.style.background = s.c;
    bar.style.backgroundImage = s.img;
    var ico = bar.querySelector("span.mark-icon");
    if (ico) ico.textContent = s.icon;
  }}
  var n = {{'in': 0, 'out': 0, 'skip': 0, 'dull': 0}};
  Object.values(window.avs_decisions).forEach(function(v) {{ n[v] += 1; }});
  var txt = n['in'] + "\\u00b7" + n['out'];
  if (Object.keys(window.avs_boring).length > 0) txt += "\\u00b7" + n['skip'];
  if (Object.keys(window.avs_dull).length > 0)   txt += "\\u00b7" + n['dull'];
  var el = document.getElementById("{pick_count_id}");
  if (el) el.textContent = txt;
}}

function _avsCycle(mid) {{
  var cur = window.avs_decisions[mid];
  var next;
  if (window.avs_dull[mid])        next = (cur === "dull" ? "in" : "dull");
  else if (window.avs_boring[mid]) next = (cur === "skip" ? "in" : "skip");
  else                             next = (cur === "in" ? "out" : "in");
  _avsSet(mid, next);
}}

function _avsSeek(cid, ins) {{
  var v = document.getElementById("main-player");
  if (!v) return;
  v.style.display = "block";
  var st = document.getElementById("player-still");
  if (st) st.style.display = "none";
  var ph = document.getElementById("player-ph");
  if (ph) ph.style.display = "none";
  var url = "/proxies/" + cid + ".mp4";
  var sameSrc = v.src && v.src.indexOf(url) !== -1;
  if (!sameSrc) {{ v.src = url; v.load(); }}
  // play() must run synchronously inside the click gesture — WebKitGTK blocks
  // unmuted play() issued later from loadedmetadata (gesture context is gone).
  var p = v.play();
  if (p && p.catch) p.catch(function() {{ v.muted = true; v.play().catch(function(){{}}); }});
  var seekTo = function() {{ try {{ v.currentTime = ins; }} catch (e) {{}} }};
  if (sameSrc && v.readyState >= 1) seekTo();
  else v.addEventListener("loadedmetadata", seekTo, {{once: true}});
}}

window.avsMarkClick = function(el) {{
  var mid = el.dataset.mid, cid = el.dataset.cid, ins = parseFloat(el.dataset.ins);
  _avsCycle(mid);
  _avsSeek(cid, ins);
}};

window.avsCardClick = function(mid, cid, ins) {{
  _avsCycle(mid);
  _avsSeek(cid, ins);
}};
''')

    # ── Action handlers ────────────────────────────────────────────────────────

    def _start_scan() -> None:
        from avs.engine import pipeline as engine
        method = detect_method_ref[0]
        _pending_methods[session_id] = method
        state.start_task(f'{session_id}_scan')
        task_start[0] = time.time()

        def _on_progress(clip_id, stage, evt_status, message, completed, total):
            if clip_id is None: return
            if evt_status in ('running', 'done', 'skipped'):
                state.update_clip_stage(session_id, clip_id, stage, evt_status)
            elif evt_status == 'progress' and completed is not None and total:
                pct = int(completed * 100 / total)
                state.update_clip_stage(session_id, clip_id, stage, 'running',
                                        pct=pct, completed=completed, total=total, message=message)

        def _on_thumbnails_done(err):
            state.finish_task(f'{session_id}_thumbnails', error=err)
            if cancel_btn_ref[0]:
                cancel_btn_ref[0].set_visibility(False)

        def _on_peaks_done(err):
            state.finish_task(f'{session_id}_highlights', error=err)
            if err:
                if err != 'cancelled':
                    ui.notify(f'Peak detection failed: {err}', type='negative', timeout=0)
                if cancel_btn_ref[0]:
                    cancel_btn_ref[0].set_visibility(False)
                return
            with db_session() as _db:
                _s = _db.query(Session).filter(Session.id == session_id).first()
                if _s: _s.status = SessionStatus.READY
            state.start_task(f'{session_id}_thumbnails')
            engine.run_thumbnails(session_id, on_progress=_on_progress, on_done=_on_thumbnails_done)

        def _on_scan_done(err):
            state.finish_task(f'{session_id}_scan', error=err)
            if err:
                if err != 'cancelled':
                    ui.notify(f'Scan failed: {err}', type='negative', timeout=0)
                _scan_started[0] = False
                if cancel_btn_ref[0]:
                    cancel_btn_ref[0].set_visibility(False)
                _update_action_bar_for_stage('scan')
                return
            state.start_task(f'{session_id}_highlights')
            engine.run_peaks(session_id, method, on_progress=_on_progress, on_done=_on_peaks_done)

        engine.run_scan(session_id, method, on_progress=_on_progress, on_done=_on_scan_done)
        _scan_started[0] = True
        # Create stage bars if the page loaded before the scan started (bar_refs empty)
        if strip_ref[0] and not bar_refs:
            with strip_ref[0]:
                for cid, fname, _ in clip_info:
                    bar_refs.setdefault(cid, {})
                    for stage in _SCAN_STAGES:
                        el = ui.html(_bar_html(StageState(), _STAGE_LABEL[stage], stage, method),
                                     sanitize=False)
                        bar_refs[cid][stage] = el
            strip_ref[0].set_visibility(True)
        if _timer_ref[0] is not None:
            _timer_ref[0].active = True
        _update_action_bar_for_stage('scan')
        if 'scan' in dot_refs: dot_refs['scan'].set_content(_dot_html('running'))
        _set_act('scan', None)

    async def _save_and_combine() -> None:
        raw = await ui.run_javascript('JSON.stringify(window.avs_decisions || {})')
        js_dec = json.loads(raw)
        _to_status = {'in': MarkStatus.ACCEPTED, 'out': MarkStatus.REJECTED,
                      'skip': MarkStatus.BORING, 'dull': MarkStatus.DULL}
        counts = {'in': 0, 'out': 0, 'skip': 0, 'dull': 0}
        with db_session() as db2:
            for mid2, st in js_dec.items():
                m2 = db2.query(Mark).filter(Mark.id == mid2).first()
                if m2 and st in _to_status:
                    m2.status = _to_status[st]
                    counts[st] += 1
        _statuses.update({m: s for m, s in js_dec.items() if s in _to_status})
        msg = f'Saved: {counts["in"]} in, {counts["out"]} out'
        if counts['skip']:
            msg += f', {counts["skip"]} skipped'
        if counts['dull']:
            msg += f', {counts["dull"]} dull'
        ui.notify(msg, type='positive')
        _exit_review()
        _update_action_bar_for_stage('combine')

    def _run_combine() -> None:
        _src_map = {'All accepted': None, 'Still-frame picks': 'jpg', 'Motion picks': 'proxy'}
        grade   = _combine_grade_val[0]
        src_val = _src_map.get(_combine_source_val[0])
        combining_lock[0] = True
        key = f'assemble_{session_id}'
        state.start_task(key)

        def _on_combine_progress(done: int, total: int) -> None:
            # Shared state, not page refs — survives navigating away and back
            state.update_task_progress(key,
                                       pct=int(done / total * 100) if total else None,
                                       message=f'{done} of {total} segments' if total else None)

        from avs.engine import pipeline as engine
        engine.run_assemble(
            session_id,
            grade=grade, source_filter=src_val,
            remove_mark_ids=[], swap_music=False, disable_overlay=False,
            on_progress=_on_combine_progress,
            on_done=lambda err: state.finish_task(key, error=err),
        )

        _update_action_bar_for_stage('combine')
        if 'combine' in dot_refs: dot_refs['combine'].set_content(_dot_html('running'))
        _watch_combine()

    def _watch_combine() -> None:
        """Poll the assemble task — called at start and re-attached on page load."""
        key = f'assemble_{session_id}'

        def _cpoll():
            t = state.get_task(key)
            if not t: return
            elapsed_s = t.elapsed or 0.0
            elapsed   = _fmt(elapsed_s)
            if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'combining: {elapsed}')
            if t.error:
                combining_lock[0] = False
                ui.notify(f'Combine error: {t.error}', type='negative', timeout=0)
                _set_next_btn('Combine clips →', True, _run_combine)
                if 'combine' in count_refs: count_refs['combine'].set_text('error')
                _set_act('combine', None)
                if 'combine' in dot_refs:   dot_refs['combine'].set_content(_dot_html('pending'))
                if task_bar_ref[0]: task_bar_ref[0].set_content('')
                if strip_ref[0]: strip_ref[0].set_visibility(False)
                _ct.active = False; return
            if t.done:
                combining_lock[0] = False
                if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'combined: {elapsed}')
                if 'combine' in dot_refs:  dot_refs['combine'].set_content(_dot_html('done'))
                _set_act('combine', elapsed_s)
                if 'combine' in count_refs: count_refs['combine'].set_text('done')
                _ct.active = False
                _update_action_bar_for_stage('combine')
                ui.navigate.to(f'/session/{session_id}')
            else:
                pct_str = f'{t.pct}%' if t.pct is not None else '…'
                if 'combine' in count_refs: count_refs['combine'].set_text(pct_str)
                _set_act('combine', elapsed_s)
                if task_bar_ref[0]:
                    task_bar_ref[0].set_content(_bar_html(
                        StageState(status='running', pct=t.pct, message=t.message),
                        'Combining clips', 'combine',
                    ))
                if strip_ref[0]: strip_ref[0].set_visibility(True)
        _ct = ui.timer(2.0, _cpoll)

    def _do_export_start() -> None:
        aspects = []
        if _export_a16_val[0]: aspects.append('16:9')
        if _export_a9_val[0]:  aspects.append('9:16')
        if not aspects:
            ui.notify('Select at least one aspect ratio', type='warning'); return
        out_dir = _export_outdir_val[0].strip() or None
        key = f'export_{session_id}'
        state.start_task(key)
        _update_action_bar_for_stage('export')

        def _on_progress(aspect: str, pct: int) -> None:
            # Shared state, not page refs — survives navigating away and back
            state.update_task_progress(key, pct=pct, message=aspect)

        from avs.engine import pipeline as engine
        engine.run_export(
            session_id,
            aspects=aspects,
            output_dir=Path(out_dir) if out_dir else None,
            on_progress=_on_progress,
            on_done=lambda err: state.finish_task(key, error=err),
        )
        if 'export' in dot_refs: dot_refs['export'].set_content(_dot_html('running'))
        _watch_export()

    def _watch_export() -> None:
        """Poll the export task — called at start and re-attached on page load."""
        key = f'export_{session_id}'

        def _epoll():
            t = state.get_task(key)
            if not t: return
            elapsed_s = t.elapsed or 0.0
            elapsed   = _fmt(elapsed_s)
            pct = t.pct or 0
            asp = t.message or ''
            if t.error:
                ui.notify(f'Export error: {t.error}', type='negative', timeout=0)
                if hdr_time_ref[0]: hdr_time_ref[0].set_text('')
                if 'export' in dot_refs:  dot_refs['export'].set_content(_dot_html('active'))
                _set_act('export', None)
                if task_bar_ref[0]: task_bar_ref[0].set_content('')
                if strip_ref[0]: strip_ref[0].set_visibility(False)
                _update_action_bar_for_stage('export')
                _et.active = False; return
            if t.done:
                if hdr_time_ref[0]:  hdr_time_ref[0].set_text(f'exported: {elapsed}')
                if 'export' in dot_refs:  dot_refs['export'].set_content(_dot_html('done'))
                _set_act('export', elapsed_s)
                if 'export' in count_refs: count_refs['export'].set_text('done')
                _elapsed_timer.active = False
                _et.active = False
                # Reload so the exported video is mounted in the player
                ui.navigate.to(f'/session/{session_id}')
            else:
                if hdr_time_ref[0]:
                    hdr_time_ref[0].set_text(f'exporting {asp}: {pct}% · {elapsed}')
                _set_act('export', elapsed_s)
                if 'export' in count_refs: count_refs['export'].set_text(f'{pct}%')
                if task_bar_ref[0]:
                    task_bar_ref[0].set_content(_bar_html(
                        StageState(status='running', pct=pct),
                        f'Exporting {asp}' if asp else 'Exporting', 'export',
                    ))
                if strip_ref[0]: strip_ref[0].set_visibility(True)
        _et = ui.timer(1.0, _epoll)

    # ── Initial render ─────────────────────────────────────────────────────────
    if not is_new:
        _update_action_bar_for_stage(initial_stage)
        if post_analysis and mark_data and tl_html_ref[0]:
            tl_html_ref[0].set_content(_timeline_html(mark_data, clip_info, _statuses))

    # ── Elapsed timer ──────────────────────────────────────────────────────────
    def _elapsed_tick() -> None:
        import datetime
        if not created: return
        elapsed_s = max(0, int((datetime.datetime.utcnow() - created).total_seconds()))
        if hdr_elapsed_ref[0]:
            hdr_elapsed_ref[0].set_text(f'elapsed time: {_fmt(elapsed_s)}')

    _elapsed_timer = ui.timer(1.0, _elapsed_tick, active=not is_new)

    # ── Re-attach watchers for combine/export still running from a previous
    #    page view (user navigated away and back) ──────────────────────────────
    if not is_new:
        _t_asm1 = state.get_task(f'assemble_{session_id}')
        if _t_asm1 and not _t_asm1.done:
            combining_lock[0] = True
            _watch_combine()
        _t_exp1 = state.get_task(f'export_{session_id}')
        if _t_exp1 and not _t_exp1.done:
            _watch_export()

    # ── Background task poll ───────────────────────────────────────────────────
    if is_new:
        return

    _any_bg      = proxy_running or scan_running or highlights_running
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

        def _t_elapsed(t) -> float:
            # Task's own clock survives the page reloads between stages
            return t.elapsed if t and t.elapsed is not None else (time.time() - task_start[0])

        def _n_stage_done(stage: str) -> int:
            return sum(1 for cid in clip_ids
                       if prog.get(cid, {}).get(stage, StageState()).status in ('done', 'skipped'))

        if _p_active:
            el_s = _t_elapsed(tp or tleg)
            est  = _fmt(max(60, int(total_s)))
            if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'working copy: {_fmt(el_s)} / ~{est}')
            if 'proxy' in dot_refs: dot_refs['proxy'].set_content(_dot_html('running'))
            _set_act('proxy', el_s)
            if 'proxy' in count_refs and clip_ids:
                count_refs['proxy'].set_text(f'{_n_stage_done("proxy")}/{len(clip_ids)}')
        elif _s_active:
            el_s = _t_elapsed(ts)
            est  = _fmt(max(30, int(total_s // 3)))
            if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'scanning: {_fmt(el_s)} / ~{est}')
            if 'scan' in dot_refs:  dot_refs['scan'].set_content(_dot_html('running'))
            _set_act('scan', el_s)
            if 'scan' in count_refs and clip_ids:
                count_refs['scan'].set_text(f'{_n_stage_done("motion")}/{len(clip_ids)}')
        elif _h_active:
            el_s = _t_elapsed(th)
            if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'finding clips: {_fmt(el_s)}')
            if 'highlights' in dot_refs: dot_refs['highlights'].set_content(_dot_html('running'))
            _set_act('highlights', el_s)

        if tp and tp.done:
            if 'proxy' in dot_refs: dot_refs['proxy'].set_content(_dot_html('done'))
            _set_act('proxy', tp.elapsed)
            if 'proxy' in count_refs and clip_ids: count_refs['proxy'].set_text(str(len(clip_ids)))
        if ts and ts.done:
            if 'scan' in dot_refs: dot_refs['scan'].set_content(_dot_html('done'))
            _set_act('scan', ts.elapsed)
            if 'scan' in count_refs and clip_ids: count_refs['scan'].set_text(str(len(clip_ids)))
        if th and th.done:
            if 'highlights' in dot_refs: dot_refs['highlights'].set_content(_dot_html('done'))
            _set_act('highlights', th.elapsed)
            n_marks = 0
            with db_session() as _db2:
                if clip_ids:
                    n_marks = _db2.query(Mark).join(Clip, Mark.clip_id == Clip.id).filter(
                        Mark.clip_id.in_(clip_ids),
                        Mark.status.notin_([MarkStatus.BORING, MarkStatus.DULL]),
                    ).count()
            if 'highlights' in count_refs and n_marks:
                count_refs['highlights'].set_text(str(n_marks))
            if 'pick' in dot_refs: dot_refs['pick'].set_content(_dot_html('active'))

        # Reveal proxy video when first proxy ready
        if not _proxy_shown[0] and clip_ids:
            px_st = prog.get(clip_ids[0], {}).get('proxy', StageState())
            if px_st.status in ('done', 'skipped'):
                _proxy_shown[0] = True
                _set_player_tag('Working copy')
                ui.run_javascript(f'''
                  var v=document.getElementById("main-player");
                  var ph=document.getElementById("player-ph");
                  var st=document.getElementById("player-still");
                  if(v){{v.src="/proxies/{clip_ids[0]}.mp4";v.load();v.style.display="block";}}
                  if(ph)ph.style.display="none";
                  if(st)st.style.display="none";
                ''')

        # Update overlay progress bars
        step_stage_map = {'proxy': _PROXY_STAGES, 'scan': _SCAN_STAGES}
        if initial_stage in step_stage_map:
            stages = step_stage_map[initial_stage]
            for cid, stage_map in bar_refs.items():
                cp = prog.get(cid, {})
                for stage, el in stage_map.items():
                    if stage in stages:
                        el.set_content(_bar_html(
                            cp.get(stage, StageState()),
                            _STAGE_LABEL[stage], stage, detect_method_ref[0],
                        ))

        for t in (tp, ts, th, tleg):
            if t and t.error:
                ui.notify(f'Error: {t.error}', type='negative', timeout=0)
                _timer.active = False; return

        if not still_running:
            _timer.active = False
            if hdr_time_ref[0]: hdr_time_ref[0].set_text(f'took {elapsed}')
            ui.navigate.to(f'/session/{session_id}')

    _timer = ui.timer(0.5, _poll, active=_any_bg)
    _timer_ref[0] = _timer
