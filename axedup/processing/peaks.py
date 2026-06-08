"""
Candidate mark generation from motion intensity (and telemetry when available).

Finds local maxima in the combined signal, expands each peak into a clip region
with pre/post padding, merges overlapping regions, and writes Mark rows to the DB.
"""

from axedup.models.db import get_session
from axedup.models.schema import Clip, Mark, MarkStatus, Profile, Session, TelemetryPoint
from axedup.presets.sports import DEFAULT_PROFILES

PRE_PADDING_S = 2.0
POST_PADDING_S = 5.0
MIN_PEAK_DISTANCE_S = 4.0

_NOOP = lambda *_: None


def detect_peaks(
    session_id: str,
    on_event=None,
    motion_method: str = "proxy",
) -> int:
    """
    Generate candidate Mark rows for every clip in *session_id*.
    Returns total number of candidates created.

    motion_method: 'proxy' uses motion_intensity; 'jpg' uses motion_intensity_quick.
    Marks are tagged 'motion_peak' or 'motion_peak_jpg' accordingly.
    on_event: same OnEvent callback as analyze_session — fires per-clip done events.
    """
    _notify = on_event or _NOOP

    with get_session() as db:
        session = db.query(Session).filter(Session.id == session_id).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")

        profile = db.query(Profile).filter(Profile.sport == session.sport).first()
        motion_threshold = (
            profile.motion_threshold
            if profile and profile.motion_threshold is not None
            else DEFAULT_PROFILES.get(session.sport, {}).get("motion_threshold", 0.5)
        )

        clips = (
            db.query(Clip)
            .filter(Clip.session_id == session_id)
            .order_by(Clip.clip_order)
            .all()
        )

    total = 0
    for clip in clips:
        n = _detect_clip_peaks(clip, motion_threshold, motion_method)
        _notify(clip.id, 'peaks', 'done', f"{clip.filename}: {n} candidate(s)", None, None)
        total += n

    return total


# ---------------------------------------------------------------------------
# Per-clip peak detection
# ---------------------------------------------------------------------------

def _detect_clip_peaks(clip: Clip, motion_threshold: float, motion_method: str = "proxy") -> int:
    """Find peaks in this clip's motion signal and write Mark candidates."""
    source = "motion_peak_jpg" if motion_method == "jpg" else "motion_peak"

    with get_session() as db:
        db.query(Mark).filter(
            Mark.clip_id == clip.id,
            Mark.source == source,
        ).delete()

        if motion_method == "jpg":
            rows = (
                db.query(TelemetryPoint)
                .filter(TelemetryPoint.clip_id == clip.id)
                .filter(TelemetryPoint.motion_intensity_quick.isnot(None))
                .order_by(TelemetryPoint.timestamp_s)
                .all()
            )
            intensities = [r.motion_intensity_quick for r in rows]
        else:
            rows = (
                db.query(TelemetryPoint)
                .filter(TelemetryPoint.clip_id == clip.id)
                .filter(TelemetryPoint.motion_intensity.isnot(None))
                .order_by(TelemetryPoint.timestamp_s)
                .all()
            )
            intensities = [r.motion_intensity for r in rows]

    if not rows:
        return 0

    timestamps = [r.timestamp_s for r in rows]
    peak_indices = _find_peaks(intensities, timestamps, motion_threshold)
    if not peak_indices:
        return 0

    regions = _peaks_to_regions(peak_indices, timestamps, intensities, clip.duration_s)
    regions = _merge_overlapping(regions)

    marks = [
        Mark(
            clip_id=clip.id,
            in_s=in_s,
            out_s=out_s,
            score=round(score, 4),
            source=source,
            status=MarkStatus.CANDIDATE,
        )
        for in_s, out_s, score in regions
    ]

    with get_session() as db:
        db.add_all(marks)

    return len(marks)


# ---------------------------------------------------------------------------
# Signal processing
# ---------------------------------------------------------------------------

def _find_peaks(
    values: list[float],
    timestamps: list[float],
    threshold: float,
    min_distance_s: float = MIN_PEAK_DISTANCE_S,
) -> list[int]:
    if len(values) < 3:
        return []

    candidates = []
    for i in range(1, len(values) - 1):
        if values[i] >= threshold and values[i] >= values[i - 1] and values[i] >= values[i + 1]:
            candidates.append(i)

    if not candidates:
        return []

    kept = [candidates[0]]
    for idx in candidates[1:]:
        if timestamps[idx] - timestamps[kept[-1]] >= min_distance_s:
            kept.append(idx)
        elif values[idx] > values[kept[-1]]:
            kept[-1] = idx

    return kept


def _peaks_to_regions(
    peak_indices: list[int],
    timestamps: list[float],
    intensities: list[float],
    clip_duration_s: float,
) -> list[tuple[float, float, float]]:
    regions = []
    for idx in peak_indices:
        t = timestamps[idx]
        in_s  = max(0.0, t - PRE_PADDING_S)
        out_s = min(clip_duration_s, t + POST_PADDING_S)
        score = intensities[idx]
        regions.append((in_s, out_s, score))
    return regions


def _merge_overlapping(
    regions: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    if not regions:
        return []

    sorted_regions = sorted(regions, key=lambda r: r[0])
    merged = [list(sorted_regions[0])]

    for in_s, out_s, score in sorted_regions[1:]:
        prev = merged[-1]
        if in_s <= prev[1]:
            prev[1] = max(prev[1], out_s)
            prev[2] = max(prev[2], score)
        else:
            merged.append([in_s, out_s, score])

    return [(r[0], r[1], r[2]) for r in merged]
