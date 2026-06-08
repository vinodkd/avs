import threading

from nicegui import ui

from axedup.models.db import get_session as db_session
from axedup.models.schema import Session, SessionStatus
from axedup.ui import state
from axedup.ui.filepicker import browse_file_button
from axedup.ui.layout import sidebar

_GRADES = ['punchy', 'cinematic', 'natural', 'warm', 'cool', 'vibrant']
_SOURCE_OPTIONS = {'(all accepted)': None, 'proxy': 'proxy', 'jpg': 'jpg', 'telemetry': 'telemetry'}


@ui.page('/cut/{session_id}')
def cut_page(session_id: str) -> None:
    ui.dark_mode().enable()

    with db_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            ui.label('Session not found.').style('color: #e57373; padding: 2rem')
            return
        status = session.status

    with ui.left_drawer(value=True).style('background: #1a1a1a; border-right: 1px solid #222'):
        sidebar('cut', session_id, status)

    with ui.column().style('padding: 2rem; width: 100%; min-height: 100vh; background: #111'):
        ui.label('Cut & Grade').style('color: #eee; font-size: 1.4rem; font-weight: 700; margin-bottom: 1.5rem')

        with ui.row().style('gap: 1.5rem; align-items: flex-end; flex-wrap: wrap; margin-bottom: 1rem'):
            grade_sel = ui.select(options=_GRADES, value='natural', label='Color grade').style('min-width: 160px')
            source_sel = ui.select(
                options=list(_SOURCE_OPTIONS.keys()),
                value='(all accepted)',
                label='Mark source',
            ).style('min-width: 160px')

        ui.label('Music track  (optional)').style('color: #aaa; font-size: 0.82rem; margin-bottom: 0.15rem')
        with ui.row().style('align-items: center; gap: 0.5rem; width: 100%; max-width: 480px; margin-bottom: 0.75rem'):
            music_input = ui.input(placeholder='No music — leave blank or browse for an MP3').style('flex: 1; color: #eee')
            browse_file_button(
                lambda p: music_input.set_value(p),
                file_types=('Audio files (*.mp3;*.aac;*.m4a;*.wav)',),
                tooltip='Browse for music track',
            )

        err = ui.label('').style('color: #e57373; font-size: 0.82rem; min-height: 1.2rem')
        status_lbl = ui.label('').style('color: #777; font-size: 0.85rem; min-height: 1.2rem')
        assemble_btn = ui.button('Assemble Preview', on_click=lambda: _start_assembly()).props('color=positive')

        preview_container = ui.element('div').style('margin-top: 1.5rem; width: 100%')

        # If already assembled, show preview immediately
        if status in (SessionStatus.ASSEMBLED, SessionStatus.EXPORTED):
            _show_preview(session_id, preview_container)

        def _start_assembly() -> None:
            assemble_btn.set_enabled(False)
            assemble_btn.set_text('Assembling…')
            err.set_text('')
            status_lbl.set_text('Encoding segments in parallel…')

            src_key = source_sel.value
            src_val = _SOURCE_OPTIONS.get(src_key)
            grade = grade_sel.value
            task_key = f'assemble_{session_id}'
            state.start_task(task_key)

            def _run() -> None:
                try:
                    from axedup.processing.assembly import assemble_session
                    assemble_session(session_id, grade_override=grade, source_filter=src_val)
                    state.finish_task(task_key)
                except Exception as exc:
                    state.finish_task(task_key, error=str(exc))

            threading.Thread(target=_run, daemon=True).start()

            def _poll() -> None:
                task = state.get_task(task_key)
                if not task:
                    return
                if task.error:
                    err.set_text(task.error)
                    status_lbl.set_text('')
                    assemble_btn.set_enabled(True)
                    assemble_btn.set_text('Assemble Preview')
                    poll_timer.active = False
                    return
                if task.done:
                    status_lbl.set_text('Preview ready.')
                    assemble_btn.set_enabled(True)
                    assemble_btn.set_text('Re-assemble')
                    poll_timer.active = False
                    preview_container.clear()
                    with preview_container:
                        _show_preview(session_id, preview_container)

            poll_timer = ui.timer(2.0, _poll)


def _show_preview(session_id: str, container) -> None:
    from axedup import config
    preview_path = config.PREVIEW_DIR / f'{session_id}_preview.mp4'
    if not preview_path.exists():
        return
    with container:
        ui.label('Preview').style('color: #aaa; font-size: 0.9rem; margin-bottom: 0.5rem')
        ui.html(
            f'<video src="/previews/{session_id}_preview.mp4" controls preload="metadata"'
            f' style="width:100%;max-height:55vh;background:#000;display:block"></video>',
            sanitize=False,
        )
        ui.button('Next: Save →', on_click=lambda: ui.navigate.to(f'/save/{session_id}')).props('flat color=positive').style('margin-top: 0.75rem')
