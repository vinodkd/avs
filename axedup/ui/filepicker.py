"""Native file/folder picker dialogs via pywebview."""
import webview
from nicegui import app as nicegui_app, ui


async def pick_folder(title: str = "Select folder") -> str | None:
    """Open a native folder-selection dialog. Returns path string or None."""
    try:
        result = await nicegui_app.native.main_window.create_file_dialog(
            webview.FileDialog.FOLDER,
            allow_multiple=False,
        )
        return result[0] if result else None
    except Exception as exc:
        ui.notify(f"Folder picker unavailable: {exc}", type="warning", timeout=4000)
        return None


async def pick_file(
    title: str = "Select file",
    file_types: tuple[str, ...] = ("All files (*.*)",),
) -> str | None:
    """Open a native file-selection dialog. Returns path string or None."""
    try:
        result = await nicegui_app.native.main_window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=False,
            file_types=file_types,
        )
        return result[0] if result else None
    except Exception as exc:
        ui.notify(f"File picker unavailable: {exc}", type="warning", timeout=4000)
        return None


def browse_button(on_pick, icon: str = "folder_open", tooltip: str = "Browse") -> None:
    """Render a small icon button that calls on_pick(path) with the chosen folder."""
    async def _click() -> None:
        path = await pick_folder()
        if path:
            on_pick(path)

    ui.button(icon=icon, on_click=_click).props("flat round dense").tooltip(tooltip)


def browse_file_button(on_pick, file_types: tuple[str, ...] = ("All files (*.*)",), tooltip: str = "Browse") -> None:
    """Render a small icon button that calls on_pick(path) with the chosen file."""
    async def _click() -> None:
        path = await pick_file(file_types=file_types)
        if path:
            on_pick(path)

    ui.button(icon="audio_file", on_click=_click).props("flat round dense").tooltip(tooltip)
