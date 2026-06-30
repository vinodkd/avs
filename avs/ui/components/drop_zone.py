"""New-session form: path input, file/folder picker, sport selector."""
from pathlib import Path
from typing import Callable

from nicegui import ui

from avs.presets.sports import DEFAULT_PROFILES, display_name as _display_name


def new_session_controls(
    sports: list[str],
    default_sport: str,
    profile_info_html_fn: Callable[[str], str],
) -> dict:
    """Render the new-session action-bar controls.

    Must be called inside an action-bar row container.
    Returns a state dict with keys: path_ref, sport_ref, files, hint_ref, err_ref.
    """
    state: dict = {
        'path_ref':  [None],
        'sport_ref': [None],
        'files':     [],
        'hint_ref':  [None],
        'err_ref':   [None],
    }

    with ui.row().style('align-items:center;gap:0.4rem;flex:1'):
        _pi = ui.input(
            placeholder='/path/to/footage  or  /media/SDCARD/DCIM'
        ).style('flex:1;color:#eee;font-size:0.82rem')
        state['path_ref'][0] = _pi

        async def _browse() -> None:
            try:
                from nicegui import app as _ng_app
                import webview
                result = await _ng_app.native.main_window.create_file_dialog(
                    webview.FileDialog.OPEN, allow_multiple=True,
                    file_types=('Video files (*.mp4;*.MP4;*.mov;*.MOV;*.avi)',),
                )
            except Exception as exc:
                ui.notify(f'File picker unavailable: {exc}', type='warning')
                return
            hint = state['hint_ref'][0]
            files = state['files']
            if result:
                paths = [Path(r) for r in result]
                files.clear(); files.extend(paths)
                # Single file → store the file path so source_path shows the filename.
                # Multiple files → store the parent folder (ingest scans it).
                _pi.set_value(str(paths[0]) if len(paths) == 1 else str(paths[0].parent))
                if hint: hint.set_text(f'{len(paths)} file(s) selected')
            else:
                try:
                    from nicegui import app as _ng_app2
                    import webview as wv2
                    folder = await _ng_app2.native.main_window.create_file_dialog(
                        wv2.FileDialog.FOLDER, allow_multiple=False)
                except Exception as exc:
                    ui.notify(f'Folder picker unavailable: {exc}', type='warning')
                    return
                if folder:
                    _pi.set_value(folder[0]); files.clear()
                    if hint: hint.set_text('All video files in folder')

        ui.button(icon='folder_open', on_click=_browse).props(
            'flat round dense size=sm'
        ).tooltip('Browse')

        _hl = ui.label('').style('color:#666;font-size:0.72rem;min-width:80px')
        state['hint_ref'][0] = _hl

        _ss = ui.select(
            options={s: _display_name(s) for s in sports},
            value=default_sport,
            label='Sport',
        ).style('min-width:140px')
        state['sport_ref'][0] = _ss

        _pi_html_ref = [None]
        with ui.button(icon='info_outline').props(
            'flat round dense size=sm'
        ).style('color:#555').tooltip('What this sport profile does'):
            with ui.menu().style('background:#1c1c1c;border:1px solid #333'):
                _pi_html = ui.html(profile_info_html_fn(_ss.value), sanitize=False)
                _pi_html_ref[0] = _pi_html

        _ss.on_value_change(
            lambda e: _pi_html_ref[0].set_content(profile_info_html_fn(e.value))
            if _pi_html_ref[0] else None
        )

    _ne = ui.label('').style('color:#e57373;font-size:0.78rem')
    state['err_ref'][0] = _ne

    return state


def drop_zone_placeholder() -> None:
    """Render the 'No footage loaded yet' placeholder in the player area."""
    with ui.element('div').classes('ax2-dz'):
        with ui.element('div').classes('ax2-dz-ring'):
            ui.html('▷', sanitize=False, tag='span')
        ui.label('No footage loaded yet').classes('ax2-dz-label')
        ui.label('enter a path or use Browse above').classes('ax2-dz-sub')
