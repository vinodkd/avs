"""
Assembly pipeline (Pass 3): cut accepted mark segments, concatenate, apply
color grade, mix audio, encode a 1080p preview.

No LUT files required — grade is applied via FFmpeg eq/colorbalance filters.
Music and telemetry overlays are skipped until those assets exist.
"""

import hashlib
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from rich.console import Console

from axedup import config
from axedup.models.db import get_session
from axedup.models.schema import Clip, Mark, MarkStatus, Profile, Session, SessionStatus
from axedup.presets.sports import DEFAULT_PROFILES

# FFmpeg eq/colorbalance filter string per grade style (None = no adjustment).
# warm/cool shift midtones (rm/bm), not just shadows — action footage is mostly
# bright midtones, so shadow-only shifts are invisible on it.
GRADE_FILTERS: dict[str, str | None] = {
    "punchy":    "eq=contrast=1.25:saturation=1.35:brightness=0.04",
    "cinematic": "eq=contrast=1.15:saturation=0.7:brightness=-0.05:gamma=1.05",
    "natural":   None,
    "warm":      "eq=saturation=1.12,colorbalance=rm=0.18:gm=0.04:bm=-0.18:rs=0.08:bs=-0.08",
    "cool":      "eq=saturation=1.05,colorbalance=rm=-0.15:bm=0.22:rs=-0.05:bs=0.10",
    "vibrant":   "eq=contrast=1.12:saturation=1.8",
}


_SOURCE_MAP = {
    "proxy":     "motion_peak",
    "jpg":       "motion_peak_jpg",
    "telemetry": "telemetry_peak",
}


def _grade_tag(grade: str) -> str:
    """Short fingerprint of a grade's filter string — cache key component so
    tuned filters re-render instead of serving stale cached output."""
    return hashlib.md5((GRADE_FILTERS.get(grade) or "none").encode()).hexdigest()[:8]


