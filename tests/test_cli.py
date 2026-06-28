"""
CLI tests: verify that the CLI is a thin consumer of the engine.

What we test:
  - Input validation the CLI owns (path-not-found, unknown sport)
  - Engine-gating logic (review checks session status before opening browser)
  - on_event wiring (assemble/refine/export pass a real callable, not None)
  - Read-only list commands (sessions, profile) surface DB state correctly

What we do NOT test here:
  - Pipeline correctness (that lives in test_peaks.py and future stage tests)
  - UI rendering (no NiceGUI in scope here)
"""

import datetime
import uuid
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
from typer.testing import CliRunner

from avs.cli import app
from avs.models.db import get_session as db_session
from avs.models.schema import Clip, Mark, MarkStatus, Profile, Session, SessionStatus
from avs.presets.sports import DEFAULT_PROFILES

runner = CliRunner()


# ── Fixtures ──────────────────────────────────────────────────────────────────

_POST_ANALYSIS = (SessionStatus.READY, SessionStatus.ASSEMBLED, SessionStatus.EXPORTED)


def _make_session(status: str = SessionStatus.READY, sport: str = 'mtb') -> Session:
    """Insert a minimal Session (+ Profile if missing) into the isolated test DB.

    For READY/ASSEMBLED/EXPORTED status we also insert a Mark: the M001 migration
    in db._migrate() downgrades 'ready' sessions with no marks back to 'ingested'
    on every init_db() call (which the CLI triggers at startup).
    """
    sid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    with db_session() as db:
        if not db.query(Profile).filter(Profile.sport == sport).first():
            db.add(Profile(sport=sport, **DEFAULT_PROFILES[sport]))
        sess = Session(
            id=sid,
            sport=sport,
            source_path='/tmp/test_src',
            status=status,
            total_clips=1,
            total_duration_s=60.0,
            created_at=datetime.datetime.utcnow(),
        )
        db.add(sess)
        db.add(Clip(
            id=cid,
            session_id=sid,
            filename='test.mp4',
            filepath='/tmp/test.mp4',
            clip_order=0,
            duration_s=60.0,
        ))
        if status in _POST_ANALYSIS:
            db.add(Mark(
                id=str(uuid.uuid4()),
                clip_id=cid,
                in_s=0.0,
                out_s=5.0,
                source='motion_peak',
                status=MarkStatus.CANDIDATE,
            ))
    with db_session() as db:
        s = db.query(Session).filter(Session.id == sid).first()
        db.expunge(s)
        return s


# ── Fixture integrity ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('status', list(SessionStatus))
def test_make_session_readable_by_engine(status):
    """_make_session must produce sessions readable by the engine with correct status.

    Catches regressions where db._migrate() silently rewrites test data (e.g.
    M001 downgrades 'ready' sessions with no marks to 'ingested').
    """
    from avs.engine import sessions as eng
    sess = _make_session(status=status)
    loaded = eng.get_session(sess.id)
    assert loaded is not None, f'get_session returned None for status={status}'
    assert loaded.status == status, (
        f'Expected status={status!r} but engine returned {loaded.status!r}. '
        f'Check db._migrate() for rewrites.'
    )


# ── Input validation ──────────────────────────────────────────────────────────

def test_ingest_path_not_found():
    result = runner.invoke(app, ['ingest', '/no/such/path', '--sport', 'mtb'])
    assert result.exit_code == 1
    assert 'not found' in result.output.lower()


def test_profile_unknown_sport():
    result = runner.invoke(app, ['profile', 'not_a_real_sport'])
    assert result.exit_code == 1
    assert 'unknown' in result.output.lower()


# ── review: engine gating ─────────────────────────────────────────────────────

def test_review_session_not_found():
    result = runner.invoke(app, ['review', 'nonexistent-session-id'])
    assert result.exit_code == 1
    assert 'not found' in result.output.lower()


@pytest.mark.parametrize('status', [
    SessionStatus.IMPORTING,
    SessionStatus.INGESTED,
    SessionStatus.ANALYZING,
])
def test_review_blocks_when_not_ready(status):
    sess = _make_session(status=status)
    result = runner.invoke(app, ['review', sess.id])
    assert result.exit_code == 1
    assert 'not ready' in result.output.lower() or 'analyze' in result.output.lower()


@pytest.mark.parametrize('status', [
    SessionStatus.READY,
    SessionStatus.ASSEMBLED,
    SessionStatus.EXPORTED,
])
def test_review_directs_to_ui(status):
    sess = _make_session(status=status)
    result = runner.invoke(app, ['review', sess.id])
    assert result.exit_code == 0
    assert 'ui' in result.output.lower() or 'localhost' in result.output.lower()


# ── List commands: DB state surfaces correctly ─────────────────────────────────

def test_sessions_shows_table_header():
    result = runner.invoke(app, ['sessions'])
    assert result.exit_code == 0
    assert 'ID' in result.output and 'Status' in result.output


def test_sessions_lists_existing_session():
    sess = _make_session()
    result = runner.invoke(app, ['sessions'])
    assert result.exit_code == 0
    assert sess.id[:8] in result.output


def test_sessions_filter_by_status():
    ready_sess = _make_session(status=SessionStatus.READY)
    ingested_sess = _make_session(status=SessionStatus.INGESTED)
    result = runner.invoke(app, ['sessions', '--status', SessionStatus.READY.value])
    assert result.exit_code == 0
    assert ready_sess.id[:8] in result.output
    assert ingested_sess.id[:8] not in result.output


