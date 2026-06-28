"""
Tests for the scene-aware clip model in avs/processing/peaks.py.

Unit tests inject synthetic telemetry + scenes directly into the DB, avoiding
any dependency on video files or optical flow.

The integration smoke test ingests the fixture (tests/fixtures/source.mp4) end
to end and verifies marks land in the expected time windows.
"""
import math
import pytest
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────

_MOTION_SOURCES = ("motion_peak_jpg", "motion_peak")


def _make_session(db, sport="mtb"):
    """Create a minimal Session + Clip + Profile in the DB; return (session, clip)."""
    from avs.models.schema import Session, Clip, Profile, SessionStatus
    from avs.presets.sports import DEFAULT_PROFILES
    import uuid, datetime

    sid = str(uuid.uuid4())
    session = Session(
        id=sid,
        sport=sport,
        source_path="/tmp/test",
        status=SessionStatus.ANALYZING,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(session)

    cid = str(uuid.uuid4())
    clip = Clip(
        id=cid,
        session_id=sid,
        filename="test.mp4",
        filepath="/tmp/test.mp4",
        duration_s=60.0,
        clip_order=0,
    )
    db.add(clip)

    existing = db.query(Profile).filter(Profile.sport == sport).first()
    if not existing:
        pd = DEFAULT_PROFILES.get(sport, DEFAULT_PROFILES["mtb"])
        db.add(Profile(
            sport=sport,
            color_grade=pd["color_grade"],
            music_energy=pd["music_energy"],
            motion_threshold=pd["motion_threshold"],
            scene_detector=pd.get("scene_detector", "content"),
            clip_pre_min_s=2.0,
            clip_pre_max_s=4.0,
            clip_post_min_s=3.0,
            clip_post_max_s=6.0,
        ))

    db.flush()
    return session, clip


def _add_telemetry(db, clip_id: str, points: list[tuple[float, float]]) -> None:
    """Add (timestamp_s, motion_intensity_quick) rows for a clip."""
    from avs.models.schema import TelemetryPoint
    for ts, val in points:
        db.add(TelemetryPoint(
            clip_id=clip_id,
            timestamp_s=ts,
            motion_intensity_quick=val,
        ))
    db.flush()


def _add_scenes(db, clip_id: str, scenes: list[tuple[float, float]]) -> None:
    """Add Scene rows for a clip."""
    from avs.models.schema import Scene
    for i, (start, end) in enumerate(scenes):
        db.add(Scene(clip_id=clip_id, scene_index=i, start_s=start, end_s=end))
    db.flush()


def _marks_for_clip(db, clip_id: str) -> list:
    """Return all motion-peak marks for a clip, ordered by in_s."""
    from avs.models.schema import Mark, MarkStatus
    return (
        db.query(Mark)
        .filter(
            Mark.clip_id == clip_id,
            Mark.source.in_(_MOTION_SOURCES),
            Mark.status == MarkStatus.CANDIDATE,
        )
        .order_by(Mark.in_s)
        .all()
    )


# ── Unit tests: scene-aware clip model properties ────────────────────────────

class TestSceneAwareClipModel:

    def test_marks_are_scene_clamped(self):
        """Each mark's in_s/out_s must lie within its scene boundaries."""
        from avs.models.db import get_session as db_session
        from avs.processing.peaks import detect_peaks

        with db_session() as db:
            session, clip = _make_session(db)
            sid, cid = session.id, clip.id
            _add_scenes(db, cid, [(0.0, 25.0), (25.0, 60.0)])
            points = [(float(t), 0.8 if t in (10, 40) else 0.02) for t in range(60)]
            _add_telemetry(db, cid, points)

        detect_peaks(sid, motion_method="jpg")

        with db_session() as db:
            marks = _marks_for_clip(db, cid)

        assert len(marks) >= 2, f"expected at least 2 marks, got {len(marks)}"
        for m in marks:
            assert m.in_s >= m.scene_start, f"in_s {m.in_s} < scene_start {m.scene_start}"
            assert m.out_s <= m.scene_end,  f"out_s {m.out_s} > scene_end {m.scene_end}"

    def test_no_overlapping_marks(self):
        """Marks must not overlap — scene-aware model guarantees this by construction."""
        from avs.models.db import get_session as db_session
        from avs.processing.peaks import detect_peaks

        with db_session() as db:
            session, clip = _make_session(db)
            sid, cid = session.id, clip.id
            # Five scenes, one peak each — closely spaced
            _add_scenes(db, cid, [(i * 12.0, (i + 1) * 12.0) for i in range(5)])
            points = []
            for i in range(5):
                mid = i * 12.0 + 6.0
                for t in range(i * 12, (i + 1) * 12):
                    points.append((float(t), 0.9 if abs(t - mid) < 1 else 0.02))
            _add_telemetry(db, cid, points)

        detect_peaks(sid, motion_method="jpg")

        with db_session() as db:
            marks = _marks_for_clip(db, cid)

        assert len(marks) >= 2
        for i in range(len(marks) - 1):
            assert marks[i].out_s <= marks[i + 1].in_s, (
                f"overlap: mark {i} out_s={marks[i].out_s} > mark {i+1} in_s={marks[i+1].in_s}"
            )

    def test_normalised_score_populated(self):
        """Every motion-peak mark must have normalised_score in (0, 1]."""
        from avs.models.db import get_session as db_session
        from avs.processing.peaks import detect_peaks

        with db_session() as db:
            session, clip = _make_session(db)
            sid, cid = session.id, clip.id
            _add_scenes(db, cid, [(0.0, 30.0), (30.0, 60.0)])
            points = [(float(t), 0.8 if t in (10, 45) else 0.02) for t in range(60)]
            _add_telemetry(db, cid, points)

        detect_peaks(sid, motion_method="jpg")

        with db_session() as db:
            marks = _marks_for_clip(db, cid)

        assert marks, "no marks produced"
        for m in marks:
            assert m.normalised_score is not None, "normalised_score is None"
            assert 0.0 < m.normalised_score <= 1.0, (
                f"normalised_score {m.normalised_score} out of range"
            )

    def test_higher_score_gets_longer_context(self):
        """A peak with a higher score should receive at least as much context as a weaker one."""
        from avs.models.db import get_session as db_session
        from avs.processing.peaks import detect_peaks

        with db_session() as db:
            session, clip = _make_session(db)
            sid, cid = session.id, clip.id
            # Scene 0: strong peak (0.95); Scene 1: weak peak (0.65)
            _add_scenes(db, cid, [(0.0, 30.0), (30.0, 60.0)])
            points = (
                [(float(t), 0.95 if t == 10 else 0.02) for t in range(30)] +
                [(float(t), 0.65 if t == 45 else 0.02) for t in range(30, 60)]
            )
            _add_telemetry(db, cid, points)

        detect_peaks(sid, motion_method="jpg")

        with db_session() as db:
            marks = _marks_for_clip(db, cid)

        assert len(marks) >= 2
        strong = next((m for m in marks if (m.in_s + m.out_s) / 2 < 30), None)
        weak   = next((m for m in marks if (m.in_s + m.out_s) / 2 >= 30), None)
        assert strong and weak, "expected one mark per scene"

        assert strong.out_s - strong.in_s >= weak.out_s - weak.in_s - 0.1, (
            f"stronger mark ({strong.out_s - strong.in_s:.1f}s) "
            f"shorter than weaker ({weak.out_s - weak.in_s:.1f}s)"
        )

    def test_no_marks_below_threshold(self):
        """Peaks below motion_threshold must not produce marks (mtb threshold = 0.60)."""
        from avs.models.db import get_session as db_session
        from avs.processing.peaks import detect_peaks

        with db_session() as db:
            session, clip = _make_session(db, sport="mtb")
            sid, cid = session.id, clip.id
            _add_scenes(db, cid, [(0.0, 60.0)])
            # All values below mtb threshold of 0.60
            points = [(float(t), 0.45) for t in range(60)]
            _add_telemetry(db, cid, points)

        detect_peaks(sid, motion_method="jpg")

        with db_session() as db:
            marks = _marks_for_clip(db, cid)

        assert len(marks) == 0, f"expected 0 marks below threshold, got {len(marks)}"

    def test_single_scene_fallback(self):
        """If no Scene rows exist, treats the full clip as one scene without crashing."""
        from avs.models.db import get_session as db_session
        from avs.processing.peaks import detect_peaks

        with db_session() as db:
            session, clip = _make_session(db)
            sid, cid = session.id, clip.id
            # No scenes — peak detection must fall back gracefully
            points = [(float(t), 0.9 if t == 30 else 0.02) for t in range(60)]
            _add_telemetry(db, cid, points)

        detect_peaks(sid, motion_method="jpg")

        with db_session() as db:
            marks = _marks_for_clip(db, cid)

        assert len(marks) >= 1, "expected at least one mark with full-clip fallback"
        m = marks[0]
        assert m.scene_start == 0.0
        assert math.isclose(m.scene_end, 60.0, abs_tol=1.0)


# ── Integration smoke test ────────────────────────────────────────────────────

FIXTURE = Path(__file__).parent / "fixtures" / "source.mp4"


@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture source.mp4 not found")
class TestFixtureIntegration:
    """Run the full ingest → proxy → scan → peaks pipeline on the 120s synthetic
    fixture and verify marks land in the expected high-motion windows."""

    EXPECTED_HIGH_WINDOWS = [
        (20, 33,   "scene A (peaks 1+2)"),
        (46, 62,   "scene B (peak 3 + medium)"),
        (76, 91,   "scene C (peak 4 + medium)"),
        (103, 115, "scene D (peaks 5+6+spike)"),
    ]

    @pytest.fixture(scope="class")
    def session_with_marks(self, tmp_path_factory):
        """Ingest fixture, build proxy, scan, detect peaks. Returns session_id."""
        import shutil
        from avs.processing.ingest import ingest_folder
        from avs.processing.analysis import build_proxy_only, run_motion_scan
        from avs.processing.peaks import detect_peaks

        src_dir = tmp_path_factory.mktemp("fixture_src")
        shutil.copy(FIXTURE, src_dir / "source.mp4")

        session_obj = ingest_folder(src_dir, "mtb")
        sid = session_obj.id

        build_proxy_only(sid)
        run_motion_scan(sid, motion_method="jpg")
        detect_peaks(sid, motion_method="jpg")

        return sid

    def test_marks_found_in_high_windows(self, session_with_marks):
        from avs.models.db import get_session as db_session
        from avs.models.schema import Mark, Clip, MarkStatus

        sid = session_with_marks
        with db_session() as db:
            clip = db.query(Clip).filter(Clip.session_id == sid).first()
            marks = (
                db.query(Mark)
                .filter(
                    Mark.clip_id == clip.id,
                    Mark.source.in_(_MOTION_SOURCES),
                    Mark.status == MarkStatus.CANDIDATE,
                )
                .order_by(Mark.in_s)
                .all()
            )
            mark_times = [(m.in_s, m.out_s) for m in marks]

        assert mark_times, "no motion marks produced from fixture"

        for win_start, win_end, label in self.EXPECTED_HIGH_WINDOWS:
            found = any(
                in_s < win_end and out_s > win_start
                for in_s, out_s in mark_times
            )
            assert found, f"no mark overlaps expected window {win_start}–{win_end}s ({label})"

    def test_no_overlapping_marks(self, session_with_marks):
        from avs.models.db import get_session as db_session
        from avs.models.schema import Mark, Clip, MarkStatus

        sid = session_with_marks
        with db_session() as db:
            clip = db.query(Clip).filter(Clip.session_id == sid).first()
            marks = (
                db.query(Mark)
                .filter(
                    Mark.clip_id == clip.id,
                    Mark.source.in_(_MOTION_SOURCES),
                    Mark.status == MarkStatus.CANDIDATE,
                )
                .order_by(Mark.in_s)
                .all()
            )

        for i in range(len(marks) - 1):
            assert marks[i].out_s <= marks[i + 1].in_s + 0.01, (
                f"marks {i} and {i+1} overlap: "
                f"{marks[i].in_s:.1f}–{marks[i].out_s:.1f} / "
                f"{marks[i+1].in_s:.1f}–{marks[i+1].out_s:.1f}"
            )

    def test_normalised_score_and_scene_metadata(self, session_with_marks):
        from avs.models.db import get_session as db_session
        from avs.models.schema import Mark, Clip, MarkStatus

        sid = session_with_marks
        with db_session() as db:
            clip = db.query(Clip).filter(Clip.session_id == sid).first()
            marks = (
                db.query(Mark)
                .filter(
                    Mark.clip_id == clip.id,
                    Mark.source.in_(_MOTION_SOURCES),
                    Mark.status == MarkStatus.CANDIDATE,
                )
                .all()
            )

        assert marks
        for m in marks:
            assert m.normalised_score is not None, (
                f"mark at {m.in_s:.1f}s missing normalised_score"
            )
            assert 0.0 < m.normalised_score <= 1.0
            assert m.scene_start is not None, f"mark at {m.in_s:.1f}s missing scene_start"
            assert m.scene_end   is not None, f"mark at {m.in_s:.1f}s missing scene_end"
            assert m.scene_start <= m.in_s + 0.01
            assert m.out_s <= m.scene_end + 0.01
