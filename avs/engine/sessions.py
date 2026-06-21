"""Session and mark queries — thin DB wrappers."""
from avs.models.db import get_session as _db
from avs.models.schema import Session as SessionModel, Profile


def list_sessions(status: str | None = None) -> list[SessionModel]:
    with _db() as s:
        q = s.query(SessionModel)
        if status:
            q = q.filter(SessionModel.status == status)
        rows = q.order_by(SessionModel.created_at.desc()).all()
        # detach from session so they're usable after close
        s.expunge_all()
        return rows


def get_session(session_id: str) -> SessionModel | None:
    with _db() as s:
        row = s.query(SessionModel).filter(SessionModel.id == session_id).first()
        if row:
            s.expunge(row)
        return row


def delete_session(session_id: str) -> None:
    # Stub — full implementation in Step 6 (consolidates two _do_delete copies)
    raise NotImplementedError("delete_session not yet implemented in engine")