def render_grade_swatches(source_jpg: Path, dest_dir: Path, prefix: str) -> dict[str, Path]:
    """Render *source_jpg* through each grade filter for side-by-side preview.

    Writes `{prefix}_grade_{grade}_{hash}.jpg` into *dest_dir* and returns
    {grade: path}. The filename carries a hash of the filter string, so a
    tuned filter re-renders instead of serving a stale cached swatch; swatches
    from older filter versions are deleted.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for grade, vf in GRADE_FILTERS.items():
        tag = _grade_tag(grade)
        dest = dest_dir / f"{prefix}_grade_{grade}_{tag}.jpg"
        (dest_dir / f"{prefix}_grade_{grade}.jpg").unlink(missing_ok=True)  # pre-hash name
        for stale in dest_dir.glob(f"{prefix}_grade_{grade}_*.jpg"):
            if stale != dest:
                stale.unlink(missing_ok=True)
        if not dest.exists():
            cmd = [config.FFMPEG_BIN, "-y", "-i", str(source_jpg)]
            if vf:
                cmd += ["-vf", vf]
            cmd += ["-frames:v", "1", "-q:v", "4", str(dest)]
            subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        out[grade] = dest
    return out


def assemble_session(
    session_id: str,
    console: Console | None = None,
    remove_mark_ids: list[str] | None = None,
    swap_music: bool = False,
    grade_override: str | None = None,
    disable_overlay: bool = False,
    source_filter: str | None = None,
    on_progress: Callable[[int, int], None] | None = None,
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

        def _mark_query(status_filter):
            q = (
                db.query(Mark)
                .join(Clip, Mark.clip_id == Clip.id)
                .filter(Mark.clip_id.in_(clips.keys()))
                .filter(status_filter)
            )
            if source_filter:
                db_source = _SOURCE_MAP.get(source_filter, source_filter)
                q = q.filter(Mark.source == db_source)
            return q.order_by(Clip.clip_order, Mark.in_s).all()

        marks = _mark_query(Mark.status == MarkStatus.ACCEPTED)
        if not marks:
            # User hasn't saved picks yet — use all candidates as-is
            marks = _mark_query(Mark.status == MarkStatus.CANDIDATE)

        profile = db.query(Profile).filter(Profile.sport == session.sport).first()

    marks = [m for m in marks if m.id not in remove_mark_ids]
    if not marks:
        raise ValueError("No marks found. Analysis may not have completed yet.")

    if not source_filter:
        sources_present = {m.source for m in marks}
        if len(sources_present) > 1:
            _log(
                f"[yellow]Warning: accepted marks from {len(sources_present)} sources "
                f"({', '.join(sorted(sources_present))}). "
                f"Use --source proxy|jpg|telemetry to pick one and avoid duplicates.[/yellow]"
            )

    grade = grade_override or (profile.color_grade if profile else None) or "natural"
    source_label = f" · source: {source_filter}" if source_filter else ""
    _log(f"Assembling {len(marks)} clip(s) · grade: {grade}{source_label}")

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

    # --- Stage 2: Encode each segment in parallel with grade ---
    encoded_dir = config.SEGMENT_DIR / "encoded"
    encoded_dir.mkdir(parents=True, exist_ok=True)
    # Cache key includes grade + filter hash: the grade is baked into the encode,
    # so a different (or retuned) grade must not reuse these files.
    grade_tag = "nograde" if disable_overlay else _grade_tag(grade)
    encoded_paths = []
    for mark in marks:
        enc = encoded_dir / f"{mark.id}_{grade}_{grade_tag}.mp4"
        (encoded_dir / f"{mark.id}.mp4").unlink(missing_ok=True)  # pre-hash name
        for stale in encoded_dir.glob(f"{mark.id}_*.mp4"):
            if stale != enc:
                stale.unlink(missing_ok=True)
        encoded_paths.append(enc)
    total_segs = len(marks)

    _log(f"Encoding {total_segs} segment(s) …")
    if on_progress: on_progress(0, total_segs)
    done_count = [0]
    futures = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        for seg, enc in zip(segment_paths, encoded_paths):
            if enc.exists() and _is_valid_video(enc):
                done_count[0] += 1
                if on_progress: on_progress(done_count[0], total_segs)
            else:
                enc.unlink(missing_ok=True)
                futures[executor.submit(_encode_segment, seg, enc, grade, disable_overlay)] = enc
        for future in as_completed(futures):
            future.result()
            done_count[0] += 1
            if on_progress: on_progress(done_count[0], total_segs)

    # --- Stage 3: Fast concat of encoded segments ---
    preview_path = config.PREVIEW_DIR / f"{session_id}_preview.mp4"
    _log("Concatenating segments …")
    _concat_copy(encoded_paths, preview_path)

    # --- Update session status ---
    with get_session() as db:
        s = db.query(Session).filter(Session.id == session_id).first()
        s.status = SessionStatus.ASSEMBLED

    _log(f"[green]Preview ready:[/green] {preview_path}")

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


def _encode_segment(seg: Path, dest: Path, grade: str, disable_overlay: bool = False) -> None:
    """Encode one segment with color grade applied."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    duration = _get_segment_duration(seg) or 0
    timeout = max(600, int(duration * 60))  # 4K medium preset can be very slow on CPU
    grade_filter = GRADE_FILTERS.get(grade)
    vf = grade_filter if grade_filter and not disable_overlay else None
    cmd = [config.FFMPEG_BIN, "-y", "-i", str(seg)]
    if vf:
        cmd += ["-vf", vf]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        str(dest),
    ]
    _run(cmd, f"encoding {seg.name}", timeout=timeout)


def _concat_copy(encoded: list[Path], dest: Path) -> None:
    """Lossless concat of already-encoded segments."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, dir=config.SEGMENT_DIR
    ) as f:
        concat_file = Path(f.name)
        for p in encoded:
            escaped = str(p).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
    cmd = [
        config.FFMPEG_BIN, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(dest),
    ]
    try:
        _run(cmd, "concat", timeout=120)
    finally:
        concat_file.unlink(missing_ok=True)


def _is_valid_video(path: Path) -> bool:
    try:
        r = subprocess.run(
            [config.FFPROBE_BIN, "-v", "error", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0 and float(r.stdout.strip() or 0) > 0
    except Exception:
        return False


def _get_segment_duration(path: Path) -> float | None:
    """Return duration in seconds for *path* via ffprobe, or None on failure."""
    try:
        r = subprocess.run(
            [config.FFPROBE_BIN, "-v", "error", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            val = float(r.stdout.strip() or 0)
            return val if val > 0 else None
    except Exception:
        pass
    return None


def _run(cmd: list[str], description: str, timeout: int = 600) -> None:
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
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
