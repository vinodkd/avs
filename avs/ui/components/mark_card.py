"""Mark card strip HTML renderer for the review/pick stage."""
from avs import config
from avs.ui.components.timeline import PICK_STYLE
from avs.utils import fmt_timestamp as _tsfmt


def mark_cards_html(
    mark_data: list,
    statuses: dict[str, str],
    audio_spikes: dict[str, list[float]],
) -> str:
    """Render the mark card strip as an HTML string.

    mark_data:    list of (mark_id, clip_id, in_s, out_s, score, source)
    statuses:     {mark_id: ui_status} — 'in' | 'out' | 'skip' | 'dull'
    audio_spikes: {clip_id: [spike_timestamp_s, ...]}
    """
    parts = ['<div style="display:flex;flex-wrap:wrap;gap:0.4rem">']
    for mid, cid, in_s, out_s, score, source in mark_data:
        thumb = config.THUMB_DIR / cid / f'mark_{mid}.jpg'
        img_part = (
            f'<img src="/thumbs/{cid}/mark_{mid}.jpg" style="width:100%;height:60px;object-fit:cover;display:block">'
            if thumb.exists() else
            '<div style="width:100%;height:60px;background:#111"></div>'
        )
        ts_label = f'{_tsfmt(in_s)}–{_tsfmt(out_s)}'
        st = statuses.get(mid, 'in')
        bc, _, bi = PICK_STYLE[st]
        spikes = audio_spikes.get(cid, [])
        has_audio = (source == 'audio_spike' or any(in_s <= t <= out_s for t in spikes))
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