def test_profile_shows_known_sport():
    result = runner.invoke(app, ['profile', 'mtb'])
    assert result.exit_code == 0
    assert 'Color grade' in result.output or 'color_grade' in result.output.lower()
    assert 'Music energy' in result.output or 'music_energy' in result.output.lower()


# ── on_event wiring: events from the engine reach the terminal ────────────────

def _make_completed_token(captured_events: list) -> MagicMock:
    """Return a CancelToken mock that records on_event calls and completes immediately."""
    token = MagicMock()
    token.wait.return_value = None
    return token


def test_assemble_passes_on_event_to_engine():
    sess = _make_session(status=SessionStatus.READY)
    with patch('avs.engine.pipeline.run_assemble') as mock_run:
        token = MagicMock()
        token.wait.return_value = None
        mock_run.return_value = token
        runner.invoke(app, ['assemble', sess.id])
    _, kwargs = mock_run.call_args
    assert callable(kwargs.get('on_event')), 'on_event must be a callable, not None'


def test_refine_passes_on_event_to_engine():
    sess = _make_session(status=SessionStatus.ASSEMBLED)
    with patch('avs.engine.pipeline.run_assemble') as mock_run:
        token = MagicMock()
        token.wait.return_value = None
        mock_run.return_value = token
        runner.invoke(app, ['refine', sess.id])
    _, kwargs = mock_run.call_args
    assert callable(kwargs.get('on_event')), 'on_event must be a callable, not None'


def test_export_passes_on_event_to_engine():
    sess = _make_session(status=SessionStatus.ASSEMBLED)
    with patch('avs.engine.pipeline.run_export') as mock_run:
        token = MagicMock()
        token.wait.return_value = None
        mock_run.return_value = token
        runner.invoke(app, ['export', sess.id])
    _, kwargs = mock_run.call_args
    assert callable(kwargs.get('on_event')), 'on_event must be a callable, not None'


# ── End-to-end: CLI workflow sequence ────────────────────────────────────────

def test_cli_workflow_sequence():
    """The full ingest → analyze → review → assemble → export sequence.

    Each command's 'Next step' hint matches the next command; status gates
    enforce the correct order; the engine is mocked so this runs fast.
    """
    # ── ingest ──────────────────────────────────────────────────────────────
    fake_session = _make_session(status=SessionStatus.INGESTED)
    fake_session.camera = 'GoPro'
    fake_session.total_clips = 3
    fake_session.total_duration_s = 180.0

    with patch('avs.engine.pipeline.ingest_folder', return_value=fake_session):
        result = runner.invoke(app, ['ingest', '/tmp', '--sport', 'mtb'])
    assert result.exit_code == 0, result.output
    assert fake_session.id in result.output
    assert f'avs analyze {fake_session.id}' in result.output   # next-step hint

    session_id = fake_session.id

    # ── analyze gates: blocked before ingested ───────────────────────────────
    # (analyze actually calls engine; we just check review blocks before it finishes)
    not_ready = _make_session(status=SessionStatus.INGESTED)
    result = runner.invoke(app, ['review', not_ready.id])
    assert result.exit_code == 1
    assert 'not ready' in result.output.lower() or 'analyze' in result.output.lower()

    # ── analyze → review hint ────────────────────────────────────────────────
    ready_sess = _make_session(status=SessionStatus.READY)
    sid = ready_sess.id

    def _instant_token(*args, **kwargs):
        t = MagicMock(); t.wait.return_value = None; return t

    with patch('avs.engine.pipeline.run_proxy', side_effect=_instant_token), \
         patch('avs.engine.pipeline.run_scan',  side_effect=_instant_token), \
         patch('avs.engine.pipeline.run_peaks', side_effect=_instant_token):
        result = runner.invoke(app, ['analyze', sid])
    assert result.exit_code == 0, result.output
    assert f'avs review {sid}' in result.output              # next-step hint

    # ── review → directs to UI ───────────────────────────────────────────────
    result = runner.invoke(app, ['review', sid])
    assert result.exit_code == 0, result.output
    assert 'ui' in result.output.lower() or 'localhost' in result.output.lower()

    # ── assemble → export hint ───────────────────────────────────────────────
    with patch('avs.engine.pipeline.run_assemble', side_effect=_instant_token):
        result = runner.invoke(app, ['assemble', sid])
    assert result.exit_code == 0, result.output
    assert f'avs export {sid}' in result.output              # next-step hint

    # ── export succeeds ──────────────────────────────────────────────────────
    with patch('avs.engine.pipeline.run_export', side_effect=_instant_token):
        result = runner.invoke(app, ['export', sid])
    assert result.exit_code == 0, result.output


def test_on_event_messages_appear_in_cli_output():
    """Engine log messages (on_event) surface in the terminal, not swallowed."""
    sess = _make_session(status=SessionStatus.READY)

    def _fake_run_assemble(*args, **kwargs):
        on_event = kwargs.get('on_event')
        if on_event:
            on_event('cutting segment 1/3')
            on_event('cutting segment 2/3')
        token = MagicMock()
        token.wait.return_value = None
        return token

    with patch('avs.engine.pipeline.run_assemble', side_effect=_fake_run_assemble):
        result = runner.invoke(app, ['assemble', sess.id])

    assert 'cutting segment' in result.output
