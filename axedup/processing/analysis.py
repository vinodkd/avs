"""
Analysis pipeline: proxy generation, thumbnail extraction, scene detection, motion intensity.

All heavy work runs on 480p proxy files — originals on the SD card are only read once
(during proxy generation). After that the SD card can be removed.
"""

import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector

from axedup import config
from axedup.models.db import get_session
from axedup.models.schema import Clip, Profile, Session, TelemetryPoint


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze_session(session_id: str, console: Console | None = None) -> None:
    """Run the full analysis pipeline for every clip in *session_id*."""
    _log = _logger(console)

    with get_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")
        clips = (
            db.query(Clip)
            .filter(Clip.session_id == session_id)
            .order_by(Clip.clip_order)
            .all()
        )
        profile = db.query(Profile).filter(Profile.sport == session.sport).first()
        session.status = "analyzing"

    _log(f"Analyzing {len(clips)} clip(s) …")

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        overall = progress.add_task("clips", total=len(clips))

        for clip in clips:
            progress.update(overall, description=f"{clip.filename}")
            _analyze_clip(clip, progress, console, profile)
            progress.advance(overall)

    # Peak detection runs after all clips are analysed
    from axedup.processing.peaks import detect_peaks
    _log("Detecting candidate marks …")
    total_candidates = detect_peaks(session_id, console=console)
    _log(f"[green]{total_candidates} candidate mark(s) generated.[/green]")

    with get_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        session.status = "ready"

    _log("[green]Analysis complete.[/green]")


# ---------------------------------------------------------------------------
# Per-clip pipeline
# ---------------------------------------------------------------------------

def _analyze_clip(clip: Clip, progress: Progress, console: Console | None, profile: Profile | None = None) -> None:
    _log = _logger(console)

    # --- Stage 1: Proxy ---
    proxy_path = config.PROXY_DIR / f"{clip.id}.mp4"
    if proxy_path.exists() and _is_valid_video(proxy_path):
        _log(f"  [dim]proxy exists, skipping generation[/dim]")
    else:
        if proxy_path.exists():
            _log(f"  [yellow]corrupt proxy found, regenerating …[/yellow]")
            proxy_path.unlink()
        else:
            _log(f"  generating proxy …")
        _generate_proxy(Path(clip.filepath), proxy_path, duration_s=clip.duration_s, progress=progress)

    # --- Stage 2: Thumbnails ---
    thumb_dir = config.THUMB_DIR / clip.id
    thumb_dir.mkdir(parents=True, exist_ok=True)
    existing_thumbs = list(thumb_dir.glob("*.jpg"))
    if existing_thumbs:
        _log(f"  [dim]{len(existing_thumbs)} thumbnails exist, skipping[/dim]")
    else:
        _log(f"  extracting thumbnails …")
        count = _extract_thumbnails(proxy_path, thumb_dir)
        _log(f"  {count} thumbnails saved")

    # --- Stage 3: Scene detection (always re-runs; fast, threshold may change) ---
    _log(f"  detecting scenes …")
    scenes = _detect_scenes(proxy_path, profile)
    _log(f"  {len(scenes)} scene(s) detected")

    # --- Stage 4: Motion intensity (optical flow) — skip if already computed ---
    with get_session() as db:
        existing = db.query(TelemetryPoint).filter(TelemetryPoint.clip_id == clip.id).count()
    if existing:
        _log(f"  [dim]{existing} motion samples exist, skipping[/dim]")
        with get_session() as db:
            motion_points = [
                (t.timestamp_s, t.motion_intensity)
                for t in db.query(TelemetryPoint).filter(TelemetryPoint.clip_id == clip.id).all()
                if t.motion_intensity is not None
            ]
    else:
        _log(f"  computing motion intensity …")
        motion_points = _compute_motion(proxy_path, progress=progress)
        _log(f"  {len(motion_points)} motion samples computed")

    # --- Write results to DB ---
    peak_motion = max((m for _, m in motion_points), default=None)

    with get_session() as db:
        c = db.query(Clip).filter(Clip.id == clip.id).first()
        c.proxy_path = str(proxy_path)
        c.scene_count = len(scenes)
        c.peak_motion = peak_motion

        if not existing:
            db.add_all([
                TelemetryPoint(
                    clip_id=clip.id,
                    timestamp_s=ts,
                    motion_intensity=intensity,
                )
                for ts, intensity in motion_points
            ])


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

