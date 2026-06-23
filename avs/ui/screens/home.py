from pathlib import Path

from nicegui import ui

from avs.models.db import get_session as db_session
from avs.models.schema import Session, SessionStatus
from avs.presets.sports import display_name
from avs.ui.layout import sidebar
from avs.utils import fmt_duration as _fmt


@ui.page('/')
def home_page() -> None:
    ui.dark_mode().enable()
    # Block the webview's default file-drop behavior — without this, dropping a
    # video onto the window navigates away from the app to fullscreen playback.
    ui.add_head_html(
        '<script>'
        "window.addEventListener('dragover',function(e){e.preventDefault();});"
        "window.addEventListener('drop',function(e){e.preventDefault();});"
        '</script>'
    )

    from avs.updater import get_update_available
    new_ver = get_update_available()
    if new_ver:
        ui.notify(
            f'Update available: v{new_ver} — visit github.com/vinodkd/avs/releases',
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
                (s.id, s.sport, Path(s.source_path).name if s.source_path else None,
                 s.created_at, s.total_clips, s.total_duration_s, s.status)
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

        for sid, sport, src_name, created_at, clips, duration, status in rows:
            _session_row(sid, sport, src_name, created_at, clips, duration, status)


def _session_row(sid: str, sport, src_name, created_at, clips, duration, status: str) -> None:
    dest = f'/session/{sid}'
    status_color = {
        SessionStatus.READY:     '#7a8fd8',
        SessionStatus.ASSEMBLED: '#7a8fd8',
        SessionStatus.EXPORTED:  '#8a6aaa',
        SessionStatus.ANALYZING: '#aa8a3a',
        SessionStatus.INGESTED:  '#6a6a6a',
        SessionStatus.IMPORTING: '#6a6a6a',
    }.get(status, '#555')

    with ui.card().style('background: #1e1e1e; margin-bottom: 0.5rem; width: 100%'):
        with ui.row().style('align-items: center; justify-content: space-between; width: 100%; gap: 0.5rem'):
            with ui.row().style('align-items: baseline; gap: 1rem; flex: 1; min-width: 0; flex-wrap: nowrap'):
                ui.html(
                    f'<span style="background:#1a1e3a;color:#7a8fd8;border-radius:4px;'
                    f'padding:0.2rem 0.5rem;font-size:0.72rem;white-space:nowrap;flex-shrink:0">'
                    f'{display_name(sport)}</span>',
                    sanitize=False,
                )
                if src_name:
                    ui.label(src_name).style(
                        'color:#ccc;font-size:0.85rem;font-family:monospace;'
                        'flex:1;min-width:0;overflow-wrap:anywhere'
                    )
                if duration:
                    ui.label(_fmt(duration)).style(
                        'color:#666;font-size:0.8rem;white-space:nowrap;flex-shrink:0'
                    )
                if created_at:
                    ui.label(created_at.strftime('%Y-%m-%d')).style(
                        'color:#444;font-size:0.75rem;white-space:nowrap;flex-shrink:0'
                    )

            with ui.row().style('align-items: center; gap: 0.75rem'):
                ui.html(
                    f'<span style="background:#111;color:{status_color};border:1px solid {status_color};'
                    f'border-radius:9999px;padding:0.15rem 0.5rem;font-size:0.72rem;'
                    f'font-family:monospace;white-space:nowrap">{status}</span>',
                    sanitize=False,
                )
                ui.button('Continue →', on_click=lambda d=dest: ui.navigate.to(d)).props('flat color=positive size=sm')
                _delete_button(sid)


def _delete_button(sid: str) -> None:
    from avs.engine import sessions as eng_sessions
    dialog = ui.dialog()
    with dialog, ui.card().style('background: #1e1e1e; padding: 1.25rem; min-width: 320px'):
        ui.label('Delete this session?').style('color: #eee; font-size: 1rem; font-weight: 600; margin-bottom: 0.4rem')
        ui.label('Removes all DB records and cached files (proxies, thumbnails, preview).').style(
            'color: #777; font-size: 0.78rem; margin-bottom: 1rem'
        )
        def _do_delete():
            eng_sessions.delete_session(sid)
            dialog.close()
            ui.navigate.to('/')
        with ui.row().style('gap: 0.5rem; justify-content: flex-end'):
            ui.button('Cancel', on_click=dialog.close).props('flat')
            ui.button('Delete', on_click=_do_delete).props('color=negative')

    ui.button(icon='delete_outline', on_click=dialog.open).props('flat round dense').style('color: #5a3030').tooltip(
        'Delete session'
    )


def _next_url(session_id: str, status: str) -> str:
    return f'/session/{session_id}'
