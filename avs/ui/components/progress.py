"""Shared progress-bar and dot-indicator HTML generators.

Pure functions — no NiceGUI imports, no state. Used by session.py (proxy/scan
bars), combine.py (assembly bar), and export.py (export bar, Step 5).
"""

from avs.ui.state import StageState


def dot_html(st: str) -> str:
    if st == 'done':
        c, cls = '#7a8fd8', ''
    elif st == 'running':
        c, cls = '#f0a040', 'class="tl-run"'
    elif st == 'active':
        c, cls = '#6a9aaa', ''
    else:
        return ('<span style="width:9px;height:9px;border-radius:50%;'
                'background:#1c1c1c;border:1px solid #2a2a2a;display:inline-block"></span>')
    return (f'<span {cls} style="width:9px;height:9px;border-radius:50%;'
            f'background:{c};display:inline-block"></span>')


def bar_html(s: StageState, label: str, stage: str, method: str = 'proxy') -> str:
    """Stage progress bar: [label 148px] [bar flex] [pct/tick 24px]"""
    if s.status in ('done', 'skipped'):
        return (
            f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:9px">'
            f'<span style="color:#7a8fd8;font-size:0.78rem;flex-shrink:0;width:148px">{label}</span>'
            f'<div style="flex:1;height:7px;border-radius:4px;background:#1a1e3a;overflow:hidden">'
            f'<div style="height:100%;width:100%;background:#7a8fd8;border-radius:4px"></div></div>'
            f'<span style="color:#5a6fa8;font-size:0.7rem;width:24px;text-align:right">✓</span>'
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
            f'<div style="height:100%;width:{pct}%;background:#f0a040;border-radius:4px;'
            f'transition:width 0.3s ease"></div></div>'
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
