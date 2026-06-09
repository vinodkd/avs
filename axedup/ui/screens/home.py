import shutil

from nicegui import ui

from axedup import config
from axedup.models.db import get_session as db_session
from axedup.models.schema import Clip, Mark, Session, SessionStatus
from axedup.ui.layout import sidebar


@ui.page('/')
def home_page() -> None:
    ui.dark_mode().enable()

    from axedup.updater import get_update_available
    new_ver = get_update_available()
    if new_ver:
        ui.notify(
            f'Update available: v{new_ver} — visit github.com/vinodkd/axedup/releases',
            type='info', timeout=0, close_button=True,
        )

    drawer = ui.left_drawer(value=True).style('background: #1a1a1a; border-right: 1px solid #222')
    drawer.props('breakpoint=0 width=180 mini-width=48')
    with drawer:
        sidebar('home')

    with ui.column().style('padding: 2rem; width: 100%; min-height: 100vh; background: #111'):
        with ui.row().style('align-items: center; justify-content: space-between; margin-bottom: 1.5rem; width: 100%'):
            ui.label('Sessions').style('color: #eee; font-size: 1.4rem; font-weight: 700')
            ui.button('Start editing →', on_click=lambda: ui.navigate.to('/session/new')).props('color=positive flat')

        with db_session() as db:
            rows = [
                (s.id, s.sport, s.created_at, s.total_clips, s.total_duration_s, s.status)
                for s in db.query(Session).order_by(Session.created_at.desc()).all()
            ]

        if not rows:
            with ui.column().style(
                'flex:1;align-items:center;justify-content:center;'
                'padding:4rem 2rem;gap:0.75rem;text-align:center'
            ):
                ui.label('No sessions yet.').style('color: #333; font-size: 1rem')
                ui.button(
                    'Start editing →',
                    on_click=lambda: ui.navigate.to('/session/new'),
                ).props('color=positive size=lg')
            return

        for sid, sport, created_at, clips, duration, status in rows:
            _session_row(sid, sport, created_at, clips, duration, status)


def _session_row(sid: str, sport, created_at, clips, duration, status: str) -> None:
    dest = _next_url(sid, status)
    status_color = {
        SessionStatus.READY:     '#5a9a5a',
        SessionStatus.ASSEMBLED: '#5a7aaa',
        SessionStatus.EXPORTED:  '#8a6aaa',
        SessionStatus.ANALYZING: '#aa8a3a',
        SessionStatus.INGESTED:  '#6a6a6a',
        SessionStatus.IMPORTING: '#6a6a6a',
    }.get(status, '#555')

    with ui.card().style('background: #1e1e1e; margin-bottom: 0.5rem; width: 100%'):
        with ui.row().style('align-items: center; justify-content: space-between; width: 100%'):
            with ui.row().style('align-items: center; gap: 1rem; flex-wrap: wrap'):
                ui.badge(sport or 'unknown').style(
                    'background: #1a2a1a; color: #5a9a5a; font-size: 0.75rem; padding: 0.2rem 0.5rem'
                )
                ui.label(created_at.strftime('%Y-%m-%d  %H:%M') if created_at else '').style(
                    'color: #aaa; font-size: 0.85rem'
                )
                if clips:
                    ui.label(f'{clips} clip{"s" if clips != 1 else ""}').style('color: #666; font-size: 0.8rem')
                if duration:
                    m, s = divmod(int(duration), 60)
                    ui.label(f'{m}m{s:02d}s total').style('color: #666; font-size: 0.8rem')

            with ui.row().style('align-items: center; gap: 0.75rem'):
                ui.badge(status).style(
                    f'background: #111; color: {status_color}; font-size: 0.75rem; '
                    'border: 1px solid currentColor; padding: 0.15rem 0.4rem'
                )
                ui.button('Continue →', on_click=lambda d=dest: ui.navigate.to(d)).props('flat color=positive size=sm')
                _delete_button(sid)


def _delete_button(sid: str) -> None:
    dialog = ui.dialog()
    with dialog, ui.card().style('background: #1e1e1e; padding: 1.25rem; min-width: 320px'):
        ui.label('Delete this session?').style('color: #eee; font-size: 1rem; font-weight: 600; margin-bottom: 0.4rem')
        ui.label('Removes all DB records and cached files (proxies, thumbnails, preview).').style(
            'color: #777; font-size: 0.78rem; margin-bottom: 1rem'
        )
        with ui.row().style('gap: 0.5rem; justify-content: flex-end'):
            ui.button('Cancel', on_click=dialog.close).props('flat')
            ui.button('Delete', on_click=lambda: (_do_delete(sid), dialog.close())).props('color=negative')

    ui.button(icon='delete_outline', on_click=dialog.open).props('flat round dense').style('color: #5a3030').tooltip(
        'Delete session'
    )


def _do_delete(sid: str) -> None:
    with db_session() as db:
        clips    = db.query(Clip).filter(Clip.session_id == sid).all()
        clip_ids = [c.id for c in clips]
        mark_ids = [
            m.id
            for c in clips
            for m in db.query(Mark).filter(Mark.clip_id == c.id).all()
        ]
        sess = db.query(Session).filter(Session.id == sid).first()
        if sess:
            db.delete(sess)

    # Wipe cached files
    (config.PREVIEW_DIR / f'{sid}_preview.mp4').unlink(missing_ok=True)
    for cid in clip_ids:
        (config.PROXY_DIR / f'{cid}.mp4').unlink(missing_ok=True)
        shutil.rmtree(config.THUMB_DIR / cid, ignore_errors=True)
        shutil.rmtree(config.JPEG_FRAMES_DIR / cid, ignore_errors=True)
    for mid in mark_ids:
        (config.SEGMENT_DIR / f'{mid}.mp4').unlink(missing_ok=True)

    ui.navigate.to('/')


def _next_url(session_id: str, status: str) -> str:
    return f'/session/{session_id}'
