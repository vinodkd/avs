"""Engine-level session management: list, get, delete.

All DB access and file cleanup goes through here so both the CLI and the UI
call the same code path — no duplicate _do_delete() in screens.
"""
import shutil

from avs import config
from avs.models.db import get_session as _db
from avs.models.schema import Clip, Mark, Session as SessionModel


def list_sessions(status: str | None = None) -> list[SessionModel]:
    with _db() as s:
        q = s.query(SessionModel)
        if status:
            q = q.filter(SessionModel.status == status)
        rows = q.order_by(SessionModel.created_at.desc()).all()
        s.expunge_all()
        return rows


def get_session(session_id: str) -> SessionModel | None:
    with _db() as s:
        row = s.query(SessionModel).filter(SessionModel.id == session_id).first()
        if row:
            s.expunge(row)
        return row


def delete_session(session_id: str) -> None:
    """Remove all DB rows and cached files for a session."""
    with _db() as db:
        clips = db.query(Clip).filter(Clip.session_id == session_id).all()
        clip_ids = [c.id for c in clips]
        mark_ids = [
            m.id
            for c in clips
            for m in db.query(Mark).filter(Mark.clip_id == c.id).all()
        ]
        sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if sess:
            db.delete(sess)

    # Cached files — best-effort, missing files are silently skipped
    (config.PREVIEW_DIR / f'{session_id}_preview.mp4').unlink(missing_ok=True)
    (config.STILL_DIR   / f'{session_id}_still.jpg').unlink(missing_ok=True)
    for sw in config.STILL_DIR.glob(f'{session_id}_grade_*.jpg'):
        sw.unlink(missing_ok=True)
    for cid in clip_ids:
        (config.PROXY_DIR      / f'{cid}.mp4').unlink(missing_ok=True)
        shutil.rmtree(config.THUMB_DIR       / cid, ignore_errors=True)
        shutil.rmtree(config.JPEG_FRAMES_DIR / cid, ignore_errors=True)
    for mid in mark_ids:
        (config.SEGMENT_DIR / f'{mid}.mp4').unlink(missing_ok=True)
        for enc in (config.SEGMENT_DIR / 'encoded').glob(f'{mid}_*.mp4'):
            enc.unlink(missing_ok=True)
