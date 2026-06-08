"""
Scan a folder for action camera footage and create a Session with Clip records.

Currently tested with: Insta360 flat cameras (Ace Pro, GO 3).
GoPro chapter grouping and DJI SRT detection are stubbed for later.
"""

import json
import re
import subprocess
import uuid
from pathlib import Path

from rich.console import Console

from axedup import config
from axedup.models.db import get_session
from axedup.models.schema import Clip, Session, SessionStatus

VIDEO_SUFFIXES = {".mp4", ".mov"}
MIN_DURATION_S = 5.0


def ingest_folder(
    source: Path,
    sport: str,
    console: Console | None = None,
    files: list[Path] | None = None,
) -> Session:
    """
    Scan *source* for video files and write a Session + Clips to the DB.

    If *files* is given, only those specific files are imported (source is still
    recorded as the session root for reference). If *source* is a single file,
    only that file is imported. Otherwise the whole folder is scanned.
    Returns the persisted Session.
    """
    _log = _logger(console)

    if files is not None:
        video_files = [f for f in files if f.suffix.lower() in VIDEO_SUFFIXES]
        _log(f"Importing {len(video_files)} selected file(s)")
    elif source.is_file():
        if source.suffix.lower() not in VIDEO_SUFFIXES:
            raise ValueError(f"{source.name} is not a supported video file")
        video_files = [source]
        _log(f"Single file: {source.name}")
    else:
        video_files = _scan(source, _log)
    if not video_files:
        raise ValueError(f"No video files found in {source}")

    session_id = str(uuid.uuid4())
    clips = []
    camera_votes: dict[str, int] = {}

    for order, filepath in enumerate(video_files):
        try:
            probe = _probe(filepath)
        except Exception as exc:
            _log(f"[yellow]Skipping {filepath.name}: {exc}[/yellow]")
            continue

        duration = float(probe.get("format", {}).get("duration", 0))
        if duration < MIN_DURATION_S:
            _log(f"[dim]Skipping {filepath.name}: {duration:.1f}s (too short)[/dim]")
            continue

        camera = _detect_camera(filepath, probe)
        camera_votes[camera] = camera_votes.get(camera, 0) + 1

        vid = _video_stream(probe)
        clips.append(Clip(
            id=str(uuid.uuid4()),
            session_id=session_id,
            filename=filepath.name,
            filepath=str(filepath),
            duration_s=duration,
            width=vid.get("width"),
            height=vid.get("height"),
            fps=_parse_fps(vid.get("r_frame_rate", "0/1")),
            codec=vid.get("codec_name"),
            has_telemetry=_has_srt_sidecar(filepath),
            clip_order=order,
        ))
        _log(f"  [green]✓[/green] {filepath.name}  {duration:.1f}s  {camera}")

    if not clips:
        raise ValueError("No usable clips found (all skipped or too short)")

    dominant_camera = max(camera_votes, key=lambda k: camera_votes[k]) if camera_votes else "unknown"

    session = Session(
        id=session_id,
        source_path=str(source),
        sport=sport,
        camera=dominant_camera,
        total_clips=len(clips),
        total_duration_s=sum(c.duration_s for c in clips),
        status=SessionStatus.INGESTED,
    )

    with get_session() as db:
        db.add(session)
        for clip in clips:
            db.add(clip)

    return session


def _scan(source: Path, log) -> list[Path]:
    """Return sorted list of video files, skipping GoPro proxy/thumbnail files."""
    files = [
        p for p in sorted(source.rglob("*"))
        if p.is_file()
        and p.suffix.lower() in VIDEO_SUFFIXES
        and p.suffix.lower() not in {".lrv", ".thm"}
        and not p.stem.upper().startswith("LRV_")
    ]
    log(f"Scanned {source}: {len(files)} video file(s)")
    return files


def _probe(filepath: Path) -> dict:
    """Run ffprobe on *filepath* and return parsed JSON."""
    cmd = [
        config.FFPROBE_BIN, "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(filepath),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise RuntimeError(
            f"ffprobe not found ('{config.FFPROBE_BIN}'). "
            "Install with: sudo apt install ffmpeg"
        )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def _video_stream(probe: dict) -> dict:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    return {}


def _parse_fps(r_frame_rate: str) -> float:
    try:
        num, den = r_frame_rate.split("/")
        return round(int(num) / int(den), 3)
    except Exception:
        return 0.0


def _detect_camera(filepath: Path, probe: dict) -> str:
    """Detect brand from filename patterns, then MP4 container tags."""
    name = filepath.name.upper()

    # GoPro patterns — detected but chapter grouping deferred until GoPro footage available
    if re.match(r"G[HX]\d{6}", name) or name.startswith("GOPR") or re.match(r"GP\d{6}", name):
        return "gopro"

    if name.startswith("DJI_"):
        return "dji"

    # Insta360 flat cameras export files named VID_YYYYMMDD_HHMMSS_XX.MP4
    if name.startswith("VID_") or name.startswith("PRO_VID"):
        return "insta360"

    # Fall back to MP4 container metadata
    tags = probe.get("format", {}).get("tags", {})
    make = (
        tags.get("com.apple.quicktime.make")
        or tags.get("make")
        or tags.get("Make")
        or ""
    ).lower()

    if "gopro" in make:
        return "gopro"
    if "dji" in make:
        return "dji"
    if "insta360" in make or "arashi" in make:
        return "insta360"

    return "unknown"


def _has_srt_sidecar(filepath: Path) -> bool:
    """Check for a DJI .SRT telemetry sidecar alongside the video."""
    return filepath.with_suffix(".SRT").exists() or filepath.with_suffix(".srt").exists()


def _logger(console: Console | None):
    return console.log if console else print
