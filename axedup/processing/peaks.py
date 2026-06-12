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


# ---------------------------------------------------------------------------
# Boring-region detection
# ---------------------------------------------------------------------------

BORING_SOURCE = "boring_motion"


def detect_boring_regions(
    session_id: str,
    on_event=None,
    motion_method: str = "proxy",
) -> int:
    """
    Flag sustained low-motion spans as Mark rows with status=BORING.

    Reads the same motion series peak detection uses — no new video processing.
    Thresholds come from global app settings (axedup/prefs.py):
      boring_threshold_pct — dull = smoothed motion < pct% of the sport's
                             motion_threshold
      boring_min_s         — dull stretches shorter than this are ignored
      boring_gap_s         — blips above the line shorter than this don't
                             break a region
    Spans overlapping any non-boring mark are cut around it: found highlights
    always win. Returns the number of boring marks created.
    """
    from axedup.prefs import get_prefs

    _notify = on_event or _NOOP
    prefs = get_prefs()
    pct   = float(prefs.get("boring_threshold_pct", 35)) / 100.0
    min_s = float(prefs.get("boring_min_s", 8.0))
    gap_s = float(prefs.get("boring_gap_s", 2.0))

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

    low_bar = motion_threshold * pct
    total = 0
    for clip in clips:
        n = _detect_clip_boring(clip, low_bar, min_s, gap_s, motion_method)
        _notify(clip.id, 'boring', 'done', f"{clip.filename}: {n} boring span(s)", None, None)
        total += n
    return total


def _detect_clip_boring(
    clip: Clip,
    low_bar: float,
    min_s: float,
    gap_s: float,
    motion_method: str,
) -> int:
    col = (TelemetryPoint.motion_intensity_quick if motion_method == "jpg"
           else TelemetryPoint.motion_intensity)
    with get_session() as db:
        # Regenerate on every run, like peak marks
        db.query(Mark).filter(
            Mark.clip_id == clip.id,
            Mark.source == BORING_SOURCE,
        ).delete()
        rows = (
            db.query(TelemetryPoint)
            .filter(TelemetryPoint.clip_id == clip.id)
            .filter(col.isnot(None))
            .order_by(TelemetryPoint.timestamp_s)
            .all()
        )
        values = [(r.timestamp_s,
                   r.motion_intensity_quick if motion_method == "jpg" else r.motion_intensity)
                  for r in rows]
        keep_marks = [
            (m.in_s, m.out_s) for m in
            db.query(Mark).filter(Mark.clip_id == clip.id,
                                  Mark.status != MarkStatus.BORING).all()
        ]

    if len(values) < 3:
        return 0

    timestamps = [t for t, _ in values]
    smoothed   = _rolling_mean([v for _, v in values], window=3)

    regions = _low_motion_runs(timestamps, smoothed, low_bar, gap_s)
    regions = [r for r in _subtract_intervals(regions, keep_marks)
               if r[1] - r[0] >= min_s]
    if not regions:
        return 0

    marks = []
    for in_s, out_s in regions:
        span = [v for t, v in values if in_s <= t <= out_s]
        marks.append(Mark(
            clip_id=clip.id,
            in_s=round(in_s, 2),
            out_s=round(min(out_s, clip.duration_s or out_s), 2),
            score=round(sum(span) / len(span), 4) if span else 0.0,
            source=BORING_SOURCE,
            status=MarkStatus.BORING,
        ))
    with get_session() as db:
        db.add_all(marks)
    return len(marks)


def _rolling_mean(values: list[float], window: int = 3) -> list[float]:
    half = window // 2
    out = []
    for i in range(len(values)):
        lo, hi = max(0, i - half), min(len(values), i + half + 1)
        out.append(sum(values[lo:hi]) / (hi - lo))
    return out


def _low_motion_runs(
    timestamps: list[float],
    values: list[float],
    low_bar: float,
    gap_s: float,
) -> list[tuple[float, float]]:
    """Contiguous low-motion spans (for boring detection), bridging blips ≤ gap_s."""
    runs: list[tuple[float, float]] = []
    start = None
    last_dull = None
    for t, v in zip(timestamps, values):
        if v < low_bar:
            if start is None:
                start = t
            last_dull = t
        elif start is not None and t - last_dull > gap_s:
            runs.append((start, last_dull))
            start = None
    if start is not None:
        runs.append((start, last_dull))
    return runs


def _subtract_intervals(
    regions: list[tuple[float, float]],
    holes: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Cut *holes* (existing highlight marks) out of *regions*."""
    out = list(regions)
    for h_in, h_out in holes:
        nxt = []
        for r_in, r_out in out:
            if h_out <= r_in or h_in >= r_out:
                nxt.append((r_in, r_out))
                continue
            if r_in < h_in:
                nxt.append((r_in, h_in))
            if h_out < r_out:
                nxt.append((h_out, r_out))
        out = nxt
    return out


# ---------------------------------------------------------------------------
# Dull-gap marking — unclaimed footage between marks becomes its own category
# ---------------------------------------------------------------------------

DULL_SOURCE = "dull_gap"


def detect_dull_gaps(session_id: str, on_event=None) -> int:
    """
    Mark every span of footage not covered by any other mark as status=DULL.

    Runs after peak + boring detection so the timeline has no anonymous black
    gaps: everything is a highlight, boring, or dull. Gaps shorter than the
    dull_min_s app setting are ignored. Returns the number of dull marks created.
    """
    from axedup.prefs import get_prefs

    _notify = on_event or _NOOP
    min_s = float(get_prefs().get("dull_min_s", 3.0))

    with get_session() as db:
        clips = (
            db.query(Clip)
            .filter(Clip.session_id == session_id)
            .order_by(Clip.clip_order)
            .all()
        )

    total = 0
    for clip in clips:
        if not clip.duration_s:
            continue
        with get_session() as db:
            db.query(Mark).filter(
                Mark.clip_id == clip.id,
                Mark.source == DULL_SOURCE,
            ).delete()
            occupied = [
                (m.in_s, m.out_s) for m in
                db.query(Mark).filter(Mark.clip_id == clip.id).all()
            ]
        gaps = [g for g in _subtract_intervals([(0.0, clip.duration_s)], occupied)
                if g[1] - g[0] >= min_s]
        if gaps:
            with get_session() as db:
                db.add_all([
                    Mark(clip_id=clip.id, in_s=round(a, 2), out_s=round(b, 2),
                         score=0.0, source=DULL_SOURCE, status=MarkStatus.DULL)
                    for a, b in gaps
                ])
        _notify(clip.id, 'dull', 'done', f"{clip.filename}: {len(gaps)} dull gap(s)", None, None)
        total += len(gaps)
    return total
