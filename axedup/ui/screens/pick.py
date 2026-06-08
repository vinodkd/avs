from nicegui import ui

from axedup import config
from axedup.models.db import get_session as db_session
from axedup.models.schema import Clip, Mark, MarkStatus, Session
from axedup.ui.layout import sidebar

_CARD_BASE = 'background: #1e1e1e; border-radius: 6px; overflow: hidden; cursor: pointer; width: 200px; flex-shrink: 0'
_BORDER_ACCEPT = 'border: 2px solid #2a7a2a'
_BORDER_REJECT = 'border: 2px solid #5a2020'


@ui.page('/pick/{session_id}')
def pick_page(session_id: str) -> None:
    ui.dark_mode().enable()

    with db_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            ui.label('Session not found.').style('color: #e57373; padding: 2rem')
            return
        status = session.status
        clips = {
            c.id: c
            for c in db.query(Clip).filter(Clip.session_id == session_id).order_by(Clip.clip_order).all()
        }
        marks = (
            db.query(Mark)
            .join(Clip, Mark.clip_id == Clip.id)
            .filter(Mark.clip_id.in_(clips.keys()))
            .filter(Mark.status.in_([MarkStatus.CANDIDATE, MarkStatus.ACCEPTED]))
            .order_by(Clip.clip_order, Mark.in_s)
            .all()
        )
        mark_data = [
            # CANDIDATE = not yet reviewed → treat as accepted by default (same as CLI HTML page)
            # ACCEPTED  = explicitly kept in a prior pass → stays accepted
            (m.id, m.clip_id, m.in_s, m.out_s, m.score or 0.0, m.source, True)
            for m in marks
        ]
        clips_data = {cid: (c.filename, c.proxy_path) for cid, c in clips.items()}

    with ui.left_drawer(value=True).style('background: #1a1a1a; border-right: 1px solid #222'):
        sidebar('pick', session_id, status)

    with ui.column().style('width: 100%; height: 100vh; background: #111; display: flex; flex-direction: column'):

        # --- Top bar ---
        with ui.row().style('align-items: center; justify-content: space-between; padding: 0.75rem 1.25rem; border-bottom: 1px solid #222; flex-shrink: 0'):
            ui.label(f'Pick Clips  ·  {len(mark_data)} candidate(s)').style('color: #eee; font-size: 1rem; font-weight: 600')
            with ui.row().style('gap: 0.75rem; align-items: center'):
                summary_lbl = ui.label('').style('color: #777; font-size: 0.82rem')
                submit_btn = ui.button('Apply →', on_click=lambda: _apply(session_id, decisions, summary_lbl)).props('color=positive')

        # --- Video player ---
        # src attribute directly on <video> — more reliable than <source> in embedded browsers.
        # First clip that actually has a proxy file on disk.
        first_proxy_url = next(
            (f'/proxies/{cid}.mp4' for cid, (_, pp) in clips_data.items() if pp),
            '',
        )

        with ui.element('div').style('flex-shrink: 0; background: #000; width: 100%'):
            ui.html(
                f'<video id="axedup-player" src="{first_proxy_url}" controls preload="metadata"'
                f' style="width:100%;max-height:42vh;display:block;background:#000"></video>',
                sanitize=False,
            )

        # --- Mark strip ---
        if not mark_data:
            ui.label('No candidate marks found. Re-run analyze first.').style('color: #666; padding: 2rem; text-align: center')
            return

        decisions: dict[str, bool] = {mid: accepted for mid, *_, accepted in mark_data}
        _update_summary(decisions, summary_lbl)

        cards: dict[str, object] = {}  # mark_id -> card element

        with ui.scroll_area().style('flex: 1; width: 100%; overflow-y: auto'):
            with ui.row().style('flex-wrap: wrap; gap: 0.75rem; padding: 1rem'):
                for mid, clip_id, in_s, out_s, score, source, accepted in mark_data:
                    _mark_card(mid, clip_id, in_s, out_s, score, source, accepted,
                               decisions, cards, summary_lbl, clips_data)


