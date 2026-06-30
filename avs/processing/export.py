"""
Export pipeline: re-encode the approved preview into final output files.
Supports 16:9 (YouTube) and 9:16 (Reels / Shorts / TikTok) aspect ratios.
"""

import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from avs import config
from avs.models.db import get_session
from avs.models.schema import Export, Session, SessionStatus

if TYPE_CHECKING:
    from avs.engine.cancel import CancelToken

# Target encode settings per aspect ratio
_ENCODE_SETTINGS = {
    "16:9": {
        "vf":      "scale=1920:1080:force_original_aspect_ratio=decrease,"
                   "pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "crf":     "20",
        "preset":  "slow",
        "suffix":  "youtube",
    },
    "9:16": {
        # Centre-crop to 9:16 then scale to 1080×1920
        "vf":      "crop=ih*9/16:ih,scale=1080:1920",
        "crf":     "22",
        "preset":  "medium",
        "suffix":  "reel",
    },
}


def export_session(
    session_id: str,
    aspects: list[str] | None = None,
    output_dir: Path | None = None,
    on_progress: Callable[[str, int], None] | None = None,
    on_event: Callable[[str], None] | None = None,
    cancel_token: 'CancelToken | None' = None,
) -> list[Path]:
    """
    Export the assembled preview for *session_id* in each requested aspect ratio.
    Returns a list of output file paths.
    """
    _log = on_event or (lambda _: None)
    aspects = aspects or ["16:9"]

    with get_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")
        if session.status not in (SessionStatus.ASSEMBLED, SessionStatus.EXPORTED):
            raise ValueError(
                f"Session is not combined yet (status: {session.status}). "
                "Run combine first."
            )

    preview_path = config.PREVIEW_DIR / f"{session_id}_preview.mp4"
    if not preview_path.exists():
        raise ValueError(f"Preview not found at {preview_path}. Run combine first.")

    date_str = datetime.now().strftime("%Y-%m-%d")
    sport = session.sport or "video"
    out_root = Path(output_dir) if output_dir else config.OUTPUT_DIR

    output_paths: list[Path] = []

    for aspect in aspects:
        if cancel_token and cancel_token.is_cancelled():
            _log("Export cancelled.")
            break
        if aspect not in _ENCODE_SETTINGS:
            _log(f"[yellow]Unknown aspect ratio '{aspect}', skipping.[/yellow]")
            continue

        settings = _ENCODE_SETTINGS[aspect]
        filename = f"{date_str}_{sport}_{settings['suffix']}.mp4"
        dest = out_root / filename

        _log(f"Exporting {aspect} → {dest.name} …")
        def _prog(pct: int, _asp: str = aspect) -> None:
            if on_progress: on_progress(_asp, pct)
        _encode(preview_path, dest, settings, on_progress=_prog, cancel_token=cancel_token)

        duration = _get_duration(dest)

        with get_session() as db:
            db.add(Export(
                session_id=session_id,
                filepath=str(dest),
                aspect=aspect,
                duration_s=duration,
            ))
            s = db.query(Session).filter(Session.id == session_id).first()
            s.status = SessionStatus.EXPORTED

        output_paths.append(dest)
        _log(f"  {dest}  ({dest.stat().st_size / 1e6:.1f} MB)")

    if output_paths:
        from avs.engine.sessions import clean_session_cache
        clean_session_cache(session_id)

    return output_paths


def _encode(source: Path, dest: Path, settings: dict,
            on_progress: Callable[[int], None] | None = None,
            cancel_token: 'CancelToken | None' = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    duration = _get_duration(source) or 0
    timeout = max(600, int(duration * 20))
    cmd = [
        config.FFMPEG_BIN, "-y",
        "-i", str(source),
        "-vf", settings["vf"],
        "-c:v", "libx264",
        "-preset", settings["preset"],
        "-crf", settings["crf"],
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        str(dest),
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    if cancel_token:
        cancel_token.register_cleanup(process.terminate)
    deadline = time.time() + timeout
    timed_out = False
    cancelled = False
    try:
        for line in process.stdout:
            if cancel_token and cancel_token.is_cancelled():
                process.terminate()
                cancelled = True
                break
            if time.time() > deadline:
                timed_out = True
                process.kill()
                break
            if line.startswith("out_time_ms=") and duration:
                try:
                    out_ms = int(line.split("=", 1)[1].strip())
                    pct = min(100, int(out_ms / (duration * 1_000_000) * 100))
                    if on_progress: on_progress(pct)
                except (ValueError, ZeroDivisionError):
                    pass
        process.wait()
    finally:
        if cancel_token:
            cancel_token.unregister_cleanup(process.terminate)

    if cancelled:
        dest.unlink(missing_ok=True)
        from avs.engine.cancel import CancelledError
        raise CancelledError()
    if timed_out:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Export timed out after {timeout}s for {dest.name}")
    if process.returncode != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError(
            f"Export failed ({dest.name}) — exit {process.returncode}"
        )


def _get_duration(path: Path) -> float | None:
    import json
    cmd = [
        config.FFPROBE_BIN, "-v", "quiet",
        "-print_format", "json", "-show_format", str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        return float(json.loads(result.stdout).get("format", {}).get("duration", 0))
    return None


