import threading

from nicegui import ui

from axedup import config
from axedup.models.db import get_session as db_session
from axedup.models.schema import Export, Session, SessionStatus
from axedup.ui import state
from axedup.ui.filepicker import browse_button
from axedup.ui.layout import sidebar


@ui.page('/save/{session_id}')
def save_page(session_id: str) -> None:
    ui.dark_mode().enable()

    with db_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            ui.label('Session not found.').style('color: #e57373; padding: 2rem')
            return
        status = session.status

    with ui.left_drawer(value=True).style('background: #1a1a1a; border-right: 1px solid #222'):
        sidebar('save', session_id, status)

    with ui.column().style('padding: 2rem; width: 100%; min-height: 100vh; background: #111'):
        ui.label('Save').style('color: #eee; font-size: 1.4rem; font-weight: 700; margin-bottom: 1.5rem')

        if status not in (SessionStatus.ASSEMBLED, SessionStatus.EXPORTED):
            ui.label('Assemble a preview first before exporting.').style('color: #777')
            ui.button('← Back to Cut', on_click=lambda: ui.navigate.to(f'/cut/{session_id}')).props('flat color=positive')
            return

        ui.label('Aspect ratios').style('color: #aaa; font-size: 0.85rem; margin-bottom: 0.4rem')
        aspect_16 = ui.checkbox('16:9  (YouTube, landscape)', value=True)
        aspect_9 = ui.checkbox('9:16  (Instagram Reels, portrait)', value=False)

        ui.separator().style('margin: 0.75rem 0; border-color: #2a2a2a')

        ui.label('Output folder').style('color: #aaa; font-size: 0.82rem; margin-bottom: 0.15rem')
        with ui.row().style('align-items: center; gap: 0.5rem; width: 100%'):
            out_dir_input = ui.input(value=str(config.OUTPUT_DIR)).style('flex: 1; color: #eee')
            browse_button(lambda p: out_dir_input.set_value(p), tooltip='Browse for output folder')

        err = ui.label('').style('color: #e57373; font-size: 0.82rem; min-height: 1.2rem; margin-top: 0.5rem')
        status_lbl = ui.label('').style('color: #777; font-size: 0.85rem; min-height: 1.2rem')

        output_container = ui.element('div').style('margin-top: 1rem')

        def _start_export() -> None:
            aspects = []
            if aspect_16.value:
                aspects.append('16:9')
            if aspect_9.value:
                aspects.append('9:16')
            if not aspects:
                err.set_text('Select at least one aspect ratio')
                return

            out_dir = out_dir_input.value.strip() or None

            err.set_text('')
            export_btn.set_enabled(False)
            export_btn.set_text('Exporting…')
            status_lbl.set_text('Encoding final output…')

            task_key = f'export_{session_id}'
            state.start_task(task_key)
            captured = (aspects[:], out_dir)

            def _run() -> None:
                asp, odir = captured
                try:
                    from axedup.processing.export import export_session
                    from pathlib import Path
                    export_session(session_id, aspects=asp, output_dir=Path(odir) if odir else None)
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
                    export_btn.set_enabled(True)
                    export_btn.set_text('Export')
                    poll_timer.active = False
                    return
                if task.done:
                    status_lbl.set_text('Export complete.')
                    export_btn.set_enabled(True)
                    export_btn.set_text('Export again')
                    poll_timer.active = False
                    _refresh_outputs()

            poll_timer = ui.timer(2.0, _poll)

        export_btn = ui.button('Export', on_click=_start_export).props('color=positive').style('margin-top: 0.75rem')

        def _refresh_outputs() -> None:
            output_container.clear()
            with output_container:
                with db_session() as db:
                    exports = (
                        db.query(Export)
                        .filter(Export.session_id == session_id)
                        .order_by(Export.exported_at.desc())
                        .all()
                    )
                if exports:
                    ui.label('Output files').style('color: #aaa; font-size: 0.85rem; margin-bottom: 0.5rem; margin-top: 0.5rem')
                for exp in exports:
                    with ui.card().style('background: #1e1e1e; margin-bottom: 0.4rem'):
                        with ui.row().style('align-items: center; gap: 1rem'):
                            ui.badge(exp.aspect).style('background: #1a2a1a; color: #5a9a5a')
                            ui.label(exp.filepath).style(
                                'color: #aaa; font-size: 0.8rem; font-family: monospace; '
                                'flex: 1; word-break: break-all'
                            )

        _refresh_outputs()