def _mark_card(
    mid: str, clip_id: str, in_s: float, out_s: float,
    score: float, source: str, accepted: bool,
    decisions: dict, cards: dict, summary_lbl, clips_data: dict,
) -> None:
    border = _BORDER_ACCEPT if accepted else _BORDER_REJECT
    thumb_url = _thumb_url(clip_id, (in_s + out_s) / 2)
    dur = out_s - in_s

    with ui.element('div').style(f'{_CARD_BASE}; {border}') as card:
        cards[mid] = card

        def _seek(c=clip_id, t=in_s) -> None:
            proxy_url = f'/proxies/{c}.mp4'
            ui.run_javascript(f'''
                var v = document.getElementById('axedup-player');
                if (v) {{
                    var newSrc = "{proxy_url}";
                    if (!v.src.endsWith(newSrc)) {{
                        v.src = newSrc; v.load();
                        v.addEventListener('loadedmetadata', function() {{
                            v.currentTime = {t}; v.play();
                        }}, {{once: true}});
                    }} else {{
                        v.currentTime = {t}; v.play();
                    }}
                }}
            ''')

        ui.image(thumb_url).style('width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block').on('click', _seek)

        with ui.element('div').style('padding: 0.4rem 0.5rem'):
            ui.label(f'{_fmt(in_s)} – {_fmt(out_s)}').style('color: #fff; font-size: 0.82rem; font-weight: 600')
            ui.label(f'{dur:.1f}s  ·  {_source_short(source)}').style('color: #555; font-size: 0.72rem')
            with ui.element('div').style('background: #2a2a2a; border-radius: 2px; height: 4px; margin: 0.3rem 0'):
                ui.element('div').style(f'background: #3a9a3a; width: {int(score * 100)}%; height: 100%; border-radius: 2px')

        with ui.row().style('gap: 0; border-top: 1px solid #2a2a2a'):
            def _accept(m=mid, c=card) -> None:
                decisions[m] = True
                c.style(f'{_CARD_BASE}; {_BORDER_ACCEPT}')
                _update_summary(decisions, summary_lbl)

            def _reject(m=mid, c=card) -> None:
                decisions[m] = False
                c.style(f'{_CARD_BASE}; {_BORDER_REJECT}')
                _update_summary(decisions, summary_lbl)

            ui.button('✓', on_click=_accept).props('flat').style(
                'flex: 1; color: #5a9a5a; font-size: 0.85rem; border-radius: 0; padding: 0.25rem'
            )
            ui.element('div').style('width: 1px; background: #2a2a2a')
            ui.button('✗', on_click=_reject).props('flat').style(
                'flex: 1; color: #7a4a4a; font-size: 0.85rem; border-radius: 0; padding: 0.25rem'
            )


def _apply(session_id: str, decisions: dict, summary_lbl) -> None:
    from axedup.models.db import get_session as db_session
    from axedup.models.schema import Mark
    accepted = rejected = 0
    with db_session() as db:
        for mid, is_acc in decisions.items():
            m = db.query(Mark).filter(Mark.id == mid).first()
            if m:
                m.status = MarkStatus.ACCEPTED if is_acc else MarkStatus.REJECTED
                if is_acc:
                    accepted += 1
                else:
                    rejected += 1
    ui.notify(f'{accepted} accepted, {rejected} rejected', type='positive')
    summary_lbl.set_text(f'{accepted} accepted · {rejected} rejected — saved')
    ui.navigate.to(f'/cut/{session_id}')


def _update_summary(decisions: dict, lbl) -> None:
    acc = sum(1 for v in decisions.values() if v)
    rej = len(decisions) - acc
    lbl.set_text(f'{acc} accepted · {rej} rejected')


def _thumb_url(clip_id: str, timestamp_s: float) -> str:
    idx = max(1, round(timestamp_s / config.THUMB_INTERVAL))
    thumb_dir = config.THUMB_DIR / clip_id
    for offset in range(6):
        for sign in ([0] if offset == 0 else [1, -1]):
            candidate = thumb_dir / f'{idx + sign * offset:04d}.jpg'
            if candidate.exists():
                return f'/thumbs/{clip_id}/{candidate.name}'
    return 'data:image/gif;base64,R0lGODlhAQABAIAAAMLCwgAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw=='


def _fmt(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f'{m}:{s:02d}'


def _source_short(source: str) -> str:
    return {'motion_peak': 'proxy', 'motion_peak_jpg': 'jpg', 'telemetry_peak': 'telem'}.get(source, source)
