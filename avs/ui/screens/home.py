from pathlib import Path

from nicegui import ui

from avs.engine import sessions as eng_sessions
from avs.ui.components.session_card import session_row
from avs.ui.layout import page_shell


@ui.page('/')
def home_page() -> None:
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

    with page_shell('home'):
        with ui.row().style('align-items:center;justify-content:space-between;margin-bottom:1.5rem;width:100%'):
            ui.label('Sessions').style('color:#eee;font-size:1.4rem;font-weight:700')
            ui.button('New edit session →', on_click=lambda: ui.navigate.to('/session/new')).props('color=positive flat')

        sessions = eng_sessions.list_sessions()

        if not sessions:
            with ui.column().style(
                'flex:1;align-items:center;justify-content:center;'
                'padding:4rem 2rem;gap:0.75rem;text-align:center'
            ):
                ui.label('No sessions yet.').style('color:#333;font-size:1rem')
                ui.button(
                    'New edit session →',
                    on_click=lambda: ui.navigate.to('/session/new'),
                ).props('color=positive size=lg')
            return

        _TH = ('color:#444;font-size:0.7rem;text-transform:uppercase;'
               'letter-spacing:0.04em;padding:0.4rem 0.75rem;'
               'border-bottom:1px solid #222;font-weight:600;white-space:nowrap')
        with ui.element('table').style('width:100%;border-collapse:collapse'):
            with ui.element('thead'):
                with ui.element('tr'):
                    for col, align in [
                        ('Sport', 'left'), ('Source', 'left'),
                        ('Source duration', 'right'), ('Date', 'left'),
                        ('Status', 'left'), ('Actions', 'right'),
                    ]:
                        with ui.element('th').style(f'{_TH};text-align:{align}'):
                            ui.label(col)
            with ui.element('tbody'):
                for s in sessions:
                    src_name = Path(s.source_path).name if s.source_path else None
                    session_row(s.id, s.sport, src_name, s.created_at, s.total_duration_s, s.status)
