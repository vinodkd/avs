"""Timeline bar HTML renderer for the review stage."""
from avs.utils import fmt_duration as _fmt, fmt_timestamp as _tsfmt

# Visuals per review state: (bar colour, hatch background-image, badge icon)
PICK_STYLE: dict[str, tuple[str, str, str]] = {
    'in':   ('#2a7a2a', 'none', '✓'),
    'out':  ('#7a2a2a',
             'repeating-linear-gradient(-45deg,transparent,transparent 3px,'
             'rgba(0,0,0,0.35) 3px,rgba(0,0,0,0.35) 4px)', '✗'),
    'skip': ('#8a6a18',
             'repeating-linear-gradient(45deg,transparent,transparent 4px,'
             'rgba(0,0,0,0.3) 4px,rgba(0,0,0,0.3) 6px)', 'z'),
    'dull': ('#a8541d', 'none', '–'),
}


def timeline_html(
    mark_data: list,
    clip_info: list,
    statuses: dict[str, str] | None = None,
) -> str:
    """Render the timeline bar as an HTML string.

    mark_data: list of (mark_id, clip_id, in_s, out_s, score, source)
    clip_info: list of (clip_id, filename, duration_s)
    statuses:  {mark_id: ui_status} — 'in' | 'out' | 'skip' | 'dull'
    """
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
        if not dur_s:
            continue
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
        if first_offset >= tick_iv:
            first_offset = 0.0
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
            color, hatch, icon = PICK_STYLE[st]
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
