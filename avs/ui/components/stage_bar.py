"""Stage action bar — Next and Cancel buttons shared across all pipeline stages."""
from typing import Callable

from nicegui import ui


def next_cancel_buttons(
    session_id: str,
    on_next: Callable | None = None,
    on_cancel: Callable | None = None,
) -> dict:
    """Render Cancel + Next buttons for use inside an .ax2-action-bar container.

    Returns:
        next_btn:   ui.button — call .set_text() / .set_enabled() per stage
        cancel_btn: ui.button — call .set_visibility(True) while a stage is running
    """
    from avs.engine import pipeline as engine

    def _do_cancel():
        engine.cancel_current(session_id)
        if on_cancel:
            on_cancel()

    cancel_btn = ui.button('Cancel', on_click=_do_cancel).props('color=negative flat size=sm')
    cancel_btn.set_visibility(False)

    next_btn = ui.button('…', on_click=on_next).props('color=positive size=sm')
    next_btn.set_enabled(False)

    return {'next_btn': next_btn, 'cancel_btn': cancel_btn}
