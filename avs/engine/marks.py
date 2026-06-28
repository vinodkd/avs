"""Engine-level mark management: read and write mark review decisions."""
from avs.models.db import get_session as _db
from avs.models.schema import Clip, Mark, MarkStatus, Session as SessionModel


def get_marks(session_id: str) -> list[Mark]:
    """Return all reviewable marks for a session, ordered by clip then time."""
    with _db() as db:
        clip_ids = [
            c.id for c in db.query(Clip)
            .filter(Clip.session_id == session_id)
            .order_by(Clip.clip_order)
            .all()
        ]
        marks = (
            db.query(Mark)
            .join(Clip, Mark.clip_id == Clip.id)
            .filter(Mark.clip_id.in_(clip_ids))
            .filter(Mark.status.in_([
                MarkStatus.CANDIDATE, MarkStatus.ACCEPTED,
                MarkStatus.REJECTED, MarkStatus.BORING, MarkStatus.DULL,
            ]))
            .order_by(Clip.clip_order, Mark.in_s)
            .all()
        )
        db.expunge_all()
        return marks


def count_actionable_marks(session_id: str) -> int:
    """Count non-boring, non-dull marks for a session (the post-highlights count)."""
    with _db() as db:
        clip_ids = [
            c.id for c in db.query(Clip).filter(Clip.session_id == session_id).all()
        ]
        if not clip_ids:
            return 0
        return (
            db.query(Mark)
            .join(Clip, Mark.clip_id == Clip.id)
            .filter(Mark.clip_id.in_(clip_ids))
            .filter(Mark.status.notin_([MarkStatus.BORING, MarkStatus.DULL]))
            .count()
        )


def get_audio_spikes(clip_ids: list[str]) -> dict[str, list[float]]:
    """Return {clip_id: [spike_timestamps_s]} using the app's audio_spike_k setting."""
    from avs.prefs import get_prefs
    from avs.processing.audio import clip_audio_spikes
    spike_k = float(get_prefs().get('audio_spike_k', 3.0))
    return {cid: clip_audio_spikes(cid, spike_k) for cid in clip_ids}


def set_mark_statuses(decisions: dict[str, str]) -> int:
    """Write a batch of mark status decisions. decisions = {mark_id: ui_status_str}.

    ui_status_str is the JS-side value: 'in' | 'out' | 'skip' | 'dull'.
    Returns count of marks actually written.
    """
    _to_status = {
        'in':   MarkStatus.ACCEPTED,
        'out':  MarkStatus.REJECTED,
        'skip': MarkStatus.BORING,
        'dull': MarkStatus.DULL,
    }
    written = 0
    with _db() as db:
        for mark_id, ui_status in decisions.items():
            status = _to_status.get(ui_status)
            if not status:
                continue
            m = db.query(Mark).filter(Mark.id == mark_id).first()
            if m:
                m.status = status
                written += 1
    return written
