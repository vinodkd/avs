"""
Analysis pipeline: proxy generation, thumbnail extraction, scene detection, motion intensity.

All heavy work runs on 480p proxy files — originals on the SD card are only read once
(during proxy generation). After that the SD card can be removed.
"""

import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from scenedetect import SceneManager, open_video
from scenedetect.detectors import ContentDetector

from axedup import config
from axedup.models.db import get_session
from axedup.models.schema import Clip, Profile, Session, SessionStatus, TelemetryPoint

# Event callback type:
#   clip_id:   str | None  — None = session-level event
#   stage:     str         — 'proxy'|'thumbnails'|'scenes'|'motion'|'peaks'|'session'
#   status:    str         — 'running'|'done'|'skipped'|'progress'|'error'
#   message:   str | None  — human-readable log text
#   completed: int | None  — progress numerator  (only when status='progress')
#   total:     int | None  — progress denominator (only when status='progress')
OnEvent = Callable[[str | None, str, str, str | None, int | None, int | None], None]

_NOOP: OnEvent = lambda *_: None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze_session(
    session_id: str,
    motion_method: str = "proxy",
    on_event: OnEvent | None = None,
) -> None:
    """Run the full analysis pipeline for every clip in *session_id*.

    motion_method: 'proxy' (default) — dense optical flow on proxy video;
                   'jpg'             — faster JPEG frame extraction path.
    on_event: optional event callback (see OnEvent alias above).
    """
    _notify = on_event or _NOOP

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
        session.status = SessionStatus.ANALYZING

    _notify(None, 'session', 'running',
            f"Analyzing {len(clips)} clip(s) [{motion_method} method]",
            0, len(clips))

    for i, clip in enumerate(clips):
        _analyze_clip(clip, profile, motion_method, _notify)
        _notify(None, 'session', 'progress', None, i + 1, len(clips))

    from axedup.processing.peaks import detect_peaks
    _notify(None, 'peaks', 'running', "Detecting candidate marks…", None, None)
    total_candidates = detect_peaks(session_id, on_event=on_event, motion_method=motion_method)
    _notify(None, 'peaks', 'done', f"{total_candidates} candidate mark(s) generated.", None, None)

    with get_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        session.status = SessionStatus.READY

    _notify(None, 'session', 'done', "Analysis complete.", None, None)


# ---------------------------------------------------------------------------
# Per-clip pipeline
# ---------------------------------------------------------------------------

