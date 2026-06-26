"""Generic confirm/cancel dialog — returns the open() callable."""
from typing import Callable

from nicegui import ui


def confirm_dialog(
    title: str,
    body: str,
    on_confirm: Callable,
    confirm_label: str = 'Confirm',
    confirm_color: str = 'negative',
) -> Callable:
    """Render a modal confirm dialog and return its open() callable.

    Usage:
        open_dlg = confirm_dialog('Delete?', 'This cannot be undone.', do_delete)
        ui.button('Delete', on_click=open_dlg)
    """
    dlg = ui.dialog()
    with dlg, ui.card().style('background:#1e1e1e;padding:1.25rem;min-width:300px'):
        ui.label(title).style('color:#eee;font-weight:600;margin-bottom:0.4rem')
        if body:
            ui.label(body).style('color:#777;font-size:0.78rem;margin-bottom:1rem')

        def _do():
            on_confirm()
            dlg.close()

        with ui.row().style('gap:0.5rem;justify-content:flex-end'):
            ui.button('Cancel', on_click=dlg.close).props('flat')
            ui.button(confirm_label, on_click=_do).props(f'color={confirm_color}')
    return dlg.open
