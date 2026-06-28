"""
Candidate mark generation from motion intensity (and telemetry when available).

Scene-aware clip model: for each PySceneDetect scene, finds the peak motion moment,
computes a score-proportional context window clamped to the scene boundary, and writes
one Mark per scene. Clips never overlap by construction (scene boundaries are hard walls).

Falls back to single-scene-per-clip if no scene data is stored (old sessions).
"""

from avs.models.db import get_session
from avs.models.schema import Clip, Mark, MarkStatus, Profile, Scene, Session, TelemetryPoint
from avs.presets.sports import DEFAULT_PROFILES

# Fallback pre/post when no profile ranges are set
_DEFAULT_PRE_MIN  = 1.0
_DEFAULT_PRE_MAX  = 4.0
_DEFAULT_POST_MIN = 2.0
_DEFAULT_POST_MAX = 6.0

MIN_PEAK_DISTANCE_S = 4.0  # kept for audio / boring / dull (not used by scene model)

_NOOP = lambda *_: None


def detect_peaks(
    session_id: str,
    on_event=None,
    motion_method: str = "proxy",
    cancel_token=None,
) -> int:
    """Generate candidate Mark rows for every clip in *session_id*.

    Uses the scene-aware model: one mark per PySceneDetect scene, window
    clamped to scene boundaries. Returns total marks created.
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
        pre_min  = (profile.clip_pre_min_s  if profile and profile.clip_pre_min_s  is not None else _DEFAULT_PRE_MIN)
        pre_max  = (profile.clip_pre_max_s  if profile and profile.clip_pre_max_s  is not None else _DEFAULT_PRE_MAX)
        post_min = (profile.clip_post_min_s if profile and profile.clip_post_min_s is not None else _DEFAULT_POST_MIN)
        post_max = (profile.clip_post_max_s if profile and profile.clip_post_max_s is not None else _DEFAULT_POST_MAX)

        clips = (
            db.query(Clip)
            .filter(Clip.session_id == session_id)
            .order_by(Clip.clip_order)
            .all()
        )

    from avs.prefs import get_prefs
    from avs.processing.audio import clip_audio_spikes
    prefs = get_prefs()
    spike_k     = float(prefs.get("audio_spike_k", 3.0))
    audio_boost = float(prefs.get("audio_boost", 1.25))

    total = 0
    for clip in clips:
        if cancel_token and cancel_token.is_cancelled():
            from avs.engine.cancel import CancelledError
            raise CancelledError()

        with get_session() as db:
            scenes = (
                db.query(Scene)
                .filter(Scene.clip_id == clip.id)
                .order_by(Scene.scene_index)
                .all()
            )

        spike_ts = clip_audio_spikes(clip.id, spike_k)
        n = _detect_clip_peaks(
            clip, motion_threshold, motion_method,
            spike_ts=spike_ts, audio_boost=audio_boost,
            scenes=scenes,
            pre_min=pre_min, pre_max=pre_max,
            post_min=post_min, post_max=post_max,
        )
        _notify(clip.id, 'peaks', 'done', f"{clip.filename}: {n} candidate(s)", None, None)
        total += n

    return total


# ---------------------------------------------------------------------------
# Per-clip peak detection (scene-aware)
# ---------------------------------------------------------------------------

def _detect_clip_peaks(
    clip: Clip,
    motion_threshold: float,
    motion_method: str = "proxy",
    spike_ts: list[float] | None = None,
    audio_boost: float = 1.0,
    scenes: list[Scene] | None = None,
    pre_min: float = _DEFAULT_PRE_MIN,
    pre_max: float = _DEFAULT_PRE_MAX,
    post_min: float = _DEFAULT_POST_MIN,
    post_max: float = _DEFAULT_POST_MAX,
) -> int:
    """Find the peak motion moment within each scene; write one Mark per scene.

    Scene boundaries are hard walls — windows are clamped to [scene.start_s, scene.end_s].
    Clips never overlap by construction. Score is normalised within the clip.

    Falls back to treating the full clip as one scene if no scene data exists.
    """
    source = "motion_peak_jpg" if motion_method == "jpg" else "motion_peak"

    with get_session() as db:
        db.query(Mark).filter(
            Mark.clip_id == clip.id,
            Mark.source == source,
        ).delete()

        col_filter = (
            TelemetryPoint.motion_intensity_quick.isnot(None)
            if motion_method == "jpg"
            else TelemetryPoint.motion_intensity.isnot(None)
        )
        rows = (
            db.query(TelemetryPoint)
            .filter(TelemetryPoint.clip_id == clip.id)
            .filter(col_filter)
            .order_by(TelemetryPoint.timestamp_s)
            .all()
        )

    if not rows:
        return 0

    timestamps  = [r.timestamp_s for r in rows]
    intensities = [
        (r.motion_intensity_quick if motion_method == "jpg" else r.motion_intensity)
        for r in rows
    ]

    # Normalise within this clip so score is comparable across clips
    global_max = max(intensities) if intensities else 1.0
    if global_max == 0:
        return 0

    # Use stored scenes; if none (old session or no cuts detected), one scene = full clip
    effective_scenes: list[tuple[float, float]] = (
        [(s.start_s, s.end_s) for s in scenes]
        if scenes
        else [(0.0, clip.duration_s)]
    )

    marks = []
    for scene_start, scene_end in effective_scenes:
        # Find the peak within this scene's time window
        scene_pairs = [
            (t, v) for t, v in zip(timestamps, intensities)
            if scene_start <= t <= scene_end
        ]
        if not scene_pairs:
            continue

        peak_t, peak_v = max(scene_pairs, key=lambda x: x[1])

        if peak_v < motion_threshold:
            continue  # below threshold; this scene becomes a dull gap

        norm_score = peak_v / global_max

        # Score-proportional context window, clamped to scene boundary
        pre  = pre_min  + norm_score * (pre_max  - pre_min)
        post = post_min + norm_score * (post_max - post_min)
        in_s  = max(scene_start, peak_t - pre)
        out_s = min(scene_end,   peak_t + post)

        # Audio spike inside the window boosts the score
        final_score = peak_v
        if spike_ts and audio_boost != 1.0:
            if any(in_s <= t <= out_s for t in spike_ts):
                final_score = min(1.0, peak_v * audio_boost)

        marks.append(Mark(
            clip_id=clip.id,
            in_s=round(in_s, 2),
            out_s=round(out_s, 2),
            score=round(final_score, 4),
            normalised_score=round(norm_score, 4),
            scene_start=scene_start,
            scene_end=scene_end,
            source=source,
            status=MarkStatus.CANDIDATE,
        ))

    if marks:
        with get_session() as db:
            db.add_all(marks)

    return len(marks)


# ---------------------------------------------------------------------------
# Boring-region detection
# ---------------------------------------------------------------------------

BORING_SOURCE = "boring_motion"


def detect_boring_regions(
    session_id: str,
    on_event=None,
    motion_method: str = "proxy",
    cancel_token=None,
) -> int:
    """Flag sustained low-motion spans as Mark rows with status=BORING.

    Reads the same motion series peak detection uses — no new video processing.
    Thresholds come from global app settings (avs/prefs.py):
      boring_threshold_pct — dull = smoothed motion < pct% of the sport's motion_threshold
      boring_min_s         — dull stretches shorter than this are ignored
      boring_gap_s         — blips above the line shorter than this don't break a region
    Spans overlapping any non-boring mark are cut around it. Returns boring marks created.
    """
    from avs.prefs import get_prefs

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
        if cancel_token and cancel_token.is_cancelled():
            from avs.engine.cancel import CancelledError
            raise CancelledError()
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
    """Contiguous low-motion spans, bridging blips <= gap_s."""
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
# Dull-gap marking
# ---------------------------------------------------------------------------

DULL_SOURCE = "dull_gap"


def detect_dull_gaps(session_id: str, on_event=None, cancel_token=None) -> int:
    """Mark every span not covered by any other mark as status=DULL.

    Runs after peak + boring detection so the timeline has no anonymous gaps.
    Gaps shorter than the dull_min_s app setting are ignored.
    """
    from avs.prefs import get_prefs

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
        if cancel_token and cancel_token.is_cancelled():
            from avs.engine.cancel import CancelledError
            raise CancelledError()
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


# ---------------------------------------------------------------------------
# Audio-only spike marks
# ---------------------------------------------------------------------------

AUDIO_SOURCE = "audio_spike"
_AUDIO_MARK_SCORE = 0.6


def detect_audio_spikes(session_id: str, on_event=None, cancel_token=None) -> int:
    """Create candidate marks around audio spikes that fall outside every existing mark window.

    Runs after detect_peaks so motion marks claim their spikes via score boost.
    Returns the number of marks created.
    """
    from avs.prefs import get_prefs
    from avs.processing.audio import clip_audio_spikes

    _notify = on_event or _NOOP
    spike_k = float(get_prefs().get("audio_spike_k", 3.0))

    with get_session() as db:
        clips = (
            db.query(Clip)
            .filter(Clip.session_id == session_id)
            .order_by(Clip.clip_order)
            .all()
        )

    total = 0
    for clip in clips:
        if cancel_token and cancel_token.is_cancelled():
            from avs.engine.cancel import CancelledError
            raise CancelledError()
        with get_session() as db:
            db.query(Mark).filter(
                Mark.clip_id == clip.id,
                Mark.source == AUDIO_SOURCE,
            ).delete()
            occupied = [
                (m.in_s, m.out_s) for m in
                db.query(Mark).filter(Mark.clip_id == clip.id).all()
            ]
        free = [t for t in clip_audio_spikes(clip.id, spike_k)
                if not any(a <= t <= b for a, b in occupied)]
        regions = _merge_overlapping([
            (max(0.0, t - _DEFAULT_PRE_MIN),
             min(clip.duration_s or t + _DEFAULT_POST_MAX, t + _DEFAULT_POST_MAX),
             _AUDIO_MARK_SCORE)
            for t in free
        ])
        if regions:
            with get_session() as db:
                db.add_all([
                    Mark(clip_id=clip.id, in_s=round(a, 2), out_s=round(b, 2),
                         score=s, source=AUDIO_SOURCE, status=MarkStatus.CANDIDATE)
                    for a, b, s in regions
                ])
        _notify(clip.id, 'audio_marks', 'done',
                f"{clip.filename}: {len(regions)} audio mark(s)", None, None)
        total += len(regions)
    return total


def _merge_overlapping(
    regions: list[tuple[float, float, float]],
) -> list[tuple[float, float, float]]:
    """Merge overlapping (in_s, out_s, score) regions, keeping max score. Used by audio marks."""
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