def _analyze_clip(
    clip: Clip,
    profile: Profile | None = None,
    motion_method: str = "proxy",
    on_event: OnEvent | None = None,
) -> None:
    _notify = on_event or _NOOP

    # --- Stage 1: Proxy (always needed; both motion methods need it for thumbnails/scenes) ---
    proxy_path = config.PROXY_DIR / f"{clip.id}.mp4"
    if proxy_path.exists() and _is_valid_video(proxy_path):
        _notify(clip.id, "proxy", "skipped", f"{clip.filename}: proxy exists", None, None)
    else:
        if proxy_path.exists():
            proxy_path.unlink()
        _notify(clip.id, "proxy", "running", f"{clip.filename}: generating proxy", None, 100)

        def _proxy_prog(done: int, total: int) -> None:
            _notify(clip.id, "proxy", "progress", None, done, total)

        _generate_proxy(Path(clip.filepath), proxy_path, duration_s=clip.duration_s, on_progress=_proxy_prog)
        _notify(clip.id, "proxy", "done", None, None, None)

    # --- Stage 2: Thumbnails ---
    thumb_dir = config.THUMB_DIR / clip.id
    thumb_dir.mkdir(parents=True, exist_ok=True)
    existing_thumbs = list(thumb_dir.glob("*.jpg"))
    if existing_thumbs:
        _notify(clip.id, "thumbnails", "skipped",
                f"{clip.filename}: {len(existing_thumbs)} thumbnails exist", None, None)
    else:
        _notify(clip.id, "thumbnails", "running", f"{clip.filename}: extracting thumbnails", None, None)
        count = _extract_thumbnails(proxy_path, thumb_dir, duration_s=clip.duration_s)
        _notify(clip.id, "thumbnails", "done", f"{clip.filename}: {count} thumbnails", None, None)

    # --- Stage 3: Scene detection ---
    _notify(clip.id, "scenes", "running", f"{clip.filename}: detecting scenes", None, None)
    scenes = _detect_scenes(proxy_path, profile)
    _notify(clip.id, "scenes", "done", f"{clip.filename}: {len(scenes)} scene(s)", None, None)

    # --- Stage 4: Motion intensity ---
    if motion_method == "jpg":
        _notify(clip.id, "motion", "running", f"{clip.filename}: computing motion (jpg)", None, None)

        def _motion_jpg_prog(done: int, total: int) -> None:
            _notify(clip.id, "motion", "progress", None, done, total)

        motion_points = _compute_motion_jpeg(proxy_path, on_progress=_motion_jpg_prog, duration_s=clip.duration_s)
        _notify(clip.id, "motion", "done", f"{clip.filename}: {len(motion_points)} samples (jpg)", None, None)

        with get_session() as db:
            db.query(TelemetryPoint).filter(
                TelemetryPoint.clip_id == clip.id,
                TelemetryPoint.motion_intensity.is_(None),
            ).delete()
            db.add_all([
                TelemetryPoint(clip_id=clip.id, timestamp_s=ts, motion_intensity_quick=intensity)
                for ts, intensity in motion_points
            ])

        with get_session() as db:
            c = db.query(Clip).filter(Clip.id == clip.id).first()
            c.proxy_path = str(proxy_path)
            c.scene_count = len(scenes)

    else:
        with get_session() as db:
            existing = db.query(TelemetryPoint).filter(
                TelemetryPoint.clip_id == clip.id,
                TelemetryPoint.motion_intensity.isnot(None),
            ).count()

        if existing:
            _notify(clip.id, "motion", "skipped",
                    f"{clip.filename}: {existing} proxy motion samples exist", None, None)
            with get_session() as db:
                motion_points = [
                    (t.timestamp_s, t.motion_intensity)
                    for t in db.query(TelemetryPoint).filter(TelemetryPoint.clip_id == clip.id).all()
                    if t.motion_intensity is not None
                ]
        else:
            _notify(clip.id, "motion", "running", f"{clip.filename}: computing motion (optical flow)", None, None)

            def _motion_proxy_prog(done: int, total: int) -> None:
                _notify(clip.id, "motion", "progress", None, done, total)

            motion_points = _compute_motion(proxy_path, on_progress=_motion_proxy_prog)
            _notify(clip.id, "motion", "done", f"{clip.filename}: {len(motion_points)} samples", None, None)

        peak_motion = max((m for _, m in motion_points), default=None)

        with get_session() as db:
            c = db.query(Clip).filter(Clip.id == clip.id).first()
            c.proxy_path = str(proxy_path)
            c.scene_count = len(scenes)
            c.peak_motion = peak_motion
            if not existing:
                db.add_all([
                    TelemetryPoint(clip_id=clip.id, timestamp_s=ts, motion_intensity=intensity)
                    for ts, intensity in motion_points
                ])


# ---------------------------------------------------------------------------
# Stage implementations
# ---------------------------------------------------------------------------

def _is_valid_video(path: Path) -> bool:
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


