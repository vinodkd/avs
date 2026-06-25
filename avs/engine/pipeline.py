"""Engine pipeline — Step 0 steel thread.

All run_* functions own threading; callers register callbacks.
processing/ is unchanged; engine wraps it.

on_progress signature (matches existing processing/ on_event):
    (clip_id, stage, evt_status, message, completed, total) -> None

on_done signature:
    (error: str | None) -> None
"""
import threading
from pathlib import Path
from typing import Callable

from avs.engine.cancel import CancelledError, CancelToken

_active_tokens: dict[str, CancelToken] = {}
_NOOP_P = lambda *_: None  # noqa: E731


def _run_in_thread(session_id: str, token: CancelToken, fn: Callable, on_done: Callable) -> None:
    _active_tokens[session_id] = token
    def _target():
        try:
            fn()
            token._finish(None)
            if on_done:
                on_done(None)
        except CancelledError:
            token._finish("cancelled")
            if on_done:
                on_done("cancelled")
        except Exception as exc:
            token._finish(str(exc))
            if on_done:
                on_done(str(exc))
        finally:
            _active_tokens.pop(session_id, None)
    threading.Thread(target=_target, daemon=True).start()


# ── Ingest ────────────────────────────────────────────────────────────────────

def ingest_folder(source_path, sport: str, console=None, files=None):
    """Sync wrapper — call via ng_run.io_bound from async UI or directly from CLI."""
    from avs.processing.ingest import ingest_folder as _ingest
    return _ingest(source_path, sport, console, files)


def ingest_session(source_path, sport: str, files=None):
    """Sync: ingest folder + extract first-frame still. Returns session_obj.

    Combines the two blocking operations so the UI needs only one io_bound call.
    """
    from avs.processing.ingest import ingest_folder as _ingest
    from avs.processing.analysis import extract_source_still
    from avs.models.db import get_session as _db
    from avs.models.schema import Clip
    from avs import config

    session_obj = _ingest(source_path, sport, None, files)
    sid = session_obj.id

    with _db() as db:
        first_clip = (db.query(Clip)
                      .filter(Clip.session_id == sid)
                      .order_by(Clip.clip_order)
                      .first())
        filepath = Path(first_clip.filepath) if first_clip else None

    if filepath:
        extract_source_still(filepath, config.STILL_DIR / f'{sid}_still.jpg')

    return session_obj


def run_proxy(session_id: str, on_progress: Callable | None, on_done: Callable) -> CancelToken:
    token = CancelToken()
    def _fn():
        from avs.processing.analysis import build_proxy_only
        build_proxy_only(session_id, on_event=on_progress or _NOOP_P, cancel_token=token)
    _run_in_thread(session_id, token, _fn, on_done)
    return token


# ── Scan ──────────────────────────────────────────────────────────────────────

def run_scan(
    session_id: str,
    method: str,
    on_progress: Callable | None,
    on_done: Callable,
) -> CancelToken:
    """Motion scan + audio scan for a session."""
    token = CancelToken()
    def _fn():
        from avs.processing.analysis import run_motion_scan
        from avs.processing.audio import run_audio_scan
        on_prog = on_progress or _NOOP_P
        run_motion_scan(session_id, motion_method=method, on_event=on_prog, cancel_token=token)
        if not token.is_cancelled():
            run_audio_scan(session_id, on_event=on_prog)
    _run_in_thread(session_id, token, _fn, on_done)
    return token


# ── Peaks ─────────────────────────────────────────────────────────────────────

def run_peaks(
    session_id: str,
    method: str,
    on_progress: Callable | None,
    on_done: Callable,
) -> CancelToken:
    """Peak detection: motion marks, audio spikes, boring regions, dull gaps."""
    token = CancelToken()
    def _fn():
        from avs.processing.peaks import (
            detect_peaks, detect_audio_spikes,
            detect_boring_regions, detect_dull_gaps,
        )
        on_prog = on_progress or _NOOP_P
        detect_peaks(session_id, on_event=on_prog, motion_method=method, cancel_token=token)
        if not token.is_cancelled():
            detect_audio_spikes(session_id, on_event=on_prog, cancel_token=token)
        if not token.is_cancelled():
            detect_boring_regions(session_id, on_event=on_prog, motion_method=method, cancel_token=token)
        if not token.is_cancelled():
            detect_dull_gaps(session_id, on_event=on_prog, cancel_token=token)
    _run_in_thread(session_id, token, _fn, on_done)
    return token


# ── Thumbnails ────────────────────────────────────────────────────────────────

def run_thumbnails(
    session_id: str,
    on_progress: Callable | None,
    on_done: Callable,
) -> CancelToken:
    token = CancelToken()
    def _fn():
        from avs.processing.analysis import extract_mark_thumbnails
        extract_mark_thumbnails(session_id, on_event=on_progress or _NOOP_P)
    _run_in_thread(session_id, token, _fn, on_done)
    return token


# ── Assemble ──────────────────────────────────────────────────────────────────

def run_assemble(
    session_id: str,
    grade: str | None,
    source_filter: str | None,
    remove_mark_ids: list[str] | None,
    swap_music: bool,
    disable_overlay: bool,
    on_progress: Callable | None,
    on_done: Callable,
    on_event: Callable | None = None,
) -> CancelToken:
    token = CancelToken()
    def _fn():
        from avs.processing.assembly import assemble_session
        assemble_session(
            session_id,
            grade_override=grade,
            source_filter=source_filter,
            remove_mark_ids=remove_mark_ids or [],
            swap_music=swap_music,
            disable_overlay=disable_overlay,
            on_progress=on_progress,
            on_event=on_event,
            cancel_token=token,
        )
    _run_in_thread(session_id, token, _fn, on_done)
    return token


# ── Export ────────────────────────────────────────────────────────────────────

def run_export(
    session_id: str,
    aspects: list[str],
    output_dir: Path | None,
    on_progress: Callable | None,
    on_done: Callable,
    on_event: Callable | None = None,
) -> CancelToken:
    token = CancelToken()
    def _fn():
        from avs.processing.export import export_session
        export_session(
            session_id,
            aspects=aspects,
            output_dir=output_dir,
            on_progress=on_progress,
            on_event=on_event,
            cancel_token=token,
        )
    _run_in_thread(session_id, token, _fn, on_done)
    return token


# ── Cancel ────────────────────────────────────────────────────────────────────

def cancel_current(session_id: str) -> None:
    """Signal the active pipeline stage for this session to stop."""
    if token := _active_tokens.get(session_id):
        token.cancel()
