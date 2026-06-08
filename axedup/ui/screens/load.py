import threading
from pathlib import Path

from nicegui import app as nicegui_app, run, ui

import webview

from axedup.models.db import get_session as db_session
from axedup.models.schema import Profile
from axedup.ui import state
from axedup.ui.layout import sidebar

_SPORT_FALLBACK = ['mtb', 'surf', 'ski', 'cycling', 'moto', 'trail', 'skydive']


@ui.page('/load')
def load_page() -> None:
    ui.dark_mode().enable()

    drawer = ui.left_drawer(value=True).style('background: #1a1a1a; border-right: 1px solid #222')
    drawer.props('breakpoint=0 width=180 mini-width=48')
    with drawer:
        sidebar('load')

    # selected_files holds the list from the file picker; empty means "scan whole folder"
    selected_files: list[Path] = []

    with ui.column().style('padding: 2.5rem; max-width: 560px'):
        ui.label('Load Footage').style('color: #eee; font-size: 1.4rem; font-weight: 700; margin-bottom: 1.5rem')

        with db_session() as db:
            sports = [p.sport for p in db.query(Profile).order_by(Profile.sport).all()]
        sports = sports or _SPORT_FALLBACK

        # --- Source selection ---
        ui.label('Footage source').style('color: #aaa; font-size: 0.82rem; margin-bottom: 0.15rem')
        ui.label('Pick files to import specific clips, or type/paste a folder path to import everything in it.').style('color: #555; font-size: 0.75rem; margin-bottom: 0.3rem')
        with ui.row().style('align-items: center; gap: 0.5rem; width: 100%'):
            path_input = ui.input(placeholder='/path/to/footage or /media/SDCARD/DCIM').style('flex: 1; color: #eee')
            ui.button(icon='folder_open', on_click=lambda: _browse(path_input, selected_files, file_hint)).props('flat round dense').tooltip('Pick files or folder')

        file_hint = ui.label('').style('color: #666; font-size: 0.78rem; min-height: 1rem; margin-top: 0.1rem')

        sport_select = ui.select(options=sports, value=sports[0], label='Sport').style('width: 100%; margin-top: 0.75rem')

        # --- Scan method ---
        ui.label('Scan method').style('color: #aaa; font-size: 0.85rem; margin-top: 0.75rem; margin-bottom: 0.25rem')
        scan_method = ui.radio(
            options={
                'jpg':   'Quick  (JPEG frames, ~5× faster)',
                'proxy': 'Full  (optical flow, more accurate)',
            },
            value='jpg',
        ).props('dense').style('color: #ccc; gap: 0.4rem')

        err = ui.label('').style('color: #e57373; font-size: 0.82rem; min-height: 1.2rem; margin-top: 0.25rem')

        async def handle_start() -> None:
            path_str = path_input.value.strip()
            if not path_str:
                err.set_text('Enter a folder path or use the browse button to pick files')
                return
            source = Path(path_str)
            if not source.exists():
                err.set_text('Path not found — check and try again')
                return

            err.set_text('')
            btn.set_enabled(False)
            btn.set_text('Importing…')

            files_to_import = selected_files[:] if selected_files else None

            try:
                from axedup.processing.ingest import ingest_folder
                session = await run.io_bound(
                    ingest_folder, source, sport_select.value, None, files_to_import
                )
            except Exception as exc:
                err.set_text(str(exc))
                btn.set_enabled(True)
                btn.set_text('Start')
                return

            session_id = session.id
            method = scan_method.value
            state.start_task(session_id)

            def _analyze() -> None:
                def _on_event(clip_id, stage, status, message, completed, total):
                    if clip_id is None:
                        return
                    if status in ('running', 'done', 'skipped'):
                        state.update_clip_stage(session_id, clip_id, stage, status)
                    elif status == 'progress' and completed is not None and total:
                        pct = int(completed * 100 / total)
                        state.update_clip_stage(
                            session_id, clip_id, stage, 'running',
                            pct=pct, completed=completed, total=total,
                        )

                try:
                    from axedup.processing.analysis import analyze_session
                    analyze_session(session_id, motion_method=method, on_event=_on_event)
                    state.finish_task(session_id)
                except Exception as exc:
                    state.finish_task(session_id, error=str(exc))

            threading.Thread(target=_analyze, daemon=True).start()
            ui.navigate.to(f'/session/{session_id}')

        btn = ui.button('Start', on_click=handle_start).props('color=positive').style('width: 100%; margin-top: 1rem')


async def _browse(path_input, selected_files: list, hint_lbl) -> None:
    """Open a multi-select file picker. If files are chosen, import only those.
    If cancelled without selecting, fall back to a folder picker so the user
    can import everything in a directory."""
    try:
        result = await nicegui_app.native.main_window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=('Video files (*.mp4;*.MP4;*.mov;*.MOV;*.avi)',),
        )
    except Exception as exc:
        ui.notify(f'File picker unavailable: {exc}', type='warning')
        return

    if result:
        paths = [Path(r) for r in result]
        selected_files.clear()
        selected_files.extend(paths)
        path_input.set_value(str(paths[0].parent))
        hint_lbl.set_text(f'{len(paths)} file(s) selected — only these will be imported')
    else:
        # Nothing chosen from file picker — offer folder selection
        try:
            folder = await nicegui_app.native.main_window.create_file_dialog(
                webview.FileDialog.FOLDER, allow_multiple=False
            )
        except Exception as exc:
            ui.notify(f'Folder picker unavailable: {exc}', type='warning')
            return
        if folder:
            path_input.set_value(folder[0])
            selected_files.clear()
            hint_lbl.set_text('All video files in this folder will be imported')
