"""
Assembly pipeline (Pass 3): cut accepted mark segments, concatenate, apply
color grade, mix audio, encode a 1080p preview.

No LUT files required — grade is applied via FFmpeg eq/colorbalance filters.
Music and telemetry overlays are skipped until those assets exist.
"""

import subprocess
import tempfile
import webbrowser
from pathlib import Path

from rich.console import Console

from axedup import config
from axedup.models.db import get_session
from axedup.models.schema import Clip, Mark, Profile, Session
from axedup.presets.sports import DEFAULT_PROFILES

# FFmpeg eq/colorbalance filter string per grade style (None = no adjustment)
GRADE_FILTERS: dict[str, str | None] = {
    "punchy":    "eq=contrast=1.2:saturation=1.3:brightness=0.05",
    "cinematic": "eq=contrast=1.1:saturation=0.85:brightness=-0.05",
    "natural":   None,
    "warm":      "eq=saturation=1.1,colorbalance=rs=0.08:gs=0.02:bs=-0.08",
    "cool":      "colorbalance=rs=-0.08:gs=0.0:bs=0.12",
    "vibrant":   "eq=contrast=1.15:saturation=1.5",
}


def assemble_session(
    session_id: str,
    console: Console | None = None,
    remove_mark_ids: list[str] | None = None,
    swap_music: bool = False,
    grade_override: str | None = None,
    disable_overlay: bool = False,
) -> Path:
    """
    Assemble accepted marks into a preview video.
    Returns the path to the preview file.
    """
    _log = _logger(console)
    remove_mark_ids = set(remove_mark_ids or [])

    with get_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")

        clips = {c.id: c for c in db.query(Clip).filter(Clip.session_id == session_id).all()}

        marks = (
            db.query(Mark)
            .filter(Mark.clip_id.in_(clips.keys()))
            .filter(Mark.status == "accepted")
            .order_by(Mark.in_s)
            .all()
        )

        profile = db.query(Profile).filter(Profile.sport == session.sport).first()

    marks = [m for m in marks if m.id not in remove_mark_ids]
    if not marks:
        raise ValueError("No accepted marks found. Run 'review' first and accept some clips.")

    grade = grade_override or (profile.color_grade if profile else None) or "natural"
    _log(f"Assembling {len(marks)} clip(s) · grade: {grade}")

    # --- Stage 1: Cut each segment ---
    segment_paths: list[Path] = []
    for i, mark in enumerate(marks):
        clip = clips[mark.clip_id]
        seg_path = config.SEGMENT_DIR / f"{mark.id}.mp4"

        if seg_path.exists():
            _log(f"  segment {i+1}/{len(marks)} cached")
        else:
            _log(f"  cutting segment {i+1}/{len(marks)}: {mark.in_s:.1f}s – {mark.out_s:.1f}s")
            _cut_segment(Path(clip.filepath), mark.in_s, mark.out_s, seg_path)

        segment_paths.append(seg_path)

    # --- Stage 2: Concat + grade + encode ---
    preview_path = config.PREVIEW_DIR / f"{session_id}_preview.mp4"
    _log(f"Encoding preview …")
    _concat_and_encode(segment_paths, preview_path, grade, disable_overlay)

    # --- Update session status ---
    with get_session() as db:
        s = db.query(Session).filter(Session.id == session_id).first()
        s.status = "assembled"

    _log(f"[green]Preview ready:[/green] {preview_path}")
    _log(f"Opening with system video player …")
    _open_player(preview_path)

    return preview_path


# ---------------------------------------------------------------------------
# FFmpeg operations
# ---------------------------------------------------------------------------

def _cut_segment(source: Path, in_s: float, out_s: float, dest: Path) -> None:
    """Cut [in_s, out_s] from *source* using stream copy (fast, lossless)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        config.FFMPEG_BIN, "-y",
        "-ss", str(in_s),
        "-to", str(out_s),
        "-i", str(source),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(dest),
    ]
    _run(cmd, f"cutting segment from {source.name}")


def _concat_and_encode(
    segments: list[Path],
    dest: Path,
    grade: str,
    disable_overlay: bool,
) -> None:
    """
    Concatenate *segments*, apply color grade, encode to 1080p H.264.

    Uses a temporary concat list file and the ffmpeg concat demuxer.
    The grade filter is applied during the single encode pass.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Write concat list to a temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, dir=config.SEGMENT_DIR
    ) as f:
        concat_file = Path(f.name)
        for seg in segments:
            # ffmpeg concat demuxer requires escaped paths
            escaped = str(seg).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    grade_filter = GRADE_FILTERS.get(grade)
    vf = grade_filter if grade_filter and not disable_overlay else None

    cmd = [
        config.FFMPEG_BIN, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file),
    ]

    if vf:
        cmd += ["-vf", vf]

    # Always re-encode to H.264 for a consistent, reasonably-sized preview
    cmd += [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "22",
    ]

    cmd += [
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(dest),
    ]

    try:
        _run(cmd, "encoding preview")
    finally:
        concat_file.unlink(missing_ok=True)


def _run(cmd: list[str], description: str) -> None:
    result = subprocess.run(cmd, capture_output=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed ({description}):\n"
            + result.stderr.decode(errors="replace")[-2000:]
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_player(path: Path) -> None:
    """Open *path* in the system default video player."""
    import shutil, subprocess as sp
    for player in ("xdg-open", "vlc", "mpv", "totem"):
        if shutil.which(player):
            sp.Popen([player, str(path)])
            return


def _logger(console: Console | None):
    return console.log if console else print
