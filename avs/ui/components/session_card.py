"""Session row — one <tr> in the home page session table."""
from datetime import datetime

from nicegui import ui

from avs.models.schema import SessionStatus
from avs.presets.sports import display_name
from avs.utils import fmt_duration as _fmt


_STATUS_COLOR = {
    SessionStatus.READY:     '#7a8fd8',
    SessionStatus.ASSEMBLED: '#7a8fd8',
    SessionStatus.EXPORTED:  '#8a6aaa',
    SessionStatus.ANALYZING: '#aa8a3a',
    SessionStatus.INGESTED:  '#6a6a6a',
    SessionStatus.IMPORTING: '#6a6a6a',
}

_TD = 'padding:0.5rem 0.75rem;vertical-align:middle'


def session_row(
    sid: str,
    sport: str,
    src_name: str | None,
    created_at: datetime | None,
    duration: float | None,
    status,
) -> None:
    """Render one session as a table row for the home page."""
    from avs.engine import sessions as eng_sessions
    from avs.ui.components.confirm_dialog import confirm_dialog

    dest = f'/session/{sid}'
    color = _STATUS_COLOR.get(status, '#555')

    def _do_delete():
        eng_sessions.delete_session(sid)
        ui.navigate.to('/')

    open_dlg = confirm_dialog(
        'Delete this session?',
        'Removes all DB records and cached files (proxies, thumbnails, preview).',
        _do_delete,
        confirm_label='Delete',
    )

    with ui.element('tr').style('border-bottom:1px solid #1a1a1a'):
        with ui.element('td').style(_TD):
            ui.html(
                f'<span style="background:#1a1e3a;color:#7a8fd8;border-radius:4px;'
                f'padding:0.2rem 0.5rem;font-size:0.72rem;white-space:nowrap">'
                f'{display_name(sport)}</span>',
                sanitize=False,
            )
        with ui.element('td').style(_TD):
            ui.label(src_name or '').style(
                'color:#ccc;font-size:0.85rem;font-family:monospace;word-break:break-all'
            )
        with ui.element('td').style(f'{_TD};text-align:right'):
            ui.label(_fmt(duration) if duration else '').style(
                'color:#666;font-size:0.8rem;white-space:nowrap'
            )
        with ui.element('td').style(_TD):
            ui.label(created_at.strftime('%Y-%m-%d') if created_at else '').style(
                'color:#444;font-size:0.75rem;white-space:nowrap'
            )
        with ui.element('td').style(_TD):
            ui.html(
                f'<span style="background:#111;color:{color};border:1px solid {color};'
                f'border-radius:9999px;padding:0.15rem 0.5rem;font-size:0.72rem;'
                f'font-family:monospace;white-space:nowrap">{status}</span>',
                sanitize=False,
            )
        with ui.element('td').style(f'{_TD};text-align:right;white-space:nowrap'):
            ui.button('Continue →', on_click=lambda d=dest: ui.navigate.to(d)).props('flat color=positive size=sm')
            ui.button(icon='delete_outline', on_click=open_dlg).props('flat round dense').style('color:#5a3030').tooltip('Delete session')
