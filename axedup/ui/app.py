import os
import signal

from nicegui import app, ui

from axedup import config


def start(port: int = 8765) -> None:
    """Launch the AxEdUp NiceGUI desktop app."""
    config.ensure_dirs()

    # Serve cached files so the video player and thumbnails work
    app.add_static_files('/proxies', str(config.PROXY_DIR))
    app.add_static_files('/thumbs', str(config.THUMB_DIR))
    app.add_static_files('/stills', str(config.STILL_DIR))
    app.add_static_files('/previews', str(config.PREVIEW_DIR))

    # Import screens to register their @ui.page routes before ui.run()
    from axedup.ui.screens import cut, home, load, pick, save, scan, session  # noqa: F401

    # When the native window closes, destroy pywebview windows (releases IPC semaphores)
    # then SIGTERM ourselves so uvicorn shuts down cleanly and the terminal is freed.
    def _shutdown() -> None:
        try:
            import webview
            for window in webview.windows:
                window.destroy()
        except Exception:
            pass
        os.kill(os.getpid(), signal.SIGTERM)

    app.on_shutdown(_shutdown)

    ui.run(
        port=port,
        title='AxEdUp',
        native=True,
        window_size=(1280, 820),
        dark=True,
        show=False,   # native=True opens the window directly
        reload=False,
    )