def _is_valid_video(path: Path) -> bool:
    """Return True if ffprobe can read a valid duration from *path*."""
    try:
        result = subprocess.run(
            [config.FFPROBE_BIN, "-v", "error", "-show_entries",
             "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
             str(path)],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0 and float(result.stdout.strip() or 0) > 0
    except Exception:
        return False


def _generate_proxy(source: Path, dest: Path, duration_s: float = 0, progress: Progress | None = None) -> None:
    """Transcode *source* to a 480p H.264 proxy at *dest*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    timeout = max(600, int(duration_s * 4))
    cmd = [
        config.FFMPEG_BIN,
        "-y",
        "-threads", "0",
        "-i", str(source),
        "-vf", "scale=-2:480",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "28",
        "-threads", "0",
        "-c:a", "aac",
        "-b:a", "64k",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        "-nostats",
        str(dest),
    ]

    task_id = None
    if progress and duration_s:
        task_id = progress.add_task("  proxy", total=100)

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    deadline = time.time() + timeout
    timed_out = False
    try:
        for line in process.stdout:
            if time.time() > deadline:
                timed_out = True
                process.kill()
                break
            if task_id is not None and line.startswith("out_time_ms="):
                try:
                    out_ms = int(line.split("=", 1)[1].strip())
                    pct = min(100, int(out_ms / (duration_s * 1_000_000) * 100))
                    progress.update(task_id, completed=pct)
                except (ValueError, ZeroDivisionError):
                    pass
        process.wait()
    finally:
        if task_id is not None:
            progress.remove_task(task_id)

    if timed_out:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Proxy generation timed out after {timeout}s for {source.name}")
    if process.returncode != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Proxy generation failed for {source.name} (exit {process.returncode})")


def _extract_thumbnails(proxy_path: Path, thumb_dir: Path) -> int:
    """Extract one JPEG every THUMB_INTERVAL seconds from *proxy_path*."""
    cmd = [
        config.FFMPEG_BIN,
        "-y",
        "-i", str(proxy_path),
        "-vf", f"fps=1/{config.THUMB_INTERVAL}",
        "-q:v", "3",                   # JPEG quality (2=best, 31=worst)
        str(thumb_dir / "%04d.jpg"),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(
            f"Thumbnail extraction failed:\n"
            + result.stderr.decode(errors="replace")
        )
    return len(list(thumb_dir.glob("*.jpg")))


def _detect_scenes(proxy_path: Path, profile: Profile | None = None) -> list[tuple[float, float]]:
    """Return a list of (start_s, end_s) scene tuples using PySceneDetect."""
    from scenedetect.detectors import AdaptiveDetector, ThresholdDetector

    detector_name = profile.scene_detector if profile else "content"
    threshold = (profile.scene_threshold if profile and profile.scene_threshold is not None
                 else config.SCENE_THRESHOLD)
    min_scene_len = (profile.scene_min_scene_len if profile and profile.scene_min_scene_len is not None
                     else 15)

    try:
        video = open_video(str(proxy_path))
        scene_manager = SceneManager()

        if detector_name == "adaptive":
            scene_manager.add_detector(AdaptiveDetector(
                adaptive_threshold=threshold,
                min_scene_len=min_scene_len,
            ))
        elif detector_name == "threshold":
            scene_manager.add_detector(ThresholdDetector(threshold=threshold))
        else:
            scene_manager.add_detector(ContentDetector(
                threshold=threshold,
                min_scene_len=min_scene_len,
            ))

        scene_manager.detect_scenes(video, show_progress=False)
        scenes = scene_manager.get_scene_list()
        return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]
    except Exception:
        return []


def _compute_motion(proxy_path: Path, progress: Progress | None = None) -> list[tuple[float, float]]:
    """
    Compute per-sample motion intensity using dense optical flow (Farneback).

    Samples every OPTICAL_FLOW_SAMPLE_INTERVAL seconds on the 480p proxy.
    Returns list of (timestamp_s, motion_intensity) — intensity is mean
    magnitude of the flow field, normalised to roughly [0, 1].
    """
    cap = cv2.VideoCapture(str(proxy_path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open proxy: {proxy_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_every = max(1, int(fps * config.OPTICAL_FLOW_SAMPLE_INTERVAL))

    task_id = None
    if progress and total_frames:
        task_id = progress.add_task("  motion", total=total_frames)

    results: list[tuple[float, float]] = []
    prev_gray: np.ndarray | None = None
    frame_idx = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % sample_every == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

                if prev_gray is not None:
                    flow = cv2.calcOpticalFlowFarneback(
                        prev_gray, gray, None,
                        pyr_scale=0.5,
                        levels=3,
                        winsize=15,
                        iterations=3,
                        poly_n=5,
                        poly_sigma=1.2,
                        flags=0,
                    )
                    magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
                    intensity = float(np.mean(magnitude)) / 20.0
                    intensity = min(intensity, 1.0)
                    timestamp_s = frame_idx / fps
                    results.append((round(timestamp_s, 3), round(intensity, 4)))

                prev_gray = gray

            if task_id is not None:
                progress.update(task_id, completed=frame_idx)
            frame_idx += 1
    finally:
        cap.release()
        if task_id is not None:
            progress.remove_task(task_id)

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _logger(console: Console | None):
    return console.log if console else print