def _generate_proxy(
    source: Path,
    dest: Path,
    duration_s: float = 0,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Transcode *source* to a 480p H.264 proxy at *dest*."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    timeout = max(600, int(duration_s * 4))
    cmd = [
        config.FFMPEG_BIN,
        "-y", "-threads", "0",
        "-i", str(source),
        "-vf", "scale=-2:480",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-threads", "0",
        "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(dest),
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    deadline = time.time() + timeout
    timed_out = False
    try:
        for line in process.stdout:
            if time.time() > deadline:
                timed_out = True
                process.kill()
                break
            if on_progress and duration_s and line.startswith("out_time_ms="):
                try:
                    out_ms = int(line.split("=", 1)[1].strip())
                    pct = min(100, int(out_ms / (duration_s * 1_000_000) * 100))
                    on_progress(pct, 100)
                except (ValueError, ZeroDivisionError):
                    pass
        process.wait()
    finally:
        pass

    if timed_out:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Proxy generation timed out after {timeout}s for {source.name}")
    if process.returncode != 0:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Proxy generation failed for {source.name} (exit {process.returncode})")


def _extract_thumbnails(proxy_path: Path, thumb_dir: Path, duration_s: float = 0) -> int:
    timeout = max(300, int(duration_s * 2))
    cmd = [
        config.FFMPEG_BIN, "-y",
        "-i", str(proxy_path),
        "-vf", f"fps=1/{config.THUMB_INTERVAL}",
        "-q:v", "3",
        str(thumb_dir / "%04d.jpg"),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            "Thumbnail extraction failed:\n"
            + result.stderr.decode(errors="replace")
        )
    return len(list(thumb_dir.glob("*.jpg")))


def _detect_scenes(proxy_path: Path, profile: Profile | None = None) -> list[tuple[float, float]]:
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
                adaptive_threshold=threshold, min_scene_len=min_scene_len))
        elif detector_name == "threshold":
            scene_manager.add_detector(ThresholdDetector(threshold=threshold))
        else:
            scene_manager.add_detector(ContentDetector(
                threshold=threshold, min_scene_len=min_scene_len))

        scene_manager.detect_scenes(video, show_progress=False)
        scenes = scene_manager.get_scene_list()
        return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]
    except Exception:
        return []


def _compute_motion(
    proxy_path: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[float, float]]:
    """Dense optical flow (Farneback) on proxy. Returns (timestamp_s, intensity) pairs."""
    cap = cv2.VideoCapture(str(proxy_path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open proxy: {proxy_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_every = max(1, int(fps * config.OPTICAL_FLOW_SAMPLE_INTERVAL))

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
                        pyr_scale=0.5, levels=3, winsize=15,
                        iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
                    )
                    magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
                    intensity = min(float(np.mean(magnitude)) / 20.0, 1.0)
                    results.append((round(frame_idx / fps, 3), round(intensity, 4)))
                prev_gray = gray

            if on_progress and total_frames:
                on_progress(frame_idx, total_frames)
            frame_idx += 1
    finally:
        cap.release()

    return results


def _compute_motion_jpeg(
    proxy_path: Path,
    on_progress: Callable[[int, int], None] | None = None,
    duration_s: float = 0,
) -> list[tuple[float, float]]:
    """JPEG-frame motion intensity — sparse sampling, ~15× faster than optical flow."""
    sample_fps = 1.0 / config.OPTICAL_FLOW_SAMPLE_INTERVAL
    frame_dir = config.JPEG_FRAMES_DIR / proxy_path.stem
    frame_dir.mkdir(parents=True, exist_ok=True)
    extraction_timeout = max(300, int(duration_s * 2))

    try:
        cmd = [
            config.FFMPEG_BIN, "-y",
            "-i", str(proxy_path),
            "-vf", f"fps={sample_fps}",
            "-q:v", "5",
            str(frame_dir / "%06d.jpg"),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=extraction_timeout)
        if result.returncode != 0:
            raise RuntimeError("JPEG frame extraction failed:\n"
                               + result.stderr.decode(errors="replace")[-1000:])

        frames = sorted(frame_dir.glob("*.jpg"))
        total = len(frames)
        results: list[tuple[float, float]] = []
        prev_gray: np.ndarray | None = None

        for i, frame_path in enumerate(frames):
            gray = cv2.imread(str(frame_path), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                continue
            if prev_gray is not None:
                flow = cv2.calcOpticalFlowFarneback(
                    prev_gray, gray, None,
                    pyr_scale=0.5, levels=3, winsize=15,
                    iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
                )
                magnitude = np.sqrt(flow[..., 0] ** 2 + flow[..., 1] ** 2)
                intensity = min(float(np.mean(magnitude)) / 20.0, 1.0)
                timestamp_s = (i + 1) * config.OPTICAL_FLOW_SAMPLE_INTERVAL
                results.append((round(timestamp_s, 3), round(intensity, 4)))
            prev_gray = gray
            if on_progress and total:
                on_progress(i + 1, total)

        return results

    finally:
        shutil.rmtree(frame_dir, ignore_errors=True)
